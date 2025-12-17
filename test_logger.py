# test_logger.py
import os
import json
import time
from datetime import datetime

class TestLogger:
    def __init__(self, log_dir="test_logs"):
        # 建立以時間命名的資料夾，例如 test_logs/2023-10-27_10-30-00
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.session_dir = os.path.join(log_dir, timestamp)
        os.makedirs(self.session_dir, exist_ok=True)
        
        self.current_log = {}
        self.log_filepath = ""

    def start_case(self, test_case):
        """ 開始一個新的測試案例紀錄 """
        self.current_log = {
            "id": test_case['id'],
            "goal": test_case['goal'],
            "url": test_case.get('url', ''),
            "web_name": test_case.get('web_name', ''),
            "start_time": time.time(),
            "status": "RUNNING",
            "steps": [],
            "error_msg": ""
        }
        # 預先定義檔案路徑
        safe_id = str(test_case['id']).replace("/", "_")
        self.log_filepath = os.path.join(self.session_dir, f"{safe_id}.json")

    def log_step(self, step_num, step_data):
        """ 記錄單一步驟的詳細資訊 """
        # step_data 包含: thought, action, coords, page_content_snippet 等
        entry = {
            "step": step_num,
            "timestamp": time.time(),
            **step_data
        }
        self.current_log["steps"].append(entry)
        # 即時寫入，避免程式崩潰導致 Log 遺失
        self._save_to_disk()

    def end_case(self, status, error_msg=""):
        """ 結束測試並標記狀態 """
        self.current_log["status"] = status
        self.current_log["end_time"] = time.time()
        self.current_log["duration"] = self.current_log["end_time"] - self.current_log["start_time"]
        self.current_log["error_msg"] = error_msg
        self._save_to_disk()

    def _save_to_disk(self):
        try:
            with open(self.log_filepath, 'w', encoding='utf-8') as f:
                json.dump(self.current_log, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"❌ Log 寫入失敗: {e}")