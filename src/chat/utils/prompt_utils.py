"""
共享提示词工具模块 - 消除重复代码
提供统一的工具函数供DefaultReplyer和SmartPrompt使用
"""
import re
import time
import asyncio
from typing import Dict, Any, List, Optional, Tuple, Union
from datetime import datetime

from src.common.logger import get_logger
from src.config.config import global_config
from src.chat.utils.chat_message_builder import (
    build_readable_messages,
    get_raw_msg_before_timestamp_with_chat,
    build_readable_messages_with_id,
)
from src.chat.message_receive.chat_stream import get_chat_manager
from src.person_info.person_info import get_person_info_manager

logger = get_logger("prompt_utils")


class PromptUtils:
    """提示词工具类 - 提供共享功能"""
    
    @staticmethod
    def parse_reply_target(target_message: str) -> Tuple[str, str]:
        """
        解析回复目标消息 - 统一实现
        
        Args:
            target_message: 目标消息，格式为 "发送者:消息内容" 或 "发送者：消息内容"
            
        Returns:
            Tuple[str, str]: (发送者名称, 消息内容)
        """
        sender = ""
        target = ""
        
        # 添加None检查，防止NoneType错误
        if target_message is None:
            return sender, target
            
        if ":" in target_message or "：" in target_message:
            # 使用正则表达式匹配中文或英文冒号
            parts = re.split(pattern=r"[:：]", string=target_message, maxsplit=1)
            if len(parts) == 2:
                sender = parts[0].strip()
                target = parts[1].strip()
        return sender, target
    
    @staticmethod
    async def build_cross_context_block(
        chat_id: str, 
        target_user_info: Optional[Dict[str, Any]], 
        current_prompt_mode: str
    ) -> str:
        """
        构建跨群聊上下文 - 统一实现
        
        Args:
            chat_id: 当前聊天ID
            target_user_info: 目标用户信息
            current_prompt_mode: 当前提示模式
            
        Returns:
            str: 跨群上下文块
        """
        if not global_config.cross_context.enable:
            return ""

        # 找到当前群聊所在的共享组
        target_group = None
        current_stream = get_chat_manager().get_stream(chat_id)
        if not current_stream or not current_stream.group_info:
            return ""
        current_chat_raw_id = current_stream.group_info.group_id

        for group in global_config.cross_context.groups:
            if str(current_chat_raw_id) in group.chat_ids:
                target_group = group
                break

        if not target_group:
            return ""

        # 根据prompt_mode选择策略
        other_chat_raw_ids = [chat_id for chat_id in target_group.chat_ids if chat_id != str(current_chat_raw_id)]

        cross_context_messages = []

        if current_prompt_mode == "normal":
            # normal模式：获取其他群聊的最近N条消息
            for chat_raw_id in other_chat_raw_ids:
                stream_id = get_chat_manager().get_stream_id(current_stream.platform, chat_raw_id, is_group=True)
                if not stream_id:
                    continue

                messages = get_raw_msg_before_timestamp_with_chat(
                    chat_id=stream_id,
                    timestamp=time.time(),
                    limit=5,  # 可配置
                )
                if messages:
                    chat_name = get_chat_manager().get_stream_name(stream_id) or stream_id
                    formatted_messages, _ = build_readable_messages_with_id(messages, timestamp_mode="relative")
                    cross_context_messages.append(f"[以下是来自\"{chat_name}\"的近期消息]\n{formatted_messages}")

        elif current_prompt_mode == "s4u":
            # s4u模式：获取当前发言用户在其他群聊的消息
            if target_user_info:
                user_id = target_user_info.get("user_id")

                if user_id:
                    for chat_raw_id in other_chat_raw_ids:
                        stream_id = get_chat_manager().get_stream_id(
                            current_stream.platform, chat_raw_id, is_group=True
                        )
                        if not stream_id:
                            continue

                        messages = get_raw_msg_before_timestamp_with_chat(
                            chat_id=stream_id,
                            timestamp=time.time(),
                            limit=20,  # 获取更多消息以供筛选
                        )
                        user_messages = [msg for msg in messages if msg.get("user_id") == user_id][
                            -5:
                        ]  # 筛选并取最近5条

                        if user_messages:
                            chat_name = get_chat_manager().get_stream_name(stream_id) or stream_id
                            user_name = (
                                target_user_info.get("person_name") or
                                target_user_info.get("user_nickname") or user_id
                            )
                            formatted_messages, _ = build_readable_messages_with_id(
                                user_messages, timestamp_mode="relative"
                            )
                            cross_context_messages.append(
                                f"[以下是\"{user_name}\"在\"{chat_name}\"的近期发言]\n{formatted_messages}"
                            )

        if not cross_context_messages:
            return ""

        return "# 跨群上下文参考\n" + "\n\n".join(cross_context_messages) + "\n"
    
    @staticmethod
    def parse_reply_target_id(reply_to: str) -> str:
        """
        解析回复目标中的用户ID
        
        Args:
            reply_to: 回复目标字符串
            
        Returns:
            str: 用户ID
        """
        if not reply_to:
            return ""
        
        # 复用parse_reply_target方法的逻辑
        sender, _ = PromptUtils.parse_reply_target(reply_to)
        if not sender:
            return ""
        
        # 获取用户ID
        person_info_manager = get_person_info_manager()
        person_id = person_info_manager.get_person_id_by_person_name(sender)
        if person_id:
            user_id = person_info_manager.get_value_sync(person_id, "user_id")
            return str(user_id) if user_id else ""
        
        return ""


