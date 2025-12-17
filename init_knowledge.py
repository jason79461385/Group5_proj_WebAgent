# init_knowledge.py
# [Updated] 模組化知識庫，提供固定 ID 以供同步

from memory_manager import MemoryManager

def sync_system_knowledge():
    """
    每次程式啟動時呼叫此函式，確保 Agent 擁有最新的 SOP。
    使用固定 ID (sop_001, sop_002...) 來避免重複。
    """
    print("📚 [System] 正在同步核心知識庫...")
    memory = MemoryManager()
    
    knowledge_base = [
        {
            "id": "sop_001_video_latest",
            "goal": "在影音平台尋找最新影片 (Latest Video on YouTube/Bilibili)",
            "trajectory": [
                "策略 A (優先)：進入頻道找最新。",
                "Step 1: 點擊搜尋結果中的『頻道名稱/頭像』進入頻道首頁。",
                "Step 2: 點擊『Videos (影片)』或『最新』分頁。",
                "Step 3: 點擊列表第一支影片。",
                "策略 B (備選)：使用篩選器 (Filters)。",
                "Step 1: 點擊 'Filters' 按鈕。",
                "Step 2: **注意**：若篩選選單已彈出，直接點擊 'Upload date' 或 'Sort by Date'。",
                "Step 3: 點擊列表第一支影片。"
            ],
            "outcome": "success",
            "insight": "General SOP: Check Channel first. If using filters, interact with the modal if open."
        },
        {
            "id": "sop_002_video_verify",
            "goal": "驗證影片是否正確 (Verify Video)",
            "trajectory": [
                "策略：影片標題可能不包含作者名字。",
                "判斷：請檢查頁面上的 **作者名稱 (Uploader/UP主)** 是否匹配。",
                "規則：只要作者正確，且這是列表中的第一支影片，即使標題完全不同，也視為任務完成 (is_finished: true)。"
            ],
            "outcome": "success",
            "insight": "Verification Rule: Check the Uploader, not just the Title."
        },
        {
            "id": "sop_003_ad_block",
            "goal": "處理影音廣告 (Skip Video Ads)",
            "trajectory": [
                "策略：若畫面出現倒數計時或 Skip 按鈕，視為廣告。",
                "Action: 點擊 'Skip', 'Skip Ad', '略過廣告', '跳过' 按鈕。",
                "Action: 若無按鈕，請等待 (wait) 直到廣告結束。",
            ],
            "outcome": "success",
            "insight": "Standard procedure for handling pre-roll ads."
        },
        {
            "id": "sop_004_google_maps",
            "goal": "使用 Google Maps 導航",
            "trajectory": [
                "策略：使用 URL Hack 直接開啟導航。",
                "Action: goto_url 'https://www.google.com/maps/dir/Your+location/3{目的地}'"
            ],
            "outcome": "success",
            "insight": "Shortcut for navigation."
        },
        {
            "id": "sop_005_social_handle",
            "goal": "社群帳號搜尋與驗證 (Search Social Media Handle)",
            "trajectory": [
                "策略：優先檢查 URL 中的 Handle (如 @username)。",
                "判斷：即使頁面標題 (Display Name) 與搜尋關鍵字不完全一致，只要 URL Handle 吻合，即視為成功。",
                "Action: 若剛從 Google 搜尋點入，請先進行驗證，不要急著站內搜尋。"
            ],
            "outcome": "success",
            "insight": "Identity verification rule for social platforms."
        }
    ]

    for item in knowledge_base:
        memory.add_memory(
            user_goal=item['goal'],
            trajectory=item['trajectory'],
            outcome=item['outcome'],
            insight=item['insight'],
            doc_id=item['id'] # 傳入 ID 進行 Upsert
        )
    
    print("✅ 核心知識庫同步完成 (無重複資料)。")

if __name__ == "__main__":
    sync_system_knowledge()