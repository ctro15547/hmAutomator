# -*- coding: utf-8 -*-

import os
import time
import typing
import threading
import numpy as np
import queue
from datetime import datetime

import cv2

from . import logger
from ._client import HmClient
from .driver import Driver
from .exception import ScreenRecordError


class RecordClient(HmClient):
    def __init__(self, serial: str, d: Driver):
        super().__init__(serial)
        self.d = d

        self.video_path = None
        self.jpeg_queue = queue.Queue()
        self.threads: typing.List[threading.Thread] = []

        # 屏幕服务状态
        self._stop_event = threading.Event()
        self.screen_server_status = False

        # 录屏状态
        self._record_event = threading.Event()
        self._record_status = False

        self.target_width, self.target_height = self.d.display_size

        # 截图图片数据
        self.screenshot_data = None

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
                break

            start_idx = buffer.find(start_flag)
            end_idx = buffer.find(end_flag)
            while start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                # Extract one JPEG image
                self.screenshot_data = buffer[start_idx:end_idx + 2]
                if self._record_status:
                    self.jpeg_queue.put(self.screenshot_data)
                # self.jpeg_queue.put(jpeg_image)

                buffer = buffer[end_idx + 2:]

                # Search for the next JPEG image in the buffer
                start_idx = buffer.find(start_flag)
                end_idx = buffer.find(end_flag)

    def start_screen_server(self):
        logger.info("Start RecordClient connection")

        self._connect_sock()

        self._send_msg("startCaptureScreen", [])

        reply: str = self._recv_msg(1024, decode=True, print=False)
        if "true" in reply:
            self._stop_event.clear()
            record_th = threading.Thread(target=self._get_data)
            record_th.daemon = True
            record_th.start()
            self.screen_server_status = True
            self.threads.append(record_th) 
        else:
            raise ScreenRecordError("Failed to start device screen capture.")

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

            self.release()

            # Invalidate the cached property
            self.d._invalidate_cache('screenrecord')

        except Exception as e:
            logger.error(f"An error occurred: {e}")

    def _video_writer(self):
        """Write frames to video file."""
        cv2_instance = None
        img = None

        target_width = int(self.target_width * 0.5)
        target_height = int(self.target_height * 0.5)
        quality = 30
        while not self._record_event.is_set():
            try:
                jpeg_image = self.jpeg_queue.get(timeout=0.1)
                img = cv2.imdecode(np.frombuffer(jpeg_image, np.uint8), cv2.IMREAD_COLOR)

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

                compressed_bytes = compressed_jpeg.tobytes()
                img = cv2.imdecode(np.frombuffer(compressed_bytes, np.uint8), cv2.IMREAD_COLOR)
            except queue.Empty:
                pass
            if img is None or img.size == 0:
                continue
            if cv2_instance is None:
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                cv2_instance = cv2.VideoWriter(self.video_path, fourcc, 10, (target_width, target_height))

            cv2_instance.write(img)

        if cv2_instance:
            cv2_instance.release()
    
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

