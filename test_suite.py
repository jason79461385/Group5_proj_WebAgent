# test_suite.py
# [Updated] V4 - Singleton Driver (Fastest Mode for Windows)

import time
import sys
import json
import os
from collections import defaultdict
from browser_controller import initialize_agent
from agent_core import AgentCore
from test_logger import TestLogger



logger = TestLogger()
# 1. 讀取測試集 (保持不變)
def load_test_cases():
    dataset_path = "test_dataset_50.json" # 確保這裡讀取的是抽樣後的檔案
    try:
        with open(dataset_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            test_cases = []
            for item in data:
                test_cases.append({
                    "id": item.get("id", "Unknown"),
                    "web_name": item.get("web_name", "General"),
                    "goal": item.get("ques", ""),
                    "url": item.get("web", ""),
                    "expected_url_keyword": "",
                    "max_steps": 25 
                })
            return test_cases
    except FileNotFoundError:
        print(f"❌ 找不到 {dataset_path}，請先執行 sample_dataset.py！")
        return []

TEST_CASES = load_test_cases()

# 2. [Modified] 執行單一測試 (接收外部傳入的 driver)
def run_single_test(test_case, driver):
    """
    現在 driver 是從外部傳進來的，這個函式只負責跑邏輯，不負責開關瀏覽器。
    """
    print(f"\n🚀 Starting Test: {test_case['id']} ({test_case['web_name']})")
    print(f"🎯 Goal: {test_case['goal']}")
    logger.start_case(test_case)
    # [Cleanup] 每次新任務開始前，建議清除 Cookie，避免上一題的登入狀態影響這一題
    try:
        driver.delete_all_cookies()
        # driver.execute_script("window.localStorage.clear();") # 視情況選用
    except: pass

    # 強制導航至起始 URL
    start_url = test_case.get("url")
    if start_url:
        print(f"🔗 Navigating to start URL: {start_url}")
        try:
            driver.get(start_url)
            time.sleep(3)
        except Exception as e:
            print(f"❌ Failed to navigate: {e}")
            return False # 導航失敗直接下一題，但不關瀏覽器

    # 初始化 Agent (Agent 是任務級別的，每次都要新的)
    agent = AgentCore(driver, logger=logger)
    agent.start_new_task(test_case['goal'])
    
    success = False
    fail_reason = "" # 用來記錄失敗原因
    for i in range(test_case['max_steps']):
        print(f"\n--- Step {i+1} ---")
        try:
            brain_command = agent.analyze_next_step()
            
            # 判斷結束條件
            is_finished = brain_command.get("is_finished") or brain_command.get("action") == "finish"
            
            if is_finished:
                print(f"🏁 Agent declared finish. Final Answer: {brain_command.get('value', 'N/A')}")
                success = True 
                break
                
            # 執行動作
            if brain_command.get("action") == "goto_url":
                from browser_controller import perform_goto_url
                perform_goto_url(driver, brain_command.get("value"))
            else:
                agent.execute_action(brain_command)
                
        except Exception as e:
            print(f"❌ Error during step execution: {e}")
            break
    
    if not success:
        if not fail_reason: fail_reason = "Steps limit reached"
        print(f"❌ Failed: {fail_reason}")
        
    status = "PASS" if success else "FAIL"
    logger.end_case(status, error_msg=fail_reason)
    # 簡易驗證
    current_url = driver.current_url
    expected_keyword = test_case.get('expected_url_keyword')
    if expected_keyword and expected_keyword not in current_url:
        print(f"❌ URL Check Failed.")
        success = False
    
    return success

# 3. 統計與分析模組 (保持不變)
def analyze_results(results):
    total_tests = len(results)
    if total_tests == 0: return

    passed_count = sum(1 for r in results if r['status'] == 'PASS')
    failed_count = total_tests - passed_count
    pass_rate = (passed_count / total_tests) * 100

    print("\n" + "="*60)
    print(f"📊 測試結果總結 (Test Summary)")
    print("="*60)
    print(f"Total Tests : {total_tests}")
    print(f"Passed      : {passed_count} 🟢")
    print(f"Failed      : {failed_count} 🔴")
    print(f"Success Rate: {pass_rate:.2f}%")
    print("-" * 60)
    
    print(f"{'Website (Domain)':<25} | {'Total':<8} | {'Pass':<8} | {'Rate':<8}")
    print("-" * 60)
    
    domain_stats = defaultdict(lambda: {'total': 0, 'pass': 0})
    for r in results:
        domain = r['web_name']
        domain_stats[domain]['total'] += 1
        if r['status'] == 'PASS':
            domain_stats[domain]['pass'] += 1
            
    for domain, stats in domain_stats.items():
        rate = (stats['pass'] / stats['total']) * 100
        print(f"{domain:<25} | {stats['total']:<8} | {stats['pass']:<8} | {rate:.1f}%")
    print("="*60)

# 4. [Modified] 主程式：只啟動一次瀏覽器
if __name__ == "__main__":
    print("🧪 [Automated Test Suite] Starting (Singleton Driver Mode)...")
    
    if not TEST_CASES:
        print("❌ No test cases found. Exiting.")
        sys.exit(1)

    # 在最外層初始化瀏覽器
    main_driver = initialize_agent()
    
    if not main_driver:
        print("❌ Fatal: Could not start browser.")
        sys.exit(1)

    results = []
    
    try:
        # 你可以調整這裡，例如只跑前 5 個測試
        # target_cases = TEST_CASES[:5] 
        target_cases = TEST_CASES

        print(f"📋 預計執行 {len(target_cases)} 個測試案例...")
        
        for case in target_cases:
            # [Core Change] 把 main_driver 傳進去，而不是在裡面 init
            is_pass = run_single_test(case, main_driver)
            status = "PASS" if is_pass else "FAIL"
            
            results.append({
                "id": case['id'],
                "web_name": case['web_name'],
                "status": status
            })
            
            # 測試間短暫休息，讓網頁有時間喘息或 GC
            time.sleep(2) 

    except KeyboardInterrupt:
        print("\n⛔ 測試被用戶手動中斷！")
    
    finally:
        # [Final Cleanup] 所有測試跑完後，才關閉瀏覽器
        print("🔻 [System] 所有測試結束，正在關閉瀏覽器...")
        try:
            main_driver.quit()
            # Windows 強制清理 (保險起見)
            if sys.platform == "win32":
                try:
                    if hasattr(main_driver, 'service') and main_driver.service.process:
                        os.system(f"taskkill /F /PID {main_driver.service.process.pid} /T >nul 2>&1")
                except: pass
        except Exception as e:
            print(f"⚠️ 關閉時發生錯誤: {e}")

    # 執行最後分析
    analyze_results(results)