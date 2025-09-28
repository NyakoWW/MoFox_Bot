"""
重构后的聊天上下文管理器
提供统一、稳定的聊天上下文管理功能
每个 context_manager 实例只管理一个 stream 的上下文
"""

import asyncio
import time
from typing import Dict, List, Optional, Any

from src.common.data_models.message_manager_data_model import StreamContext
from src.common.logger import get_logger
from src.config.config import global_config
from src.common.data_models.database_data_model import DatabaseMessages
from src.chat.energy_system import energy_manager
from .distribution_manager import distribution_manager

logger = get_logger("context_manager")


class SingleStreamContextManager:
    """单流上下文管理器 - 每个实例只管理一个 stream 的上下文"""

    def __init__(self, stream_id: str, context: StreamContext, max_context_size: Optional[int] = None):
        self.stream_id = stream_id
        self.context = context

        # 配置参数
        self.max_context_size = max_context_size or getattr(global_config.chat, "max_context_size", 100)
        self.context_ttl = getattr(global_config.chat, "context_ttl", 24 * 3600)  # 24小时

        # 元数据
        self.created_time = time.time()
        self.last_access_time = time.time()
        self.access_count = 0
        self.total_messages = 0

        logger.debug(f"单流上下文管理器初始化: {stream_id}")

    def get_context(self) -> StreamContext:
        """获取流上下文"""
        self._update_access_stats()
        return self.context

    def add_message(self, message: DatabaseMessages, skip_energy_update: bool = False) -> bool:
        """添加消息到上下文

        Args:
            message: 消息对象
            skip_energy_update: 是否跳过能量更新

        Returns:
            bool: 是否成功添加
        """
        try:
            # 添加消息到上下文
            self.context.add_message(message)

            # 计算消息兴趣度
            interest_value = self._calculate_message_interest(message)
            message.interest_value = interest_value

            # 更新统计
            self.total_messages += 1
            self.last_access_time = time.time()

            # 更新能量和分发
            if not skip_energy_update:
                self._update_stream_energy()
                distribution_manager.add_stream_message(self.stream_id, 1)

            logger.debug(f"添加消息到单流上下文: {self.stream_id} (兴趣度: {interest_value:.3f})")
            return True

        except Exception as e:
            logger.error(f"添加消息到单流上下文失败 {self.stream_id}: {e}", exc_info=True)
            return False

    def update_message(self, message_id: str, updates: Dict[str, Any]) -> bool:
        """更新上下文中的消息

        Args:
            message_id: 消息ID
            updates: 更新的属性

        Returns:
            bool: 是否成功更新
        """
        try:
            # 更新消息信息
            self.context.update_message_info(message_id, **updates)

            # 如果更新了兴趣度，重新计算能量
            if "interest_value" in updates:
                self._update_stream_energy()

            logger.debug(f"更新单流上下文消息: {self.stream_id}/{message_id}")
            return True

        except Exception as e:
            logger.error(f"更新单流上下文消息失败 {self.stream_id}/{message_id}: {e}", exc_info=True)
            return False

    def get_messages(self, limit: Optional[int] = None, include_unread: bool = True) -> List[DatabaseMessages]:
        """获取上下文消息

        Args:
            limit: 消息数量限制
            include_unread: 是否包含未读消息

        Returns:
            List[DatabaseMessages]: 消息列表
        """
        try:
            messages = []
            if include_unread:
                messages.extend(self.context.get_unread_messages())

            if limit:
                messages.extend(self.context.get_history_messages(limit=limit))
            else:
                messages.extend(self.context.get_history_messages())

            # 按时间排序
            messages.sort(key=lambda msg: getattr(msg, "time", 0))

            # 应用限制
            if limit and len(messages) > limit:
                messages = messages[-limit:]

            return messages

        except Exception as e:
            logger.error(f"获取单流上下文消息失败 {self.stream_id}: {e}", exc_info=True)
            return []

    def get_unread_messages(self) -> List[DatabaseMessages]:
        """获取未读消息"""
        try:
            return self.context.get_unread_messages()
        except Exception as e:
            logger.error(f"获取单流未读消息失败 {self.stream_id}: {e}", exc_info=True)
            return []

    def mark_messages_as_read(self, message_ids: List[str]) -> bool:
        """标记消息为已读"""
        try:
            if not hasattr(self.context, "mark_message_as_read"):
                logger.error(f"上下文对象缺少 mark_message_as_read 方法: {self.stream_id}")
                return False

            marked_count = 0
            for message_id in message_ids:
                try:
                    self.context.mark_message_as_read(message_id)
                    marked_count += 1
                except Exception as e:
                    logger.warning(f"标记消息已读失败 {message_id}: {e}")

            logger.debug(f"标记消息为已读: {self.stream_id} ({marked_count}/{len(message_ids)}条)")
            return marked_count > 0

        except Exception as e:
            logger.error(f"标记消息已读失败 {self.stream_id}: {e}", exc_info=True)
            return False

    def clear_context(self) -> bool:
        """清空上下文"""
        try:
            # 清空消息
            if hasattr(self.context, "unread_messages"):
                self.context.unread_messages.clear()
            if hasattr(self.context, "history_messages"):
                self.context.history_messages.clear()

            # 重置状态
            reset_attrs = ["interruption_count", "afc_threshold_adjustment", "last_check_time"]
            for attr in reset_attrs:
                if hasattr(self.context, attr):
                    if attr in ["interruption_count", "afc_threshold_adjustment"]:
                        setattr(self.context, attr, 0)
                    else:
                        setattr(self.context, attr, time.time())

            # 重新计算能量
            self._update_stream_energy()

            logger.info(f"清空单流上下文: {self.stream_id}")
            return True

        except Exception as e:
            logger.error(f"清空单流上下文失败 {self.stream_id}: {e}", exc_info=True)
            return False

    def get_statistics(self) -> Dict[str, Any]:
        """获取流统计信息"""
        try:
            current_time = time.time()
            uptime = current_time - self.created_time

            unread_messages = getattr(self.context, "unread_messages", [])
            history_messages = getattr(self.context, "history_messages", [])

            return {
                "stream_id": self.stream_id,
                "context_type": type(self.context).__name__,
                "total_messages": len(history_messages) + len(unread_messages),
                "unread_messages": len(unread_messages),
                "history_messages": len(history_messages),
                "is_active": getattr(self.context, "is_active", True),
                "last_check_time": getattr(self.context, "last_check_time", current_time),
                "interruption_count": getattr(self.context, "interruption_count", 0),
                "afc_threshold_adjustment": getattr(self.context, "afc_threshold_adjustment", 0.0),
                "created_time": self.created_time,
                "last_access_time": self.last_access_time,
                "access_count": self.access_count,
                "uptime_seconds": uptime,
                "idle_seconds": current_time - self.last_access_time,
            }
        except Exception as e:
            logger.error(f"获取单流统计失败 {self.stream_id}: {e}", exc_info=True)
            return {}

    def validate_integrity(self) -> bool:
        """验证上下文完整性"""
        try:
            # 检查基本属性
            required_attrs = ["stream_id", "unread_messages", "history_messages"]
            for attr in required_attrs:
                if not hasattr(self.context, attr):
                    logger.warning(f"上下文缺少必要属性: {attr}")
                    return False

            # 检查消息ID唯一性
            all_messages = getattr(self.context, "unread_messages", []) + getattr(self.context, "history_messages", [])
            message_ids = [msg.message_id for msg in all_messages if hasattr(msg, "message_id")]
            if len(message_ids) != len(set(message_ids)):
                logger.warning(f"上下文中存在重复消息ID: {self.stream_id}")
                return False

            return True

        except Exception as e:
            logger.error(f"验证单流上下文完整性失败 {self.stream_id}: {e}")
            return False

    def _update_access_stats(self):
        """更新访问统计"""
        self.last_access_time = time.time()
        self.access_count += 1

    def _calculate_message_interest(self, message: DatabaseMessages) -> float:
        """计算消息兴趣度"""
        try:
            # 使用插件内部的兴趣度评分系统
            try:
                from src.plugins.built_in.affinity_flow_chatter.interest_scoring import chatter_interest_scoring_system

                # 使用插件内部的兴趣度评分系统计算（同步方式）
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                interest_score = loop.run_until_complete(
                    chatter_interest_scoring_system._calculate_single_message_score(
                        message=message, bot_nickname=global_config.bot.nickname
                    )
                )
                interest_value = interest_score.total_score

                logger.debug(f"使用插件内部系统计算兴趣度: {interest_value:.3f}")

            except Exception as e:
                logger.warning(f"插件内部兴趣度计算失败，使用默认值: {e}")
                interest_value = 0.5  # 默认中等兴趣度

            return interest_value

        except Exception as e:
            logger.error(f"计算消息兴趣度失败: {e}")
            return 0.5

    async def _update_stream_energy(self):
        """更新流能量"""
        try:
            # 获取所有消息
            all_messages = self.get_messages(self.max_context_size)
            unread_messages = self.get_unread_messages()
            combined_messages = all_messages + unread_messages

            # 获取用户ID
            user_id = None
            if combined_messages:
                last_message = combined_messages[-1]
                user_id = last_message.user_info.user_id

            # 计算能量
            energy = await energy_manager.calculate_focus_energy(
                stream_id=self.stream_id, messages=combined_messages, user_id=user_id
            )

            # 更新分发管理器
            distribution_manager.update_stream_energy(self.stream_id, energy)

        except Exception as e:
            logger.error(f"更新单流能量失败 {self.stream_id}: {e}")