class DependencyChecker:
    """依赖检查器 - 检查关键组件的可用性"""
    
    @staticmethod
    async def check_expression_dependencies() -> Tuple[bool, List[str]]:
        """
        检查表达系统依赖
        
        Returns:
            Tuple[bool, List[str]]: (是否可用, 缺失的依赖列表)
        """
        missing_deps = []
        try:
            from src.chat.express.expression_selector import expression_selector
            # 尝试访问一个方法以确保模块可用
            if not hasattr(expression_selector, 'select_suitable_expressions_llm'):
                missing_deps.append("expression_selector.select_suitable_expressions_llm")
        except ImportError as e:
            missing_deps.append(f"expression_selector: {str(e)}")
        
        return len(missing_deps) == 0, missing_deps
    
    @staticmethod
    async def check_memory_dependencies() -> Tuple[bool, List[str]]:
        """
        检查记忆系统依赖
        
        Returns:
            Tuple[bool, List[str]]: (是否可用, 缺失的依赖列表)
        """
        missing_deps = []
        try:
            from src.chat.memory_system.memory_activator import MemoryActivator
            from src.chat.memory_system.vector_instant_memory import VectorInstantMemoryV2
        except ImportError as e:
            missing_deps.append(f"memory_system: {str(e)}")
        
        return len(missing_deps) == 0, missing_deps
    
    @staticmethod
    async def check_tool_dependencies() -> Tuple[bool, List[str]]:
        """
        检查工具系统依赖
        
        Returns:
            Tuple[bool, List[str]]: (是否可用, 缺失的依赖列表)
        """
        missing_deps = []
        try:
            from src.plugin_system.core.tool_use import ToolExecutor
        except ImportError as e:
            missing_deps.append(f"tool_executor: {str(e)}")
        
        return len(missing_deps) == 0, missing_deps
    
    @staticmethod
    async def check_knowledge_dependencies() -> Tuple[bool, List[str]]:
        """
        检查知识系统依赖
        
        Returns:
            Tuple[bool, List[str]]: (是否可用, 缺失的依赖列表)
        """
        missing_deps = []
        try:
            from src.plugins.built_in.knowledge.lpmm_get_knowledge import SearchKnowledgeFromLPMMTool
        except ImportError as e:
            missing_deps.append(f"knowledge_tool: {str(e)}")
        
        return len(missing_deps) == 0, missing_deps
    
    @staticmethod
    async def check_all_dependencies() -> Dict[str, Tuple[bool, List[str]]]:
        """
        检查所有依赖
        
        Returns:
            Dict[str, Tuple[bool, List[str]]]: 各系统依赖状态
        """
        return {
            "expression": await DependencyChecker.check_expression_dependencies(),
            "memory": await DependencyChecker.check_memory_dependencies(),
            "tool": await DependencyChecker.check_tool_dependencies(),
            "knowledge": await DependencyChecker.check_knowledge_dependencies(),
        }


class SmartPromptCache:
    """智能提示词缓存系统 - 分层缓存实现"""
    
    def __init__(self):
        self._l1_cache: Dict[str, Tuple[str, float]] = {}  # 内存缓存: {key: (value, timestamp)}
        self._l2_cache_enabled = False  # 是否启用L2缓存
        self._cache_ttl = 300  # 默认缓存TTL: 5分钟
        
    def enable_l2_cache(self, enabled: bool = True):
        """启用或禁用L2缓存"""
        self._l2_cache_enabled = enabled
        
    def set_cache_ttl(self, ttl: int):
        """设置缓存TTL（秒）"""
        self._cache_ttl = ttl
        
    def _generate_key(self, chat_id: str, prompt_mode: str, reply_to: str) -> str:
        """生成缓存键"""
        import hashlib
        key_content = f"{chat_id}_{prompt_mode}_{reply_to}"
        return hashlib.md5(key_content.encode()).hexdigest()
        
    def get(self, chat_id: str, prompt_mode: str, reply_to: str) -> Optional[str]:
        """获取缓存值"""
        cache_key = self._generate_key(chat_id, prompt_mode, reply_to)
        
        # 检查L1缓存
        if cache_key in self._l1_cache:
            value, timestamp = self._l1_cache[cache_key]
            if time.time() - timestamp < self._cache_ttl:
                logger.debug(f"L1缓存命中: {cache_key}")
                return value
            else:
                # 缓存过期，清理
                del self._l1_cache[cache_key]
                
        # TODO: 实现L2缓存（如Redis）
        # if self._l2_cache_enabled:
        #     return self._get_from_l2_cache(cache_key)
                
        return None
        
    def set(self, chat_id: str, prompt_mode: str, reply_to: str, value: str):
        """设置缓存值"""
        cache_key = self._generate_key(chat_id, prompt_mode, reply_to)
        
        # 设置L1缓存
        self._l1_cache[cache_key] = (value, time.time())
        
        # TODO: 实现L2缓存
        # if self._l2_cache_enabled:
        #     self._set_to_l2_cache(cache_key, value)
            
        # 定期清理过期缓存
        if len(self._l1_cache) > 1000:  # 缓存条目过多时清理
            self._clean_expired_cache()
            
    def _clean_expired_cache(self):
        """清理过期缓存"""
        current_time = time.time()
        expired_keys = [
            key for key, (_, timestamp) in self._l1_cache.items()
            if current_time - timestamp >= self._cache_ttl
        ]
        for key in expired_keys:
            del self._l1_cache[key]
            
        logger.debug(f"清理过期缓存: {len(expired_keys)} 个条目")
        
    def clear(self):
        """清空所有缓存"""
        self._l1_cache.clear()
        # TODO: 清空L2缓存
        logger.info("缓存已清空")
        
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        return {
            "l1_cache_size": len(self._l1_cache),
            "l2_cache_enabled": self._l2_cache_enabled,
            "cache_ttl": self._cache_ttl,
        }