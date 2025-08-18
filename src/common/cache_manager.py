import time
import json
import sqlite3
import chromadb
import hashlib
import inspect
import numpy as np
import faiss
from typing import Any, Dict, Optional
from src.common.logger import get_logger
from src.llm_models.utils_model import LLMRequest
from src.config.config import global_config, model_config

logger = get_logger("cache_manager")

class CacheManager:
    """
    一个支持分层和语义缓存的通用工具缓存管理器。
    采用单例模式，确保在整个应用中只有一个缓存实例。
    L1缓存: 内存字典 (KV) + FAISS (Vector)。
    L2缓存: SQLite (KV) + ChromaDB (Vector)。
    """
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(CacheManager, cls).__new__(cls)
        return cls._instance

    def __init__(self, default_ttl: int = 3600, db_path: str = "data/cache.db", chroma_path: str = "data/chroma_db"):
        """
        初始化缓存管理器。
        """
        if not hasattr(self, '_initialized'):
            self.default_ttl = default_ttl
            
            # L1 缓存 (内存)
            self.l1_kv_cache: Dict[str, Dict[str, Any]] = {}
            embedding_dim = global_config.lpmm_knowledge.embedding_dimension
            self.l1_vector_index = faiss.IndexFlatIP(embedding_dim)
            self.l1_vector_id_to_key: Dict[int, str] = {}
            
            # L2 缓存 (持久化)
            self.db_path = db_path
            self._init_sqlite()
            self.chroma_client = chromadb.PersistentClient(path=chroma_path)
            self.chroma_collection = self.chroma_client.get_or_create_collection(name="semantic_cache")
            
            # 嵌入模型
            self.embedding_model = LLMRequest(model_config.model_task_config.embedding)

            self._initialized = True
            logger.info("缓存管理器已初始化: L1 (内存+FAISS), L2 (SQLite+ChromaDB)")

    def _init_sqlite(self):
        """初始化SQLite数据库和表结构。"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    expires_at REAL
                )
            """)
            conn.commit()

    def _validate_embedding(self, embedding_result: Any) -> Optional[np.ndarray]:
        """
        验证和标准化嵌入向量格式
        """
        try:
            if embedding_result is None:
                return None
                
            # 确保embedding_result是一维数组或列表
            if isinstance(embedding_result, (list, tuple, np.ndarray)):
                # 转换为numpy数组进行处理
                embedding_array = np.array(embedding_result)
                
                # 如果是多维数组，展平它
                if embedding_array.ndim > 1:
                    embedding_array = embedding_array.flatten()
                
                # 检查维度是否符合预期
                expected_dim = global_config.lpmm_knowledge.embedding_dimension
                if embedding_array.shape[0] != expected_dim:
                    logger.warning(f"嵌入向量维度不匹配: 期望 {expected_dim}, 实际 {embedding_array.shape[0]}")
                    return None
                
                # 检查是否包含有效的数值
                if np.isnan(embedding_array).any() or np.isinf(embedding_array).any():
                    logger.warning("嵌入向量包含无效的数值 (NaN 或 Inf)")
                    return None
                
                return embedding_array.astype('float32')
            else:
                logger.warning(f"嵌入结果格式不支持: {type(embedding_result)}")
                return None
                
        except Exception as e:
            logger.error(f"验证嵌入向量时发生错误: {e}")
            return None

    def _generate_key(self, tool_name: str, function_args: Dict[str, Any], tool_class: Any) -> str:
        """生成确定性的缓存键，包含代码哈希以实现自动失效。"""
        try:
            source_code = inspect.getsource(tool_class)
            code_hash = hashlib.md5(source_code.encode()).hexdigest()
        except Exception as e:
            code_hash = "unknown"
            # 获取更清晰的类名
            class_name = getattr(tool_class, '__name__', str(tool_class))
            # 简化错误信息
            error_msg = str(e).replace(str(tool_class), class_name)
            logger.warning(f"无法获取 {class_name} 的源代码，代码哈希将为 'unknown'。原因: {error_msg}")
        try:
            sorted_args = json.dumps(function_args, sort_keys=True)
        except TypeError:
            sorted_args = repr(sorted(function_args.items()))
        return f"{tool_name}::{sorted_args}::{code_hash}"

    async def get(self, tool_name: str, function_args: Dict[str, Any], tool_class: Any, semantic_query: Optional[str] = None) -> Optional[Any]:
        """
        从缓存获取结果，查询顺序: L1-KV -> L1-Vector -> L2-KV -> L2-Vector。
        """
        # 步骤 1: L1 精确缓存查询
        key = self._generate_key(tool_name, function_args, tool_class)
        logger.debug(f"生成的缓存键: {key}")
        if semantic_query:
            logger.debug(f"使用的语义查询: '{semantic_query}'")

        if key in self.l1_kv_cache:
            entry = self.l1_kv_cache[key]
            if time.time() < entry["expires_at"]:
                logger.info(f"命中L1键值缓存: {key}")
                return entry["data"]
            else:
                del self.l1_kv_cache[key]

        # 步骤 2: L1/L2 语义和L2精确缓存查询
        query_embedding = None
        if semantic_query and self.embedding_model:
            embedding_result = await self.embedding_model.get_embedding(semantic_query)
            if embedding_result:
                validated_embedding = self._validate_embedding(embedding_result)
                if validated_embedding is not None:
                    query_embedding = np.array([validated_embedding], dtype='float32')

        # 步骤 2a: L1 语义缓存 (FAISS)
        if query_embedding is not None and self.l1_vector_index.ntotal > 0:
            faiss.normalize_L2(query_embedding)
            distances, indices = self.l1_vector_index.search(query_embedding, 1)
            if indices.size > 0 and distances[0][0] > 0.75: # IP 越大越相似
                hit_index = indices[0][0]
                l1_hit_key = self.l1_vector_id_to_key.get(hit_index)
                if l1_hit_key and l1_hit_key in self.l1_kv_cache:
                    logger.info(f"命中L1语义缓存: {l1_hit_key}")
                    return self.l1_kv_cache[l1_hit_key]["data"]

        # 步骤 2b: L2 精确缓存 (SQLite)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value, expires_at FROM cache WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                value, expires_at = row
                if time.time() < expires_at:
                    logger.info(f"命中L2键值缓存: {key}")
                    data = json.loads(value)
                    # 回填 L1
                    self.l1_kv_cache[key] = {"data": data, "expires_at": expires_at}
                    return data
                else:
                    cursor.execute("DELETE FROM cache WHERE key = ?", (key,))
                    conn.commit()

        # 步骤 2c: L2 语义缓存 (ChromaDB)
        if query_embedding is not None:
            results = self.chroma_collection.query(query_embeddings=query_embedding.tolist(), n_results=1)
            if results and results['ids'] and results['ids'][0]:
                distance = results['distances'][0][0] if results['distances'] and results['distances'][0] else 'N/A'
                logger.debug(f"L2语义搜索找到最相似的结果: id={results['ids'][0]}, 距离={distance}")
                if distance != 'N/A' and distance < 0.75:
                    l2_hit_key = results['ids'][0]
                    logger.info(f"命中L2语义缓存: key='{l2_hit_key}', 距离={distance:.4f}")
                    with sqlite3.connect(self.db_path) as conn:
                        cursor = conn.cursor()
                    cursor.execute("SELECT value, expires_at FROM cache WHERE key = ?", (l2_hit_key if isinstance(l2_hit_key, str) else l2_hit_key[0],))
                    row = cursor.fetchone()
                    if row:
                        value, expires_at = row
                        if time.time() < expires_at:
                            data = json.loads(value)
                            logger.debug(f"L2语义缓存返回的数据: {data}")
                            # 回填 L1
                            self.l1_kv_cache[key] = {"data": data, "expires_at": expires_at}
                            if query_embedding is not None:
                                try:
                                    new_id = self.l1_vector_index.ntotal
                                    faiss.normalize_L2(query_embedding)
                                    self.l1_vector_index.add(x=query_embedding)
                                    self.l1_vector_id_to_key[new_id] = key
                                except Exception as e:
                                    logger.error(f"回填L1向量索引时发生错误: {e}")
                            return data

        logger.debug(f"缓存未命中: {key}")
        return None

    async def set(self, tool_name: str, function_args: Dict[str, Any], tool_class: Any, data: Any, ttl: Optional[int] = None, semantic_query: Optional[str] = None):
        """将结果存入所有缓存层。"""
        if ttl is None:
            ttl = self.default_ttl
        if ttl <= 0:
            return

        key = self._generate_key(tool_name, function_args, tool_class)
        expires_at = time.time() + ttl
        
        # 写入 L1
        self.l1_kv_cache[key] = {"data": data, "expires_at": expires_at}

        # 写入 L2
        value = json.dumps(data)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)", (key, value, expires_at))
            conn.commit()

        # 写入语义缓存
        if semantic_query and self.embedding_model:
            embedding_result = await self.embedding_model.get_embedding(semantic_query)
            if embedding_result:
                validated_embedding = self._validate_embedding(embedding_result)
                if validated_embedding is not None:
                    try:
                        embedding = np.array([validated_embedding], dtype='float32')
                        # 写入 L1 Vector
                        new_id = self.l1_vector_index.ntotal
                        faiss.normalize_L2(embedding)
                        self.l1_vector_index.add(x=embedding)
                        self.l1_vector_id_to_key[new_id] = key
                        # 写入 L2 Vector
                        self.chroma_collection.add(embeddings=embedding.tolist(), ids=[key])
                    except Exception as e:
                        logger.error(f"写入语义缓存时发生错误: {e}")
                        # 继续执行，不影响主要缓存功能

        logger.info(f"已缓存条目: {key}, TTL: {ttl}s")

    def clear_l1(self):
        """清空L1缓存。"""
        self.l1_kv_cache.clear()
        self.l1_vector_index.reset()
        self.l1_vector_id_to_key.clear()
        logger.info("L1 (内存+FAISS) 缓存已清空。")

    def clear_l2(self):
        """清空L2缓存。"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM cache")
            conn.commit()
        self.chroma_client.delete_collection(name="semantic_cache")
        self.chroma_collection = self.chroma_client.get_or_create_collection(name="semantic_cache")
        logger.info("L2 (SQLite & ChromaDB) 缓存已清空。")

    def clear_all(self):
        """清空所有缓存。"""
        self.clear_l1()
        self.clear_l2()
        logger.info("所有缓存层级已清空。")

# 全局实例
tool_cache = CacheManager()