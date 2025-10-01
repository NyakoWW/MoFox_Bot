# -*- coding: utf-8 -*-
"""
多阶段召回机制
实现粗粒度到细粒度的记忆检索优化
"""

import time
import asyncio
from typing import Dict, List, Optional, Tuple, Set, Any
from dataclasses import dataclass
from enum import Enum
import numpy as np

from src.common.logger import get_logger
from src.chat.memory_system.memory_chunk import MemoryChunk, MemoryType, ConfidenceLevel, ImportanceLevel

logger = get_logger(__name__)


class RetrievalStage(Enum):
    """检索阶段"""
    METADATA_FILTERING = "metadata_filtering"      # 元数据过滤阶段
    VECTOR_SEARCH = "vector_search"                 # 向量搜索阶段
    SEMANTIC_RERANKING = "semantic_reranking"       # 语义重排序阶段
    CONTEXTUAL_FILTERING = "contextual_filtering"    # 上下文过滤阶段


@dataclass
class RetrievalConfig:
    """检索配置"""
    # 各阶段配置
    metadata_filter_limit: int = 100        # 元数据过滤阶段返回数量
    vector_search_limit: int = 50           # 向量搜索阶段返回数量
    semantic_rerank_limit: int = 20         # 语义重排序阶段返回数量
    final_result_limit: int = 10            # 最终结果数量

    # 相似度阈值
    vector_similarity_threshold: float = 0.7    # 向量相似度阈值
    semantic_similarity_threshold: float = 0.6  # 语义相似度阈值

    # 权重配置
    vector_weight: float = 0.4                 # 向量相似度权重
    semantic_weight: float = 0.3               # 语义相似度权重
    context_weight: float = 0.2                 # 上下文权重
    recency_weight: float = 0.1                 # 时效性权重

    @classmethod
    def from_global_config(cls):
        """从全局配置创建配置实例"""
        from src.config.config import global_config

        return cls(
            # 各阶段配置
            metadata_filter_limit=global_config.memory.metadata_filter_limit,
            vector_search_limit=global_config.memory.vector_search_limit,
            semantic_rerank_limit=global_config.memory.semantic_rerank_limit,
            final_result_limit=global_config.memory.final_result_limit,

            # 相似度阈值
            vector_similarity_threshold=global_config.memory.vector_similarity_threshold,
            semantic_similarity_threshold=0.6,  # 保持默认值

            # 权重配置
            vector_weight=global_config.memory.vector_weight,
            semantic_weight=global_config.memory.semantic_weight,
            context_weight=global_config.memory.context_weight,
            recency_weight=global_config.memory.recency_weight
        )


@dataclass
class StageResult:
    """阶段结果"""
    stage: RetrievalStage
    memory_ids: List[str]
    processing_time: float
    filtered_count: int
    score_threshold: float


@dataclass
class RetrievalResult:
    """检索结果"""
    query: str
    user_id: str
    final_memories: List[MemoryChunk]
    stage_results: List[StageResult]
    total_processing_time: float
    total_filtered: int
    retrieval_stats: Dict[str, Any]


