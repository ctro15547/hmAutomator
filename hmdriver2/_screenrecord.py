# -*- coding: utf-8 -*-

import os
import time
import typing
import threading
import numpy as np
import queue
from datetime import datetime
import subprocess

import cv2

from . import logger
from ._client import HmClient
from .driver import Driver
from .exception import ScreenRecordError


class RecordClient(HmClient):
    def __init__(self, serial: str, d: Driver):
        super().__init__(serial)
        self.d = d
        self.serial = serial

        self.video_path = None
        self.jpeg_queue = queue.Queue()
        self.threads: typing.List[threading.Thread] = []

        # 屏幕服务状态
        self._stop_event = threading.Event()
        self.screen_server_status = False

        # 录屏状态
        self._record_event = threading.Event()
        self._record_status = False

        # 屏显状态
        self._show_phone_event = threading.Event()  # 内部
        self._show_phone_status = False  # 外部
        

        # 横竖屏状态 竖屏 0 横屏 1
        self.display_rotation = 0
        self.target_width, self.target_height = self.d.display_size

        # 截图图片数据
        self.screenshot_data = bytearray()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop_screen_server()

    def _send_msg(self, api: str, args: list):
        _msg = {
            "module": "com.ohos.devicetest.hypiumApiHelper",
            "method": "Captures",
            "params": {
                "api": api,
                "args": args
            },
            "request_id": datetime.now().strftime("%Y%m%d%H%M%S%f")
        }
        super()._send_msg(_msg)
    
    # 屏幕旋转状态
    def _get_display_rotation(self):
        time.sleep(3)  # 等待屏幕服务启动
        if not self.screen_server_status:
            assert False, "Screen server is not running."
        
        while not self._stop_event.is_set():
            img = cv2.imdecode(np.frombuffer(self.screenshot_data, np.uint8), cv2.IMREAD_COLOR)
            if img is None or img.size == 0:
                time.sleep(0.5)
                continue
            
            x, y = img.shape[1], img.shape[0]
            if x < y:
                self.display_rotation = 0
            else:
                self.display_rotation = 1
            time.sleep(0.5)

    def _get_data(self, api: str, args: list):
        # JPEG start and end markers.
        start_flag = b'\xff\xd8'
        end_flag = b'\xff\xd9'
        buffer = bytearray()
        while not self._stop_event.is_set():
            try:
                buffer += self._recv_msg(4096 * 1024, decode=False, print=False)
            except Exception as e:
                print(f"Error receiving data: {e}")
                self._stop_event.set()
                break

            start_idx = buffer.find(start_flag)
            end_idx = buffer.find(end_flag)
            while start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                # Extract one JPEG image
                self.screenshot_data = buffer[start_idx:end_idx + 2]
                buffer = buffer[end_idx + 2:]
                # Search for the next JPEG image in the buffer
                start_idx = buffer.find(start_flag)
                end_idx = buffer.find(end_flag)
        self.screen_server_status = False

    def start_screen_server(self):
        logger.info("Start RecordClient connection")

        self._connect_sock()

        self._send_msg("startCaptureScreen", [])

        reply: str = self._recv_msg(1024, decode=True, print=False)
        if "true" in reply:
            self._stop_event.clear()
            record_th = threading.Thread(target=self._get_display_rotation)
            record_th.daemon = True
            record_th.start()
            rotation_th = threading.Thread(target=self._get_display_rotation)
            rotation_th.daemon = True
            rotation_th.start()
            self.screen_server_status = True
            self.threads.append(record_th) 
            self.threads.append(rotation_th)
        else:
            raise ScreenRecordError("Failed to start device screen capture.")
        # 倒计时5秒
        for i in range(5, 0, -1):
            print(f"等待屏幕服务启动: {i}秒", end="\r", flush=True)
            time.sleep(1)
        print("等待屏幕服务启动结束", flush=True)
        return self
    
    def stop_screen_server(self):
        try:
            self._stop_event.set()
            self.screen_server_status = False
            self._record_event.set()
            self._record_status = False
            for t in self.threads:
                t.join()

            self._send_msg("stopCaptureScreen", [])
            self._recv_msg(1024, decode=True, print=False)

            # self.release()

            # Invalidate the cached property
            self.d._invalidate_cache('screenrecord')

        except Exception as e:
            logger.error(f"An error occurred: {e}")

    def _video_writer(self):
        """Write frames to video file."""
        
        img = None

        # 分辨率
        target_width = int(self.target_width * 0.5)
        target_height = int(self.target_height * 0.5)
        # 质量
        quality = 30
        # 帧率
        fps = 10
        
        frame_count = 0
        
        # 确保使用AVI格式和MJPG编码器，提高可靠性
        video_path = os.path.splitext(self.video_path)[0] + '.avi'
        
        # 创建视频写入器
        fourcc = cv2.VideoWriter_fourcc(*'MJPG')
        cv2_instance = cv2.VideoWriter(
            video_path,
            fourcc,
            fps,
            (target_width, target_height)
        )
        
        if not cv2_instance.isOpened():
            logger.error(f"无法创建视频写入器: {video_path}")
            return
            
        logger.info(f"使用AVI格式和MJPG编码器录制到: {video_path}")
        
        # 保存计时器
        save_interval = 10  # 每10秒记录一次日志
        last_save_time = time.time()
        
        while not self._record_event.is_set():
            current_time = time.time()
            start_time = current_time
            
            try:
                if self.screenshot_data is None:
                    time.sleep(0.1)
                    continue
                    
                img = cv2.imdecode(np.frombuffer(self.screenshot_data, np.uint8), cv2.IMREAD_COLOR)
                if img is None or img.size == 0:
                    continue

                # === 新增：分辨率调整 ===
                scaled_img = cv2.resize(
                    img, 
                    (target_width, target_height),  # 目标尺寸
                    interpolation=cv2.INTER_AREA  # 推荐用于缩小图像
                )

                # === 继续压缩流程 ===
                _, compressed_jpeg = cv2.imencode(
                    '.jpg', 
                    scaled_img,  # 使用缩放后的图像
                    [int(cv2.IMWRITE_JPEG_QUALITY), quality]
                )
                
                # 解码压缩后的JPEG数据
                img = cv2.imdecode(np.frombuffer(compressed_jpeg, np.uint8), cv2.IMREAD_COLOR)
                if img is None or img.size == 0:
                    continue
                    
                # 写入视频帧
                cv2_instance.write(img)
                frame_count += 1
                
                # 每10秒强制刷新视频文件
                if current_time - last_save_time >= save_interval:
                    # 在某些平台上，可以尝试调用flush方法（如果可用）
                    try:
                        if hasattr(cv2_instance, 'flush'):
                            cv2_instance.flush()
                    except:
                        pass
                        
                    logger.info(f"视频录制中: {video_path}，已写入{frame_count}帧")
                    last_save_time = current_time
                    
            except Exception as e:
                logger.error(f"处理视频帧时出错: {e}")
                
            time.sleep(max(0, 1 / fps - (time.time() - start_time)))

        # 录制结束，关闭资源
        cv2_instance.release()
        logger.info(f"录制结束，视频已保存: {video_path}")
        
        # 更新实际使用的视频路径
        self.video_path = video_path
        self._record_status = False

    def start_record(self, video_path: str):
        if not self.screen_server_status:
            raise ScreenRecordError("Screen server is not running.")

        self.video_path = video_path
        self._record_event.clear()
        self._record_status = True
        t = threading.Thread(target=self._video_writer)
        t.daemon = True
        t.start()
        self.threads.append(t)

    def stop_record(self):
        self._record_event.set()
        self._record_status = False
    
    def screenshot(self, path: str):
        if not self.screen_server_status:
            raise ScreenRecordError("Screen server is not running.")
        
        # 如果文件已存在，先删除
        if os.path.exists(path):
            os.remove(path)
            
        # 将screenshot_data写入文件
        with open(path, "wb") as f:
            f.write(self.screenshot_data)
            
        # 等待文件写入完成
        time.sleep(0.02)
        
        # 检查文件是否成功创建
        is_success = os.path.exists(path)
        
        return {
            "path": path,
            "is_success": is_success
        }
    
    def _shwo_phone_screen(self):
        if self.screen_server_status:
            assert False, "Screen server is running."

        img = cv2.imdecode(np.frombuffer(self.screenshot_data, np.uint8), cv2.IMREAD_COLOR)
        # 获取图片 xy
        x, y = img.shape[1], img.shape[0]
        if not self.display_rotation:
            width, height = int(x / 4), int(y / 4)
        else:
            width, height = int(y / 4), int(x / 4)
            
        _tmp_display_rotation = self.d.display_rotation

        window_name = f"Window_{self.serial}_{int(time.time())}"
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(window_name, width, height)  # 强制新尺寸

        _count = 0
        while not self._show_phone_event.is_set() and self._show_phone_status:
            start_time = time.time()
            _count += 1

            img = cv2.imdecode(np.frombuffer(self.screenshot_data, np.uint8), cv2.IMREAD_COLOR)
            if img is None or img.size == 0:
                time.sleep(0.1)
                continue

            if _count % 10 == 0 and self.display_rotation != _tmp_display_rotation:
                # 重新计算宽高
                if not self.display_rotation:
                    width, height = int(x / 4), int(y / 4)
                else:
                    width, height = int(y / 4), int(x / 4)
                # 旋转后交换窗口宽高
                window_name = f"Window_{self.serial}_{int(time.time())}"
                cv2.destroyWindow(window_name)
                cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
                cv2.resizeWindow(window_name, width, height)
                _tmp_display_rotation = self.display_rotation

            cv2.imshow(window_name, img)
            cv2.waitKey(0)

            time.sleep(max(0, 1 / 10 - (time.time() - start_time)))

        cv2.destroyWindow(window_name)
        self._show_phone_status = False
    
    def start_show_phone_screen(self):
        if not self.screen_server_status:
            raise ScreenRecordError("Screen server is not running.")
        
        self._show_phone_event.clear()
        self._show_phone_status = True
        t = threading.Thread(target=self._shwo_phone_screen)
        t.daemon = True
        t.start()
        self.threads.append(t)

    def stop_show_phone_screen(self):
        self._show_phone_event.set()
        self._show_phone_status = False