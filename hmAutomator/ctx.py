import os
import json
import uuid
import re
import time
import threading
import subprocess

class hm_ctx:

    def __init__(self, d):
        self.d = d
        self.check_list = []
        self.call_list = []
        self.xpath_list = []
        self.ui_json = {}
        self.loop_sig = False

    def __call__(self, **kwargs):
        if 'call' in kwargs and ('text' in kwargs or 'textMatches' in kwargs):
            # cell=lambda: (print(1), print(2), True) if d(text='123').exists() else (False,)
            self.call_list.append(['text' if 'text' in kwargs else 'textMatches',
                                   kwargs['text'] if 'text' in kwargs else kwargs['textMatches'],
                                   kwargs['call']])
        elif 'xpath' in kwargs and ('text' in kwargs or 'textMatches' in kwargs):
            self.xpath_list.append(['text' if 'text' in kwargs else 'textMatches',
                                    kwargs['text'] if 'text' in kwargs else kwargs['textMatches'], 
                                    kwargs['xpath']])
        # ====================这上面要条件限制才行====================
        elif 'text' in kwargs:
            self.check_list.append({kwargs['text']: 'text'})
        elif 'textMatches' in kwargs:
            self.check_list.append({kwargs['textMatches']: 'textMatches'})
        return self

    def _get_ui_json(self):
        _tmp_path = f"/data/local/tmp/{uuid.uuid4().hex}.json"
        cmd = f"hdc -t {self.d.serial} shell uitest dumpLayout -p {_tmp_path}"
        os.popen(cmd).readlines()  # 获取当前xml
        cmd = f'hdc -t {self.d.serial} shell cat {_tmp_path}' 
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, shell=True)
        output, error = process.communicate()
        output = output.decode('utf-8')
        error = error.decode('utf-8')
        if output:
            self.d.shell(f"rm -rf {_tmp_path}")
            try:
                return json.loads(output)
            except Exception as e:
                return {}
        else:
            self.d.shell(f"rm -rf {_tmp_path}")
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

        for _call in self.call_list:
            _type, _text, _call = _call
            try:
                if _type == 'text':
                    if self._find_control(data=self.ui_json, text=_text) and _call():
                        return
                elif _type == 'textMatches':
                    if self._find_control(data=self.ui_json, textMatches=_text) and _call():
                        return
            except:
                pass
        
        for x in self.xpath_list:
            _type, _text, _xpath = x
            try:
                if _type == 'text':
                    if self._find_control(data=self.ui_json, text=_text):
                        self.d.xpath(_xpath).click()
                        return
                elif _type == 'textMatches':
                    if self._find_control(data=self.ui_json, textMatches=_text):
                        self.d.xpath(_xpath).click()
                        return
            except:
                pass

        controls_found = []
        for check_item in self.check_list:
            for search_value, search_type in check_item.items():
                if search_type == 'textMatches':
                    controls_found.append(self._find_control(data=self.ui_json, textMatches=search_value))
                elif search_type == 'text':
                    controls_found.append(self._find_control(data=self.ui_json, text=search_value))

        for control_element in controls_found:
            if self._click_control(control_element):
                return  # 成功点击后立即退出方法
    
    def _loop_find_and_click_control(self, time_sleep=0.1):
        while self.loop_sig:
            try:
                self.ui_json = self._get_ui_json()
                self._find_and_click_control()
            except Exception as e:
                print('ctx loop error',e)
                time.sleep(time_sleep)
                continue
            time.sleep(time_sleep)

    def start(self, time_sleep=3):
        if self.loop_sig:
            return
        self.loop_sig = True
        thread = threading.Thread(target=self._loop_find_and_click_control, args=(time_sleep,))
        thread.setDaemon(True)
        thread.start()
        time.sleep(0.2)  # 等稳定

    def stop(self):
        self.loop_sig = False
        self.ui_json = {}
    
    def click(self):
        ...


if __name__ == '__main__':

    ctx = hm_ctx(d)
    ctx(text='123').click()