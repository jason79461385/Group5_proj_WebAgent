# memory_manager.py
# [Fix] 修正 add_memory 參數定義，加入 doc_id 支援
# 職責：儲存成功經驗、儲存失敗教訓、語意檢索

import chromadb
import uuid
import json
from datetime import datetime
from langchain_community.embeddings import OllamaEmbeddings
from config import EMBEDDING_SERVER_URL, EMBEDDING_MODEL_NAME, CHROMA_DB_PATH

class MemoryManager:
    def __init__(self):
        print(f"[Memory] 初始化 ChromaDB ({CHROMA_DB_PATH})...")
        
        # 1. 初始化 Embedding Function
        self.embedding_fn = OllamaEmbeddings(
            base_url=EMBEDDING_SERVER_URL, 
            model=EMBEDDING_MODEL_NAME
        )
        
        # 2. 初始化 Chroma Client (Persistent)
        self.client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        
        # 3. 取得或建立 Collection
        self.collection = self.client.get_or_create_collection(
            name="agent_experiences",
            metadata={"hnsw:space": "cosine"} # 使用餘弦相似度
        )

    def _get_embedding(self, text):
        """ 產生向量 """
        return self.embedding_fn.embed_query(text)

    # [關鍵修正] 這裡必須包含 doc_id=None
    def add_memory(self, user_goal: str, trajectory: list, outcome: str, insight: str = "", doc_id: str = None):
        """ 
        [Updated] 統一的儲存入口 
        doc_id: 若提供 (例如來自 init_knowledge.py)，則進行 Upsert (更新/插入)；若無，則自動生成 UUID (新增)。
        """
        # 決定 ID 與動作類型
        if doc_id is None:
            doc_id = str(uuid.uuid4())
            action_type = "新增"
        else:
            action_type = "同步" # 有 ID 代表是系統知識同步

        # 準備向量化文字
        text_to_embed = user_goal 
        embedding = self._get_embedding(text_to_embed)
        
        # 確保 trajectory 是字串格式 (存入 metadata)
        if isinstance(trajectory, list):
            traj_str = "\n".join([str(step) for step in trajectory])
        else:
            traj_str = str(trajectory)
        
        # 建構 Metadata
        metadata = {
            "goal": user_goal,
            "outcome": outcome,
            "insight": insight,
            "timestamp": datetime.now().isoformat(),
            "trajectory": traj_str 
        }

        # 執行 Upsert (存在則更新，不存在則寫入)
        self.collection.upsert(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[text_to_embed], # 搜尋時匹配這段文字
            metadatas=[metadata]
        )
        
        # 僅在新增時印出 Log，避免同步時洗版
        if action_type == "新增":
            print(f"💾 [Memory] 已儲存 ({outcome}): {user_goal}")

    def retrieve_relevant_memory(self, current_goal: str, k=2) -> dict:
        """
        檢索相關記憶，回傳包含 'success_path' 和 'warnings' 的字典
        """
        query_vec = self._get_embedding(current_goal)
        
        results = self.collection.query(
            query_embeddings=[query_vec],
            n_results=k
        )
        
        # 解析結果容器
        retrieved = {
            "success_path": None,
            "warnings": []
        }
        
        if not results['metadatas'] or not results['metadatas'][0]:
            return retrieved

        for meta in results['metadatas'][0]:
            outcome = meta.get('outcome')
            
            # 優先找一個成功案例
            if outcome == 'success' and not retrieved['success_path']:
                retrieved['success_path'] = meta.get('trajectory', '')
                
            # 同時收集相關的失敗教訓
            elif outcome == 'failure' or outcome == 'insight':
                insight = meta.get('insight', '')
                if insight:
                    retrieved['warnings'].append(insight)
                    
        return retrieved