class MultiStageRetrieval:
    """多阶段召回系统"""

    def __init__(self, config: Optional[RetrievalConfig] = None):
        self.config = config or RetrievalConfig.from_global_config()
        self.retrieval_stats = {
            "total_queries": 0,
            "average_retrieval_time": 0.0,
            "stage_stats": {
                "metadata_filtering": {"calls": 0, "avg_time": 0.0},
                "vector_search": {"calls": 0, "avg_time": 0.0},
                "semantic_reranking": {"calls": 0, "avg_time": 0.0},
                "contextual_filtering": {"calls": 0, "avg_time": 0.0}
            }
        }

    async def retrieve_memories(
        self,
        query: str,
        user_id: str,
        context: Dict[str, Any],
        metadata_index,
        vector_storage,
        all_memories_cache: Dict[str, MemoryChunk],
        limit: Optional[int] = None
    ) -> RetrievalResult:
        """多阶段记忆检索"""
        start_time = time.time()
        limit = limit or self.config.final_result_limit

        stage_results = []
        current_memory_ids = set()

        try:
            logger.debug(f"开始多阶段检索：query='{query}', user_id='{user_id}'")

            # 阶段1：元数据过滤
            stage1_result = await self._metadata_filtering_stage(
                query, user_id, context, metadata_index, all_memories_cache
            )
            stage_results.append(stage1_result)
            current_memory_ids.update(stage1_result.memory_ids)

            # 阶段2：向量搜索
            stage2_result = await self._vector_search_stage(
                query, user_id, context, vector_storage, current_memory_ids, all_memories_cache
            )
            stage_results.append(stage2_result)
            current_memory_ids.update(stage2_result.memory_ids)

            # 阶段3：语义重排序
            stage3_result = await self._semantic_reranking_stage(
                query, user_id, context, current_memory_ids, all_memories_cache
            )
            stage_results.append(stage3_result)

            # 阶段4：上下文过滤
            stage4_result = await self._contextual_filtering_stage(
                query, user_id, context, stage3_result.memory_ids, all_memories_cache, limit
            )
            stage_results.append(stage4_result)

            # 获取最终记忆对象
            final_memories = []
            for memory_id in stage4_result.memory_ids:
                if memory_id in all_memories_cache:
                    final_memories.append(all_memories_cache[memory_id])

            # 更新统计
            total_time = time.time() - start_time
            self._update_retrieval_stats(total_time, stage_results)

            total_filtered = sum(result.filtered_count for result in stage_results)

            logger.debug(f"多阶段检索完成：返回 {len(final_memories)} 条记忆，耗时 {total_time:.3f}s")

            return RetrievalResult(
                query=query,
                user_id=user_id,
                final_memories=final_memories,
                stage_results=stage_results,
                total_processing_time=total_time,
                total_filtered=total_filtered,
                retrieval_stats=self.retrieval_stats.copy()
            )

        except Exception as e:
            logger.error(f"多阶段检索失败: {e}", exc_info=True)
            # 返回空结果
            return RetrievalResult(
                query=query,
                user_id=user_id,
                final_memories=[],
                stage_results=stage_results,
                total_processing_time=time.time() - start_time,
                total_filtered=0,
                retrieval_stats=self.retrieval_stats.copy()
            )

    async def _metadata_filtering_stage(
        self,
        query: str,
        user_id: str,
        context: Dict[str, Any],
        metadata_index,
        all_memories_cache: Dict[str, MemoryChunk]
    ) -> StageResult:
        """阶段1：元数据过滤"""
        start_time = time.time()

        try:
            from .metadata_index import IndexQuery

            query_plan = context.get("query_plan")

            memory_types = self._extract_memory_types_from_context(context)
            keywords = self._extract_keywords_from_query(query, query_plan)
            subjects = query_plan.subject_includes if query_plan and getattr(query_plan, "subject_includes", None) else None

            index_query = IndexQuery(
                user_ids=None,
                memory_types=memory_types,
                subjects=subjects,
                keywords=keywords,
                limit=self.config.metadata_filter_limit,
                sort_by="last_accessed",
                sort_order="desc"
            )

            # 执行查询
            result = await metadata_index.query_memories(index_query)
            result_ids = list(result.memory_ids)
            filtered_count = max(0, len(all_memories_cache) - len(result_ids))

            # 如果未命中任何索引且未指定所有者过滤，则回退到最近访问的记忆
            if not result_ids:
                sorted_ids = sorted(
                    (memory.memory_id for memory in all_memories_cache.values()),
                    key=lambda mid: all_memories_cache[mid].metadata.last_accessed if mid in all_memories_cache else 0,
                    reverse=True,
                )
                if memory_types:
                    type_filtered = [
                        mid for mid in sorted_ids
                        if all_memories_cache[mid].memory_type in memory_types
                    ]
                    sorted_ids = type_filtered or sorted_ids
                if subjects:
                    subject_candidates = [s.lower() for s in subjects if isinstance(s, str) and s.strip()]
                    if subject_candidates:
                        subject_filtered = [
                            mid for mid in sorted_ids
                            if any(
                                subj.strip().lower() in subject_candidates
                                for subj in all_memories_cache[mid].subjects
                            )
                        ]
                        sorted_ids = subject_filtered or sorted_ids

                if keywords:
                    keyword_pool = {kw.lower() for kw in keywords if isinstance(kw, str) and kw.strip()}
                    if keyword_pool:
                        keyword_filtered = []
                        for mid in sorted_ids:
                            memory_text = (
                                (all_memories_cache[mid].display or "")
                                + "\n"
                                + (all_memories_cache[mid].text_content or "")
                            ).lower()
                            if any(kw in memory_text for kw in keyword_pool):
                                keyword_filtered.append(mid)
                        sorted_ids = keyword_filtered or sorted_ids

                result_ids = sorted_ids[: self.config.metadata_filter_limit]
                filtered_count = max(0, len(all_memories_cache) - len(result_ids))
                logger.debug(
                    "元数据过滤未命中索引，使用近似回退: types=%s, subjects=%s, keywords=%s",
                    bool(memory_types),
                    bool(subjects),
                    bool(keywords),
                )

            logger.debug(
                "元数据过滤：候选=%d, 返回=%d",
                len(all_memories_cache),
                len(result_ids),
            )

            return StageResult(
                stage=RetrievalStage.METADATA_FILTERING,
                memory_ids=result_ids,
                processing_time=time.time() - start_time,
                filtered_count=filtered_count,
                score_threshold=0.0
            )

        except Exception as e:
            logger.error(f"元数据过滤阶段失败: {e}")
            return StageResult(
                stage=RetrievalStage.METADATA_FILTERING,
                memory_ids=[],
                processing_time=time.time() - start_time,
                filtered_count=0,
                score_threshold=0.0
            )

    async def _vector_search_stage(
        self,
        query: str,
        user_id: str,
        context: Dict[str, Any],
        vector_storage,
        candidate_ids: Set[str],
        all_memories_cache: Dict[str, MemoryChunk]
    ) -> StageResult:
        """阶段2：向量搜索"""
        start_time = time.time()

        try:
            # 生成查询向量
            query_embedding = await self._generate_query_embedding(query, context, vector_storage)

            if not query_embedding:
                return StageResult(
                    stage=RetrievalStage.VECTOR_SEARCH,
                    memory_ids=[],
                    processing_time=time.time() - start_time,
                    filtered_count=0,
                    score_threshold=self.config.vector_similarity_threshold
                )

            # 执行向量搜索
            search_result = await vector_storage.search_similar_memories(
                query_vector=query_embedding,
                limit=self.config.vector_search_limit
            )

            candidate_pool = candidate_ids or set(all_memories_cache.keys())

            # 过滤候选记忆
            filtered_memories = []
            for memory_id, similarity in search_result:
                if memory_id in candidate_pool and similarity >= self.config.vector_similarity_threshold:
                    filtered_memories.append((memory_id, similarity))

            # 按相似度排序
            filtered_memories.sort(key=lambda x: x[1], reverse=True)
            result_ids = [memory_id for memory_id, _ in filtered_memories[:self.config.vector_search_limit]]

            filtered_count = max(0, len(candidate_pool) - len(result_ids))

            logger.debug(f"向量搜索：{len(candidate_ids)} -> {len(result_ids)} 条记忆")

            return StageResult(
                stage=RetrievalStage.VECTOR_SEARCH,
                memory_ids=result_ids,
                processing_time=time.time() - start_time,
                filtered_count=filtered_count,
                score_threshold=self.config.vector_similarity_threshold
            )

        except Exception as e:
            logger.error(f"向量搜索阶段失败: {e}")
            return StageResult(
                stage=RetrievalStage.VECTOR_SEARCH,
                memory_ids=[],
                processing_time=time.time() - start_time,
                filtered_count=0,
                score_threshold=self.config.vector_similarity_threshold
            )

    async def _semantic_reranking_stage(
        self,
        query: str,
        user_id: str,
        context: Dict[str, Any],
        candidate_ids: Set[str],
        all_memories_cache: Dict[str, MemoryChunk]
    ) -> StageResult:
        """阶段3：语义重排序"""
        start_time = time.time()

        try:
            reranked_memories = []

            for memory_id in candidate_ids:
                if memory_id not in all_memories_cache:
                    continue

                memory = all_memories_cache[memory_id]

                # 计算综合语义相似度
                semantic_score = await self._calculate_semantic_similarity(query, memory, context)

                if semantic_score >= self.config.semantic_similarity_threshold:
                    reranked_memories.append((memory_id, semantic_score))

            # 按语义相似度排序
            reranked_memories.sort(key=lambda x: x[1], reverse=True)
            result_ids = [memory_id for memory_id, _ in reranked_memories[:self.config.semantic_rerank_limit]]

            filtered_count = len(candidate_ids) - len(result_ids)

            logger.debug(f"语义重排序：{len(candidate_ids)} -> {len(result_ids)} 条记忆")

            return StageResult(
                stage=RetrievalStage.SEMANTIC_RERANKING,
                memory_ids=result_ids,
                processing_time=time.time() - start_time,
                filtered_count=filtered_count,
                score_threshold=self.config.semantic_similarity_threshold
            )

        except Exception as e:
            logger.error(f"语义重排序阶段失败: {e}")
            return StageResult(
                stage=RetrievalStage.SEMANTIC_RERANKING,
                memory_ids=list(candidate_ids),  # 失败时返回原候选集
                processing_time=time.time() - start_time,
                filtered_count=0,
                score_threshold=self.config.semantic_similarity_threshold
            )

    async def _contextual_filtering_stage(
        self,
        query: str,
        user_id: str,
        context: Dict[str, Any],
        candidate_ids: List[str],
        all_memories_cache: Dict[str, MemoryChunk],
        limit: int
    ) -> StageResult:
        """阶段4：上下文过滤"""
        start_time = time.time()

        try:
            final_memories = []

            for memory_id in candidate_ids:
                if memory_id not in all_memories_cache:
                    continue

                memory = all_memories_cache[memory_id]

                # 计算上下文相关度评分
                context_score = await self._calculate_context_relevance(query, memory, context)

                # 结合多因子评分
                final_score = await self._calculate_final_score(query, memory, context, context_score)

                final_memories.append((memory_id, final_score))

            # 按最终评分排序
            final_memories.sort(key=lambda x: x[1], reverse=True)
            result_ids = [memory_id for memory_id, _ in final_memories[:limit]]

            filtered_count = len(candidate_ids) - len(result_ids)

            logger.debug(f"上下文过滤：{len(candidate_ids)} -> {len(result_ids)} 条记忆")

            return StageResult(
                stage=RetrievalStage.CONTEXTUAL_FILTERING,
                memory_ids=result_ids,
                processing_time=time.time() - start_time,
                filtered_count=filtered_count,
                score_threshold=0.0  # 动态阈值
            )

        except Exception as e:
            logger.error(f"上下文过滤阶段失败: {e}")
            return StageResult(
                stage=RetrievalStage.CONTEXTUAL_FILTERING,
                memory_ids=candidate_ids[:limit],  # 失败时返回前limit个
                processing_time=time.time() - start_time,
                filtered_count=0,
                score_threshold=0.0
            )

    async def _generate_query_embedding(self, query: str, context: Dict[str, Any], vector_storage) -> Optional[List[float]]:
        """生成查询向量"""
        try:
            query_plan = context.get("query_plan")
            query_text = query
            if query_plan and getattr(query_plan, "semantic_query", None):
                query_text = query_plan.semantic_query

            if not query_text:
                return None

            if hasattr(vector_storage, "generate_query_embedding"):
                return await vector_storage.generate_query_embedding(query_text)

            return None
        except Exception as e:
            logger.warning(f"生成查询向量失败: {e}")
            return None

    async def _calculate_semantic_similarity(self, query: str, memory: MemoryChunk, context: Dict[str, Any]) -> float:
        """计算语义相似度"""
        try:
            query_plan = context.get("query_plan")
            query_text = query
            if query_plan and getattr(query_plan, "semantic_query", None):
                query_text = query_plan.semantic_query

            # 简单的文本相似度计算
            query_words = set(query_text.lower().split())
            memory_text = (memory.display or memory.text_content or "").lower()
            memory_words = set(memory_text.split())

            if not query_words or not memory_words:
                return 0.0

            intersection = query_words & memory_words
            union = query_words | memory_words

            jaccard_similarity = len(intersection) / len(union)
            return jaccard_similarity

        except Exception as e:
            logger.warning(f"计算语义相似度失败: {e}")
            return 0.0

    async def _calculate_context_relevance(self, query: str, memory: MemoryChunk, context: Dict[str, Any]) -> float:
        """计算上下文相关度"""
        try:
            score = 0.0

            query_plan = context.get("query_plan")

            # 检查记忆类型是否匹配上下文
            if context.get("expected_memory_types"):
                if memory.memory_type in context["expected_memory_types"]:
                    score += 0.3
            elif query_plan and getattr(query_plan, "memory_types", None):
                if memory.memory_type in query_plan.memory_types:
                    score += 0.3

            # 检查关键词匹配
            if context.get("keywords"):
                memory_keywords = set(memory.keywords)
                context_keywords = set(context["keywords"])
                overlap = memory_keywords & context_keywords
                if overlap:
                    score += len(overlap) / max(len(context_keywords), 1) * 0.4

            if query_plan:
                # 主体匹配
                subject_score = self._calculate_subject_overlap(memory, getattr(query_plan, "subject_includes", []))
                score += subject_score * 0.3

                # 对象/描述匹配
                object_keywords = getattr(query_plan, "object_includes", []) or []
                if object_keywords:
                    display_text = (memory.display or memory.text_content or "").lower()
                    hits = sum(1 for kw in object_keywords if isinstance(kw, str) and kw.strip() and kw.strip().lower() in display_text)
                    if hits:
                        score += min(0.3, hits * 0.1)

                optional_keywords = getattr(query_plan, "optional_keywords", []) or []
                if optional_keywords:
                    display_text = (memory.display or memory.text_content or "").lower()
                    hits = sum(1 for kw in optional_keywords if isinstance(kw, str) and kw.strip() and kw.strip().lower() in display_text)
                    if hits:
                        score += min(0.2, hits * 0.05)

                # 时间偏好
                recency_pref = getattr(query_plan, "recency_preference", "")
                if recency_pref:
                    memory_age = time.time() - memory.metadata.created_at
                    if recency_pref == "recent" and memory_age < 7 * 24 * 3600:
                        score += 0.2
                    elif recency_pref == "historical" and memory_age > 30 * 24 * 3600:
                        score += 0.1

            # 检查时效性
            if context.get("recent_only", False):
                memory_age = time.time() - memory.metadata.created_at
                if memory_age < 7 * 24 * 3600:  # 7天内
                    score += 0.3

            return min(score, 1.0)

        except Exception as e:
            logger.warning(f"计算上下文相关度失败: {e}")
            return 0.0

    async def _calculate_final_score(self, query: str, memory: MemoryChunk, context: Dict[str, Any], context_score: float) -> float:
        """计算最终评分"""
        try:
            query_plan = context.get("query_plan")

            # 语义相似度
            semantic_score = await self._calculate_semantic_similarity(query, memory, context)

            # 向量相似度（如果有）
            vector_score = 0.0
            if memory.embedding:
                # 这里应该有向量相似度计算，简化处理
                vector_score = 0.5

            # 时效性评分
            recency_score = self._calculate_recency_score(memory.metadata.created_at)
            if query_plan:
                recency_pref = getattr(query_plan, "recency_preference", "")
                if recency_pref == "recent":
                    recency_score = max(recency_score, 0.8)
                elif recency_pref == "historical":
                    recency_score = min(recency_score, 0.5)

            # 权重组合
            vector_weight = self.config.vector_weight
            semantic_weight = self.config.semantic_weight
            context_weight = self.config.context_weight
            recency_weight = self.config.recency_weight

            if query_plan and getattr(query_plan, "emphasis", None) == "precision":
                semantic_weight += 0.05
            elif query_plan and getattr(query_plan, "emphasis", None) == "recall":
                context_weight += 0.05

            final_score = (
                semantic_score * semantic_weight +
                vector_score * vector_weight +
                context_score * context_weight +
                recency_score * recency_weight
            )

            # 加入记忆重要性权重
            importance_weight = memory.metadata.importance.value / 4.0  # 标准化到0-1
            final_score = final_score * (0.7 + importance_weight * 0.3)  # 重要性影响30%

            return final_score

        except Exception as e:
            logger.warning(f"计算最终评分失败: {e}")
            return 0.0

    def _calculate_subject_overlap(self, memory: MemoryChunk, required_subjects: Optional[List[str]]) -> float:
        if not required_subjects:
            return 0.0

        memory_subjects = {subject.lower() for subject in memory.subjects if isinstance(subject, str)}
        if not memory_subjects:
            return 0.0

        hit = 0
        total = 0
        for subject in required_subjects:
            if not isinstance(subject, str):
                continue
            total += 1
            normalized = subject.strip().lower()
            if not normalized:
                continue
            if any(normalized in mem_subject for mem_subject in memory_subjects):
                hit += 1

        if total == 0:
            return 0.0

        return hit / total

    def _calculate_recency_score(self, timestamp: float) -> float:
        """计算时效性评分"""
        try:
            age = time.time() - timestamp
            age_days = age / (24 * 3600)

            if age_days < 1:
                return 1.0
            elif age_days < 7:
                return 0.8
            elif age_days < 30:
                return 0.6
            elif age_days < 90:
                return 0.4
            else:
                return 0.2

        except Exception:
            return 0.5

    def _extract_memory_types_from_context(self, context: Dict[str, Any]) -> List[MemoryType]:
        """从上下文中提取记忆类型"""
        try:
            query_plan = context.get("query_plan")
            if query_plan and getattr(query_plan, "memory_types", None):
                return query_plan.memory_types

            if "expected_memory_types" in context:
                return context["expected_memory_types"]

            # 根据上下文推断记忆类型
            if "message_type" in context:
                message_type = context["message_type"]
                if message_type in ["personal_info", "fact"]:
                    return [MemoryType.PERSONAL_FACT]
                elif message_type in ["event", "activity"]:
                    return [MemoryType.EVENT]
                elif message_type in ["preference", "like"]:
                    return [MemoryType.PREFERENCE]
                elif message_type in ["opinion", "view"]:
                    return [MemoryType.OPINION]

            return []

        except Exception:
            return []

    def _extract_keywords_from_query(self, query: str, query_plan: Optional[Any] = None) -> List[str]:
        """从查询中提取关键词"""
        try:
            extracted: List[str] = []

            if query_plan and getattr(query_plan, "required_keywords", None):
                extracted.extend([kw.lower() for kw in query_plan.required_keywords if isinstance(kw, str)])

            # 简单的关键词提取
            words = query.lower().split()
            # 过滤停用词
            stopwords = {"的", "是", "在", "有", "我", "你", "他", "她", "它", "这", "那", "了", "吗", "呢"}
            extracted.extend(word for word in words if len(word) > 1 and word not in stopwords)

            # 去重并保留顺序
            seen = set()
            deduplicated = []
            for word in extracted:
                if word in seen or not word:
                    continue
                seen.add(word)
                deduplicated.append(word)

            return deduplicated[:10]
        except Exception:
            return []

    def _update_retrieval_stats(self, total_time: float, stage_results: List[StageResult]):
        """更新检索统计"""
        self.retrieval_stats["total_queries"] += 1

        # 更新平均检索时间
        current_avg = self.retrieval_stats["average_retrieval_time"]
        total_queries = self.retrieval_stats["total_queries"]
        new_avg = (current_avg * (total_queries - 1) + total_time) / total_queries
        self.retrieval_stats["average_retrieval_time"] = new_avg

        # 更新各阶段统计
        for result in stage_results:
            stage_name = result.stage.value
            if stage_name in self.retrieval_stats["stage_stats"]:
                stage_stat = self.retrieval_stats["stage_stats"][stage_name]
                stage_stat["calls"] += 1

                current_stage_avg = stage_stat["avg_time"]
                new_stage_avg = (current_stage_avg * (stage_stat["calls"] - 1) + result.processing_time) / stage_stat["calls"]
                stage_stat["avg_time"] = new_stage_avg

    def get_retrieval_stats(self) -> Dict[str, Any]:
        """获取检索统计信息"""
        return self.retrieval_stats.copy()

    def reset_stats(self):
        """重置统计信息"""
        self.retrieval_stats = {
            "total_queries": 0,
            "average_retrieval_time": 0.0,
            "stage_stats": {
                "metadata_filtering": {"calls": 0, "avg_time": 0.0},
                "vector_search": {"calls": 0, "avg_time": 0.0},
                "semantic_reranking": {"calls": 0, "avg_time": 0.0},
                "contextual_filtering": {"calls": 0, "avg_time": 0.0}
            }
        }