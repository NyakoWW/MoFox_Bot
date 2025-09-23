import time
import orjson
import hashlib
from pathlib import Path
import numpy as np
import faiss
from typing import Any, Dict, Optional, Union
from src.common.logger import get_logger
from src.llm_models.utils_model import LLMRequest
from src.config.config import global_config, model_config
from src.common.database.sqlalchemy_models import CacheEntries
from src.common.database.sqlalchemy_database_api import db_query, db_save
from src.common.vector_db import vector_db_service

logger = get_logger("cache_manager")


class CacheManager:
    """
    一个支持分层和语义缓存的通用工具缓存管理器。
    采用单例模式，确保在整个应用中只有一个缓存实例。
    L1缓存: 内存字典 (KV) + FAISS (Vector)。
    L2缓存: 数据库 (KV) + ChromaDB (Vector)。
    """

    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(CacheManager, cls).__new__(cls)
        return cls._instance

    def __init__(self, default_ttl: int = 3600):
        """
        初始化缓存管理器。
        """
        if not hasattr(self, "_initialized"):
            self.default_ttl = default_ttl
            self.semantic_cache_collection_name = "semantic_cache"

            # L1 缓存 (内存)
            self.l1_kv_cache: Dict[str, Dict[str, Any]] = {}
            embedding_dim = global_config.lpmm_knowledge.embedding_dimension
            self.l1_vector_index = faiss.IndexFlatIP(embedding_dim)
            self.l1_vector_id_to_key: Dict[int, str] = {}

            # L2 向量缓存 (使用新的服务)
            vector_db_service.get_or_create_collection(self.semantic_cache_collection_name)

            # 嵌入模型
            self.embedding_model = LLMRequest(model_config.model_task_config.embedding)

            self._initialized = True
            logger.info("缓存管理器已初始化: L1 (内存+FAISS), L2 (数据库+ChromaDB)")

    @staticmethod
    def _validate_embedding(embedding_result: Any) -> Optional[np.ndarray]:
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

                return embedding_array.astype("float32")
            else:
                logger.warning(f"嵌入结果格式不支持: {type(embedding_result)}")
                return None

        except Exception as e:
            logger.error(f"验证嵌入向量时发生错误: {e}")
            return None

    @staticmethod
    def _generate_key(tool_name: str, function_args: Dict[str, Any], tool_file_path: Union[str, Path]) -> str:
        """生成确定性的缓存键，包含文件修改时间以实现自动失效。"""
        try:
            tool_file_path = Path(tool_file_path)
            if tool_file_path.exists():
                file_name = tool_file_path.name
                file_mtime = tool_file_path.stat().st_mtime
                file_hash = hashlib.md5(f"{file_name}:{file_mtime}".encode()).hexdigest()
            else:
                file_hash = "unknown"
                logger.warning(f"工具文件不存在: {tool_file_path}")
        except (OSError, TypeError) as e:
            file_hash = "unknown"
            logger.warning(f"无法获取文件信息: {tool_file_path}，错误: {e}")

        try:
            sorted_args = orjson.dumps(function_args, option=orjson.OPT_SORT_KEYS).decode("utf-8")
        except TypeError:
            sorted_args = repr(sorted(function_args.items()))
        return f"{tool_name}::{sorted_args}::{file_hash}"

    async def get(
        self,
        tool_name: str,
        function_args: Dict[str, Any],
        tool_file_path: Union[str, Path],
        semantic_query: Optional[str] = None,
    ) -> Optional[Any]:
        """
        从缓存获取结果，查询顺序: L1-KV -> L1-Vector -> L2-KV -> L2-Vector。
        """
        # 步骤 1: L1 精确缓存查询
        key = self._generate_key(tool_name, function_args, tool_file_path)
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
                # embedding_result是一个元组(embedding_vector, model_name)，取第一个元素
                embedding_vector = embedding_result[0] if isinstance(embedding_result, tuple) else embedding_result
                validated_embedding = self._validate_embedding(embedding_vector)
                if validated_embedding is not None:
                    query_embedding = np.array([validated_embedding], dtype="float32")

        # 步骤 2a: L1 语义缓存 (FAISS)
        if query_embedding is not None and self.l1_vector_index.ntotal > 0:
            faiss.normalize_L2(query_embedding)
            distances, indices = self.l1_vector_index.search(query_embedding, 1)  # type: ignore
            if indices.size > 0 and distances[0][0] > 0.75:  # IP 越大越相似
                hit_index = indices[0][0]
                l1_hit_key = self.l1_vector_id_to_key.get(hit_index)
                if l1_hit_key and l1_hit_key in self.l1_kv_cache:
                    logger.info(f"命中L1语义缓存: {l1_hit_key}")
                    return self.l1_kv_cache[l1_hit_key]["data"]

        # 步骤 2b: L2 精确缓存 (数据库)
        cache_results_obj = await db_query(
            model_class=CacheEntries, query_type="get", filters={"cache_key": key}, single_result=True
        )

        if cache_results_obj:
            # 使用 getattr 安全访问属性，避免 Pylance 类型检查错误
            expires_at = getattr(cache_results_obj, "expires_at", 0)
            if time.time() < expires_at:
                logger.info(f"命中L2键值缓存: {key}")
                cache_value = getattr(cache_results_obj, "cache_value", "{}")
                data = orjson.loads(cache_value)

                # 更新访问统计
                await db_query(
                    model_class=CacheEntries,
                    query_type="update",
                    filters={"cache_key": key},
                    data={
                        "last_accessed": time.time(),
                        "access_count": getattr(cache_results_obj, "access_count", 0) + 1,
                    },
                )

                # 回填 L1
                self.l1_kv_cache[key] = {"data": data, "expires_at": expires_at}
                return data
            else:
                # 删除过期的缓存条目
                await db_query(model_class=CacheEntries, query_type="delete", filters={"cache_key": key})

        # 步骤 2c: L2 语义缓存 (VectorDB Service)
        if query_embedding is not None:
            try:
                results = vector_db_service.query(
                    collection_name=self.semantic_cache_collection_name,
                    query_embeddings=query_embedding.tolist(),
                    n_results=1,
                )
                if results and results.get("ids") and results["ids"][0]:
                    distance = (
                        results["distances"][0][0] if results.get("distances") and results["distances"][0] else "N/A"
                    )
                    logger.debug(f"L2语义搜索找到最相似的结果: id={results['ids'][0]}, 距离={distance}")

                    if distance != "N/A" and distance < 0.75:
                        l2_hit_key = results["ids"][0][0] if isinstance(results["ids"][0], list) else results["ids"][0]
                        logger.info(f"命中L2语义缓存: key='{l2_hit_key}', 距离={distance:.4f}")

                        # 从数据库获取缓存数据
                        semantic_cache_results_obj = await db_query(
                            model_class=CacheEntries,
                            query_type="get",
                            filters={"cache_key": l2_hit_key},
                            single_result=True,
                        )

                        if semantic_cache_results_obj:
                            expires_at = getattr(semantic_cache_results_obj, "expires_at", 0)
                            if time.time() < expires_at:
                                cache_value = getattr(semantic_cache_results_obj, "cache_value", "{}")
                                data = orjson.loads(cache_value)
                                logger.debug(f"L2语义缓存返回的数据: {data}")

                                # 回填 L1
                                self.l1_kv_cache[key] = {"data": data, "expires_at": expires_at}
                                if query_embedding is not None:
                                    try:
                                        new_id = self.l1_vector_index.ntotal
                                        faiss.normalize_L2(query_embedding)
                                        self.l1_vector_index.add(x=query_embedding)  # type: ignore
                                        self.l1_vector_id_to_key[new_id] = key
                                    except Exception as e:
                                        logger.error(f"回填L1向量索引时发生错误: {e}")
                                return data
            except Exception as e:
                logger.warning(f"VectorDB Service 查询失败: {e}")

        logger.debug(f"缓存未命中: {key}")
        return None

    async def set(
        self,
        tool_name: str,
        function_args: Dict[str, Any],
        tool_file_path: Union[str, Path],
        data: Any,
        ttl: Optional[int] = None,
        semantic_query: Optional[str] = None,
    ):
        """将结果存入所有缓存层。"""
        if ttl is None:
            ttl = self.default_ttl
        if ttl <= 0:
            return

        key = self._generate_key(tool_name, function_args, tool_file_path)
        expires_at = time.time() + ttl

        # 写入 L1
        self.l1_kv_cache[key] = {"data": data, "expires_at": expires_at}

        # 写入 L2 (数据库)
        cache_data = {
            "cache_key": key,
            "cache_value": orjson.dumps(data).decode("utf-8"),
            "expires_at": expires_at,
            "tool_name": tool_name,
            "created_at": time.time(),
            "last_accessed": time.time(),
            "access_count": 1,
        }

        await db_save(model_class=CacheEntries, data=cache_data, key_field="cache_key", key_value=key)

        # 写入语义缓存
        if semantic_query and self.embedding_model:
            try:
                embedding_result = await self.embedding_model.get_embedding(semantic_query)
                if embedding_result:
                    embedding_vector = embedding_result[0] if isinstance(embedding_result, tuple) else embedding_result
                    validated_embedding = self._validate_embedding(embedding_vector)
                    if validated_embedding is not None:
                        embedding = np.array([validated_embedding], dtype="float32")

                        # 写入 L1 Vector
                        new_id = self.l1_vector_index.ntotal
                        faiss.normalize_L2(embedding)
                        self.l1_vector_index.add(x=embedding)  # type: ignore
                        self.l1_vector_id_to_key[new_id] = key

                        # 写入 L2 Vector (使用新的服务)
                        vector_db_service.add(
                            collection_name=self.semantic_cache_collection_name,
                            embeddings=embedding.tolist(),
                            ids=[key],
                        )
            except Exception as e:
                logger.warning(f"语义缓存写入失败: {e}")

        logger.info(f"已缓存条目: {key}, TTL: {ttl}s")

    def clear_l1(self):
        """清空L1缓存。"""
        self.l1_kv_cache.clear()
        self.l1_vector_index.reset()
        self.l1_vector_id_to_key.clear()
        logger.info("L1 (内存+FAISS) 缓存已清空。")

    async def clear_l2(self):
        """清空L2缓存。"""
        # 清空数据库缓存
        await db_query(
            model_class=CacheEntries,
            query_type="delete",
            filters={},  # 删除所有记录
        )

        # 清空 VectorDB
        try:
            vector_db_service.delete_collection(name=self.semantic_cache_collection_name)
            vector_db_service.get_or_create_collection(name=self.semantic_cache_collection_name)
        except Exception as e:
            logger.warning(f"清空 VectorDB 集合失败: {e}")

        logger.info("L2 (数据库 & VectorDB) 缓存已清空。")

    async def clear_all(self):
        """清空所有缓存。"""
        self.clear_l1()
        await self.clear_l2()
        logger.info("所有缓存层级已清空。")

    async def clean_expired(self):
        """清理过期的缓存条目"""
        current_time = time.time()

        # 清理L1过期条目
        expired_keys = []
        for key, entry in self.l1_kv_cache.items():
            if current_time >= entry["expires_at"]:
                expired_keys.append(key)

        for key in expired_keys:
            del self.l1_kv_cache[key]

        # 清理L2过期条目
        await db_query(model_class=CacheEntries, query_type="delete", filters={"expires_at": {"$lt": current_time}})

        if expired_keys:
            logger.info(f"清理了 {len(expired_keys)} 个过期的L1缓存条目")


# 全局实例
tool_cache = CacheManager()
