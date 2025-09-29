# -*- coding: utf-8 -*-
"""
增强记忆系统管理器
替代原有的 Hippocampus 和 instant_memory 系统
"""

import asyncio
import time
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from dataclasses import dataclass

from src.common.logger import get_logger
from src.config.config import global_config
from src.chat.memory_system.enhanced_memory_core import EnhancedMemorySystem
from src.chat.memory_system.memory_chunk import MemoryChunk, MemoryType
from src.chat.memory_system.enhanced_memory_adapter import (
    initialize_enhanced_memory_system
)

logger = get_logger(__name__)


@dataclass
class EnhancedMemoryResult:
    """增强记忆查询结果"""
    content: str
    memory_type: str
    confidence: float
    importance: float
    timestamp: float
    source: str = "enhanced_memory"
    relevance_score: float = 0.0


class EnhancedMemoryManager:
    """增强记忆系统管理器 - 替代原有的 HippocampusManager"""

    def __init__(self):
        self.enhanced_system: Optional[EnhancedMemorySystem] = None
        self.is_initialized = False
        self.user_cache = {}  # 用户记忆缓存

    async def initialize(self):
        """初始化增强记忆系统"""
        if self.is_initialized:
            return

        try:
            from src.config.config import global_config

            # 检查是否启用增强记忆系统
            if not global_config.memory.enable_enhanced_memory:
                logger.info("增强记忆系统已禁用，跳过初始化")
                self.is_initialized = True
                return

            logger.info("正在初始化增强记忆系统...")

            # 获取LLM模型
            from src.llm_models.utils_model import LLMRequest
            from src.config.config import model_config
            llm_model = LLMRequest(model_set=model_config.model_task_config.utils, request_type="memory")

            # 初始化增强记忆系统
            self.enhanced_system = await initialize_enhanced_memory_system(llm_model)

            # 设置全局实例
            global_enhanced_manager = self.enhanced_system

            self.is_initialized = True
            logger.info("✅ 增强记忆系统初始化完成")

        except Exception as e:
            logger.error(f"❌ 增强记忆系统初始化失败: {e}")
            # 如果增强系统初始化失败，创建一个空的管理器避免系统崩溃
            self.enhanced_system = None
            self.is_initialized = True  # 标记为已初始化但系统不可用

    def get_hippocampus(self):
        """兼容原有接口 - 返回空"""
        logger.debug("get_hippocampus 调用 - 增强记忆系统不使用此方法")
        return {}

    async def build_memory(self):
        """兼容原有接口 - 构建记忆"""
        if not self.is_initialized or not self.enhanced_system:
            return

        try:
            # 增强记忆系统使用实时构建，不需要定时构建
            logger.debug("build_memory 调用 - 增强记忆系统使用实时构建")
        except Exception as e:
            logger.error(f"build_memory 失败: {e}")

    async def forget_memory(self, percentage: float = 0.005):
        """兼容原有接口 - 遗忘机制"""
        if not self.is_initialized or not self.enhanced_system:
            return

        try:
            # 增强记忆系统有内置的遗忘机制
            logger.debug(f"forget_memory 调用 - 参数: {percentage}")
            # 可以在这里调用增强系统的维护功能
            await self.enhanced_system.maintenance()
        except Exception as e:
            logger.error(f"forget_memory 失败: {e}")

    async def consolidate_memory(self):
        """兼容原有接口 - 记忆巩固"""
        if not self.is_initialized or not self.enhanced_system:
            return

        try:
            # 增强记忆系统自动处理记忆巩固
            logger.debug("consolidate_memory 调用 - 增强记忆系统自动处理")
        except Exception as e:
            logger.error(f"consolidate_memory 失败: {e}")

    async def get_memory_from_text(
        self,
        text: str,
        chat_id: str,
        user_id: str,
        max_memory_num: int = 3,
        max_memory_length: int = 2,
        time_weight: float = 1.0,
        keyword_weight: float = 1.0
    ) -> List[Tuple[str, str]]:
        """从文本获取相关记忆 - 兼容原有接口"""
        if not self.is_initialized or not self.enhanced_system:
            return []

        try:
            # 使用增强记忆系统检索
            context = {
                "chat_id": chat_id,
                "expected_memory_types": [MemoryType.PERSONAL_FACT, MemoryType.EVENT, MemoryType.PREFERENCE]
            }

            relevant_memories = await self.enhanced_system.retrieve_relevant_memories(
                query=text,
                user_id=user_id,
                context=context,
                limit=max_memory_num
            )

            # 转换为原有格式 (topic, content)
            results = []
            for memory in relevant_memories:
                topic = memory.memory_type.value
                content = memory.text_content
                results.append((topic, content))

            logger.debug(f"从文本检索到 {len(results)} 条相关记忆")
            return results

        except Exception as e:
            logger.error(f"get_memory_from_text 失败: {e}")
            return []

    async def get_memory_from_topic(
        self,
        valid_keywords: List[str],
        max_memory_num: int = 3,
        max_memory_length: int = 2,
        max_depth: int = 3
    ) -> List[Tuple[str, str]]:
        """从关键词获取记忆 - 兼容原有接口"""
        if not self.is_initialized or not self.enhanced_system:
            return []

        try:
            # 将关键词转换为查询文本
            query_text = " ".join(valid_keywords)

            # 使用增强记忆系统检索
            context = {
                "keywords": valid_keywords,
                "expected_memory_types": [
                    MemoryType.PERSONAL_FACT,
                    MemoryType.EVENT,
                    MemoryType.PREFERENCE,
                    MemoryType.OPINION
                ]
            }

            relevant_memories = await self.enhanced_system.retrieve_relevant_memories(
                query_text=query_text,
                user_id="default_user",  # 可以根据实际需要传递
                context=context,
                limit=max_memory_num
            )

            # 转换为原有格式 (topic, content)
            results = []
            for memory in relevant_memories:
                topic = memory.memory_type.value
                content = memory.text_content
                results.append((topic, content))

            logger.debug(f"从关键词 {valid_keywords} 检索到 {len(results)} 条相关记忆")
            return results

        except Exception as e:
            logger.error(f"get_memory_from_topic 失败: {e}")
            return []

    def get_memory_from_keyword(self, keyword: str, max_depth: int = 2) -> list:
        """从单个关键词获取记忆 - 兼容原有接口"""
        if not self.is_initialized or not self.enhanced_system:
            return []

        try:
            # 同步方法，返回空列表
            logger.debug(f"get_memory_from_keyword 调用 - 关键词: {keyword}")
            return []
        except Exception as e:
            logger.error(f"get_memory_from_keyword 失败: {e}")
            return []

    async def process_conversation(
        self,
        conversation_text: str,
        context: Dict[str, Any],
        user_id: str,
        timestamp: Optional[float] = None
    ) -> List[MemoryChunk]:
        """处理对话并构建记忆 - 新增功能"""
        if not self.is_initialized or not self.enhanced_system:
            return []

        try:
            result = await self.enhanced_system.process_conversation_memory(
                conversation_text=conversation_text,
                context=context,
                user_id=user_id,
                timestamp=timestamp
            )

            # 从结果中提取记忆块
            memory_chunks = []
            if result.get("success"):
                memory_chunks = result.get("created_memories", [])

            logger.info(f"从对话构建了 {len(memory_chunks)} 条记忆")
            return memory_chunks

        except Exception as e:
            logger.error(f"process_conversation 失败: {e}")
            return []

    async def get_enhanced_memory_context(
        self,
        query_text: str,
        user_id: str,
        context: Optional[Dict[str, Any]] = None,
        limit: int = 5
    ) -> List[EnhancedMemoryResult]:
        """获取增强记忆上下文 - 新增功能"""
        if not self.is_initialized or not self.enhanced_system:
            return []

        try:
            relevant_memories = await self.enhanced_system.retrieve_relevant_memories(
                query=query_text,
                user_id=user_id,
                context=context or {},
                limit=limit
            )

            results = []
            for memory in relevant_memories:
                result = EnhancedMemoryResult(
                    content=memory.text_content,
                    memory_type=memory.memory_type.value,
                    confidence=memory.metadata.confidence.value,
                    importance=memory.metadata.importance.value,
                    timestamp=memory.metadata.created_at,
                    source="enhanced_memory",
                    relevance_score=memory.metadata.relevance_score
                )
                results.append(result)

            return results

        except Exception as e:
            logger.error(f"get_enhanced_memory_context 失败: {e}")
            return []

    async def shutdown(self):
        """关闭增强记忆系统"""
        if not self.is_initialized:
            return

        try:
            if self.enhanced_system:
                await self.enhanced_system.shutdown()
            logger.info("✅ 增强记忆系统已关闭")
        except Exception as e:
            logger.error(f"关闭增强记忆系统失败: {e}")


# 全局增强记忆管理器实例
enhanced_memory_manager = EnhancedMemoryManager()