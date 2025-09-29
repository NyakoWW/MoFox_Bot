# -*- coding: utf-8 -*-
"""
增强记忆系统适配器
将增强记忆系统集成到现有MoFox Bot架构中
"""

import asyncio
import time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

from src.common.logger import get_logger
from src.chat.memory_system.integration_layer import MemoryIntegrationLayer, IntegrationConfig, IntegrationMode
from src.chat.memory_system.memory_chunk import MemoryChunk
from src.llm_models.utils_model import LLMRequest

logger = get_logger(__name__)


@dataclass
class AdapterConfig:
    """适配器配置"""
    enable_enhanced_memory: bool = True
    integration_mode: str = "enhanced_only"  # replace, enhanced_only
    auto_migration: bool = True
    memory_value_threshold: float = 0.6
    fusion_threshold: float = 0.85
    max_retrieval_results: int = 10


class EnhancedMemoryAdapter:
    """增强记忆系统适配器"""

    def __init__(self, llm_model: LLMRequest, config: Optional[AdapterConfig] = None):
        self.llm_model = llm_model
        self.config = config or AdapterConfig()
        self.integration_layer: Optional[MemoryIntegrationLayer] = None
        self._initialized = False

        # 统计信息
        self.adapter_stats = {
            "total_processed": 0,
            "enhanced_used": 0,
            "legacy_used": 0,
            "hybrid_used": 0,
            "memories_created": 0,
            "memories_retrieved": 0,
            "average_processing_time": 0.0
        }

    async def initialize(self):
        """初始化适配器"""
        if self._initialized:
            return

        try:
            logger.info("🚀 初始化增强记忆系统适配器...")

            # 转换配置格式
            integration_config = IntegrationConfig(
                mode=IntegrationMode(self.config.integration_mode),
                enable_enhanced_memory=self.config.enable_enhanced_memory,
                memory_value_threshold=self.config.memory_value_threshold,
                fusion_threshold=self.config.fusion_threshold,
                max_retrieval_results=self.config.max_retrieval_results,
                enable_learning=True  # 启用学习功能
            )

            # 创建集成层
            self.integration_layer = MemoryIntegrationLayer(
                llm_model=self.llm_model,
                config=integration_config
            )

            # 初始化集成层
            await self.integration_layer.initialize()

            self._initialized = True
            logger.info("✅ 增强记忆系统适配器初始化完成")

        except Exception as e:
            logger.error(f"❌ 增强记忆系统适配器初始化失败: {e}", exc_info=True)
            # 如果初始化失败，禁用增强记忆功能
            self.config.enable_enhanced_memory = False

    async def process_conversation_memory(
        self,
        conversation_text: str,
        context: Dict[str, Any],
        user_id: str,
        timestamp: Optional[float] = None
    ) -> Dict[str, Any]:
        """处理对话记忆"""
        if not self._initialized or not self.config.enable_enhanced_memory:
            return {"success": False, "error": "Enhanced memory not available"}

        start_time = time.time()
        self.adapter_stats["total_processed"] += 1

        try:
            # 使用集成层处理对话
            result = await self.integration_layer.process_conversation(
                conversation_text, context, user_id, timestamp
            )

            # 更新统计
            processing_time = time.time() - start_time
            self._update_processing_stats(processing_time)

            if result["success"]:
                created_count = len(result.get("created_memories", []))
                self.adapter_stats["memories_created"] += created_count
                logger.debug(f"对话记忆处理完成，创建 {created_count} 条记忆")

            return result

        except Exception as e:
            logger.error(f"处理对话记忆失败: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def retrieve_relevant_memories(
        self,
        query: str,
        user_id: str,
        context: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[MemoryChunk]:
        """检索相关记忆"""
        if not self._initialized or not self.config.enable_enhanced_memory:
            return []

        try:
            limit = limit or self.config.max_retrieval_results
            memories = await self.integration_layer.retrieve_relevant_memories(
                query, user_id, context, limit
            )

            self.adapter_stats["memories_retrieved"] += len(memories)
            logger.debug(f"检索到 {len(memories)} 条相关记忆")

            return memories

        except Exception as e:
            logger.error(f"检索相关记忆失败: {e}", exc_info=True)
            return []

    async def get_memory_context_for_prompt(
        self,
        query: str,
        user_id: str,
        context: Optional[Dict[str, Any]] = None,
        max_memories: int = 5
    ) -> str:
        """获取用于提示词的记忆上下文"""
        memories = await self.retrieve_relevant_memories(query, user_id, context, max_memories)

        if not memories:
            return ""

        # 格式化记忆为提示词友好的格式
        memory_context_parts = []
        for memory in memories:
            memory_context_parts.append(f"- {memory.text_content}")

        return "\n".join(memory_context_parts)

    async def get_enhanced_memory_summary(self, user_id: str) -> Dict[str, Any]:
        """获取增强记忆系统摘要"""
        if not self._initialized or not self.config.enable_enhanced_memory:
            return {"available": False, "reason": "Not initialized or disabled"}

        try:
            # 获取系统状态
            status = await self.integration_layer.get_system_status()

            # 获取适配器统计
            adapter_stats = self.adapter_stats.copy()

            # 获取集成统计
            integration_stats = self.integration_layer.get_integration_stats()

            return {
                "available": True,
                "system_status": status,
                "adapter_stats": adapter_stats,
                "integration_stats": integration_stats,
                "total_memories_created": adapter_stats["memories_created"],
                "total_memories_retrieved": adapter_stats["memories_retrieved"]
            }

        except Exception as e:
            logger.error(f"获取增强记忆摘要失败: {e}", exc_info=True)
            return {"available": False, "error": str(e)}

    def _update_processing_stats(self, processing_time: float):
        """更新处理统计"""
        total_processed = self.adapter_stats["total_processed"]
        if total_processed > 0:
            current_avg = self.adapter_stats["average_processing_time"]
            new_avg = (current_avg * (total_processed - 1) + processing_time) / total_processed
            self.adapter_stats["average_processing_time"] = new_avg

    def get_adapter_stats(self) -> Dict[str, Any]:
        """获取适配器统计信息"""
        return self.adapter_stats.copy()

    async def maintenance(self):
        """维护操作"""
        if not self._initialized:
            return

        try:
            logger.info("🔧 增强记忆系统适配器维护...")
            await self.integration_layer.maintenance()
            logger.info("✅ 增强记忆系统适配器维护完成")
        except Exception as e:
            logger.error(f"❌ 增强记忆系统适配器维护失败: {e}", exc_info=True)

    async def shutdown(self):
        """关闭适配器"""
        if not self._initialized:
            return

        try:
            logger.info("🔄 关闭增强记忆系统适配器...")
            await self.integration_layer.shutdown()
            self._initialized = False
            logger.info("✅ 增强记忆系统适配器已关闭")
        except Exception as e:
            logger.error(f"❌ 关闭增强记忆系统适配器失败: {e}", exc_info=True)


# 全局适配器实例
_enhanced_memory_adapter: Optional[EnhancedMemoryAdapter] = None


async def get_enhanced_memory_adapter(llm_model: LLMRequest) -> EnhancedMemoryAdapter:
    """获取全局增强记忆适配器实例"""
    global _enhanced_memory_adapter

    if _enhanced_memory_adapter is None:
        # 从配置中获取适配器配置
        from src.config.config import global_config

        adapter_config = AdapterConfig(
            enable_enhanced_memory=getattr(global_config.memory, 'enable_enhanced_memory', True),
            integration_mode=getattr(global_config.memory, 'enhanced_memory_mode', 'enhanced_only'),
            auto_migration=getattr(global_config.memory, 'enable_memory_migration', True),
            memory_value_threshold=getattr(global_config.memory, 'memory_value_threshold', 0.6),
            fusion_threshold=getattr(global_config.memory, 'fusion_threshold', 0.85),
            max_retrieval_results=getattr(global_config.memory, 'max_retrieval_results', 10)
        )

        _enhanced_memory_adapter = EnhancedMemoryAdapter(llm_model, adapter_config)
        await _enhanced_memory_adapter.initialize()

    return _enhanced_memory_adapter


async def initialize_enhanced_memory_system(llm_model: LLMRequest):
    """初始化增强记忆系统"""
    try:
        logger.info("🚀 初始化增强记忆系统...")
        adapter = await get_enhanced_memory_adapter(llm_model)
        logger.info("✅ 增强记忆系统初始化完成")
        return adapter
    except Exception as e:
        logger.error(f"❌ 增强记忆系统初始化失败: {e}", exc_info=True)
        return None


async def process_conversation_with_enhanced_memory(
    conversation_text: str,
    context: Dict[str, Any],
    user_id: str,
    timestamp: Optional[float] = None,
    llm_model: Optional[LLMRequest] = None
) -> Dict[str, Any]:
    """使用增强记忆系统处理对话"""
    if not llm_model:
        # 获取默认的LLM模型
        from src.llm_models.utils_model import get_global_llm_model
        llm_model = get_global_llm_model()

    try:
        adapter = await get_enhanced_memory_adapter(llm_model)
        return await adapter.process_conversation_memory(conversation_text, context, user_id, timestamp)
    except Exception as e:
        logger.error(f"使用增强记忆系统处理对话失败: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


async def retrieve_memories_with_enhanced_system(
    query: str,
    user_id: str,
    context: Optional[Dict[str, Any]] = None,
    limit: int = 10,
    llm_model: Optional[LLMRequest] = None
) -> List[MemoryChunk]:
    """使用增强记忆系统检索记忆"""
    if not llm_model:
        # 获取默认的LLM模型
        from src.llm_models.utils_model import get_global_llm_model
        llm_model = get_global_llm_model()

    try:
        adapter = await get_enhanced_memory_adapter(llm_model)
        return await adapter.retrieve_relevant_memories(query, user_id, context, limit)
    except Exception as e:
        logger.error(f"使用增强记忆系统检索记忆失败: {e}", exc_info=True)
        return []


async def get_memory_context_for_prompt(
    query: str,
    user_id: str,
    context: Optional[Dict[str, Any]] = None,
    max_memories: int = 5,
    llm_model: Optional[LLMRequest] = None
) -> str:
    """获取用于提示词的记忆上下文"""
    if not llm_model:
        # 获取默认的LLM模型
        from src.llm_models.utils_model import get_global_llm_model
        llm_model = get_global_llm_model()

    try:
        adapter = await get_enhanced_memory_adapter(llm_model)
        return await adapter.get_memory_context_for_prompt(query, user_id, context, max_memories)
    except Exception as e:
        logger.error(f"获取记忆上下文失败: {e}", exc_info=True)
        return ""