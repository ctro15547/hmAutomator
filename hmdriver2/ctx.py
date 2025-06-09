import os
import json
import re
import time
import threading
import subprocess

class hm_ctx:

    def __init__(self, d):
        self.d = d
        self.check_list = []
        self.cell_list = []
        self.ui_json = {}
        self.loop_sig = True

    def append_check_list(self, **kwargs):
        if 'text' in kwargs:
            self.check_list.append({kwargs['text']: 'text'})
        if 'textMatches' in kwargs:
            self.check_list.append({kwargs['textMatches']: 'textMatches'})
        if 'xpath' in kwargs:
            self.check_list.append({kwargs['xpath']: 'xpath'})
        if 'cell' in kwargs:
            # cell=lambda: (print(1), print(2)) if d(text='123').exists() else print('error')
            self.cell_list.append(kwargs['cell'])

    def _get_ui_json(self):
        _tmp_path = f"/data/local/tmp/{self.d.serial}_tmp.json"
        cmd = f"hdc -t {self.d.serial} shell uitest dumpLayout -p {_tmp_path}"
        os.popen(cmd).readlines()  # 获取当前xml
        cmd = f'hdc -t {self.d.serial} shell cat {_tmp_path}'
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, shell=True)
        output, error = process.communicate()
        output = output.decode('utf-8')
        error = error.decode('utf-8')
        if output:
            return json.loads(output)
        else:
            return {}  # 当解析失败时返回空字典，避免json解析异常
    
    def _find_control(self, data, label="text", **kwargs):
        """

        :retrun list[dict]
        """
        stack = [data]
        results = []
        text = kwargs.get('text')
        textMatches = kwargs.get('textMatches')
        if textMatches:
            pattern = re.compile(textMatches)
        
        while stack and (text or textMatches):
            current = stack.pop()
            
            if isinstance(current, dict):
                _tmp_text = current.get(label)
                if textMatches:
                    try:
                        a = pattern.search(_tmp_text)
                        if a:
                            results.append(current)
                    except:
                        pass
                else:
                    if _tmp_text == text:
                        results.append(current)
                stack.extend(current.values())
            elif isinstance(current, list):
                stack.extend(current)
        return results
    
    def _click_control(self, b):
        try:
            raw_Bounds = b.get('bounds')
            if not raw_Bounds:
                return False
            result = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", raw_Bounds)
            if result:
                g = result.groups()
                x = round((int(g[0]) + int(g[2])) / 2, 1)
                y = round((int(g[1]) + int(g[3])) / 2, 1)
                self.d.click(x, y)
                return True
        except:
            pass
        return False
    
    def _find_and_click_control(self):
        for check_item in self.check_list:
            for search_value, search_type in check_item.items():
                controls_found = []
                if search_type == 'textMatches':
                    controls_found = self._find_control(data=self.ui_json, textMatches=search_value)
                elif search_type == 'text':
                    controls_found = self._find_control(data=self.ui_json, text=search_value)
                elif search_type == 'xpath':
                    self.d.xpath(search_value).click_if_exists()
                    return
                elif search_type == 'cell':
                    for _cell in self.cell_list:
                        _cell()
                        return
                
                for control_element in controls_found:
                    if self._click_control(control_element):
                        return  # 成功点击后立即退出方法
    
    def _loop_find_and_click_control(self, time_sleep=0.1):
        while self.loop_sig:
            self.ui_json = self._get_ui_json()
            self._find_and_click_control()
            time.sleep(time_sleep)

    def start(self, time_sleep=0.1):
        thread = threading.Thread(target=self._loop_find_and_click_control, args=(time_sleep,))
        thread.setDaemon(True)
        thread.start()
        time.sleep(0.2)  # 等稳定

    def stop(self):
        self.loop_sig = False