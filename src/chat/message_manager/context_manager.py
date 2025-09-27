"""
重构后的聊天上下文管理器
提供统一、稳定的聊天上下文管理功能
"""

import asyncio
import time
from typing import Dict, List, Optional, Any, Union, Tuple
from abc import ABC, abstractmethod

from src.common.data_models.message_manager_data_model import StreamContext
from src.common.logger import get_logger
from src.config.config import global_config
from src.common.data_models.database_data_model import DatabaseMessages
from src.chat.energy_system import energy_manager
from .distribution_manager import distribution_manager

logger = get_logger("context_manager")

class StreamContextManager:
    """流上下文管理器 - 统一管理所有聊天流上下文"""

    def __init__(self, max_context_size: Optional[int] = None, context_ttl: Optional[int] = None):
        # 上下文存储
        self.stream_contexts: Dict[str, Any] = {}
        self.context_metadata: Dict[str, Dict[str, Any]] = {}

        # 统计信息
        self.stats: Dict[str, Union[int, float, str, Dict]] = {
            "total_messages": 0,
            "total_streams": 0,
            "active_streams": 0,
            "inactive_streams": 0,
            "last_activity": time.time(),
            "creation_time": time.time(),
        }

        # 配置参数
        self.max_context_size = max_context_size or getattr(global_config.chat, "max_context_size", 100)
        self.context_ttl = context_ttl or getattr(global_config.chat, "context_ttl", 24 * 3600)  # 24小时
        self.cleanup_interval = getattr(global_config.chat, "context_cleanup_interval", 3600)  # 1小时
        self.auto_cleanup = getattr(global_config.chat, "auto_cleanup_contexts", True)
        self.enable_validation = getattr(global_config.chat, "enable_context_validation", True)

        # 清理任务
        self.cleanup_task: Optional[Any] = None
        self.is_running = False

        logger.info(f"上下文管理器初始化完成 (最大上下文: {self.max_context_size}, TTL: {self.context_ttl}s)")

    def add_stream_context(self, stream_id: str, context: Any, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """添加流上下文

        Args:
            stream_id: 流ID
            context: 上下文对象
            metadata: 上下文元数据

        Returns:
            bool: 是否成功添加
        """
        if stream_id in self.stream_contexts:
            logger.warning(f"流上下文已存在: {stream_id}")
            return False

        # 添加上下文
        self.stream_contexts[stream_id] = context

        # 初始化元数据
        self.context_metadata[stream_id] = {
            "created_time": time.time(),
            "last_access_time": time.time(),
            "access_count": 0,
            "last_validation_time": 0.0,
            "custom_metadata": metadata or {},
        }

        # 更新统计
        self.stats["total_streams"] += 1
        self.stats["active_streams"] += 1
        self.stats["last_activity"] = time.time()

        logger.debug(f"添加流上下文: {stream_id} (类型: {type(context).__name__})")
        return True

    def remove_stream_context(self, stream_id: str) -> bool:
        """移除流上下文

        Args:
            stream_id: 流ID

        Returns:
            bool: 是否成功移除
        """
        if stream_id in self.stream_contexts:
            context = self.stream_contexts[stream_id]
            metadata = self.context_metadata.get(stream_id, {})

            del self.stream_contexts[stream_id]
            if stream_id in self.context_metadata:
                del self.context_metadata[stream_id]

            self.stats["active_streams"] = max(0, self.stats["active_streams"] - 1)
            self.stats["inactive_streams"] += 1
            self.stats["last_activity"] = time.time()

            logger.debug(f"移除流上下文: {stream_id} (类型: {type(context).__name__})")
            return True
        return False

    def get_stream_context(self, stream_id: str, update_access: bool = True) -> Optional[StreamContext]:
        """获取流上下文

        Args:
            stream_id: 流ID
            update_access: 是否更新访问统计

        Returns:
            Optional[Any]: 上下文对象
        """
        context = self.stream_contexts.get(stream_id)
        if context and update_access:
            # 更新访问统计
            if stream_id in self.context_metadata:
                metadata = self.context_metadata[stream_id]
                metadata["last_access_time"] = time.time()
                metadata["access_count"] = metadata.get("access_count", 0) + 1
        return context

    def get_context_metadata(self, stream_id: str) -> Optional[Dict[str, Any]]:
        """获取上下文元数据

        Args:
            stream_id: 流ID

        Returns:
            Optional[Dict[str, Any]]: 元数据
        """
        return self.context_metadata.get(stream_id)

    def update_context_metadata(self, stream_id: str, updates: Dict[str, Any]) -> bool:
        """更新上下文元数据

        Args:
            stream_id: 流ID
            updates: 更新的元数据

        Returns:
            bool: 是否成功更新
        """
        if stream_id not in self.context_metadata:
            return False

        self.context_metadata[stream_id].update(updates)
        return True

    def add_message_to_context(self, stream_id: str, message: DatabaseMessages, skip_energy_update: bool = False) -> bool:
        """添加消息到上下文

        Args:
            stream_id: 流ID
            message: 消息对象
            skip_energy_update: 是否跳过能量更新

        Returns:
            bool: 是否成功添加
        """
        context = self.get_stream_context(stream_id)
        if not context:
            logger.warning(f"流上下文不存在: {stream_id}")
            return False

        try:
            # 添加消息到上下文
            context.add_message(message)

            # 计算消息兴趣度
            interest_value = self._calculate_message_interest(message)
            message.interest_value = interest_value

            # 更新统计
            self.stats["total_messages"] += 1
            self.stats["last_activity"] = time.time()

            # 更新能量和分发
            if not skip_energy_update:
                self._update_stream_energy(stream_id)
                distribution_manager.add_stream_message(stream_id, 1)

            logger.debug(f"添加消息到上下文: {stream_id} (兴趣度: {interest_value:.3f})")
            return True

        except Exception as e:
            logger.error(f"添加消息到上下文失败 {stream_id}: {e}", exc_info=True)
            return False

    def update_message_in_context(self, stream_id: str, message_id: str, updates: Dict[str, Any]) -> bool:
        """更新上下文中的消息

        Args:
            stream_id: 流ID
            message_id: 消息ID
            updates: 更新的属性

        Returns:
            bool: 是否成功更新
        """
        context = self.get_stream_context(stream_id)
        if not context:
            logger.warning(f"流上下文不存在: {stream_id}")
            return False

        try:
            # 更新消息信息
            context.update_message_info(message_id, **updates)

            # 如果更新了兴趣度，重新计算能量
            if "interest_value" in updates:
                self._update_stream_energy(stream_id)

            logger.debug(f"更新上下文消息: {stream_id}/{message_id}")
            return True

        except Exception as e:
            logger.error(f"更新上下文消息失败 {stream_id}/{message_id}: {e}", exc_info=True)
            return False

    def get_context_messages(self, stream_id: str, limit: Optional[int] = None, include_unread: bool = True) -> List[DatabaseMessages]:
        """获取上下文消息

        Args:
            stream_id: 流ID
            limit: 消息数量限制
            include_unread: 是否包含未读消息

        Returns:
            List[Any]: 消息列表
        """
        context = self.get_stream_context(stream_id)
        if not context:
            return []

        try:
            messages = []
            if include_unread:
                messages.extend(context.get_unread_messages())

            if limit:
                messages.extend(context.get_history_messages(limit=limit))
            else:
                messages.extend(context.get_history_messages())

            # 按时间排序
            messages.sort(key=lambda msg: getattr(msg, 'time', 0))

            # 应用限制
            if limit and len(messages) > limit:
                messages = messages[-limit:]

            return messages

        except Exception as e:
            logger.error(f"获取上下文消息失败 {stream_id}: {e}", exc_info=True)
            return []

    def get_unread_messages(self, stream_id: str) -> List[DatabaseMessages]:
        """获取未读消息

        Args:
            stream_id: 流ID

        Returns:
            List[Any]: 未读消息列表
        """
        context = self.get_stream_context(stream_id)
        if not context:
            return []

        try:
            return context.get_unread_messages()
        except Exception as e:
            logger.error(f"获取未读消息失败 {stream_id}: {e}", exc_info=True)
            return []

    def mark_messages_as_read(self, stream_id: str, message_ids: List[str]) -> bool:
        """标记消息为已读

        Args:
            stream_id: 流ID
            message_ids: 消息ID列表

        Returns:
            bool: 是否成功标记
        """
        context = self.get_stream_context(stream_id)
        if not context:
            logger.warning(f"流上下文不存在: {stream_id}")
            return False

        try:
            if not hasattr(context, 'mark_message_as_read'):
                logger.error(f"上下文对象缺少 mark_message_as_read 方法: {stream_id}")
                return False

            marked_count = 0
            for message_id in message_ids:
                try:
                    context.mark_message_as_read(message_id)
                    marked_count += 1
                except Exception as e:
                    logger.warning(f"标记消息已读失败 {message_id}: {e}")

            logger.debug(f"标记消息为已读: {stream_id} ({marked_count}/{len(message_ids)}条)")
            return marked_count > 0

        except Exception as e:
            logger.error(f"标记消息已读失败 {stream_id}: {e}", exc_info=True)
            return False

    def clear_context(self, stream_id: str) -> bool:
        """清空上下文

        Args:
            stream_id: 流ID

        Returns:
            bool: 是否成功清空
        """
        context = self.get_stream_context(stream_id)
        if not context:
            logger.warning(f"流上下文不存在: {stream_id}")
            return False

        try:
            # 清空消息
            if hasattr(context, 'unread_messages'):
                context.unread_messages.clear()
            if hasattr(context, 'history_messages'):
                context.history_messages.clear()

            # 重置状态
            reset_attrs = ['interruption_count', 'afc_threshold_adjustment', 'last_check_time']
            for attr in reset_attrs:
                if hasattr(context, attr):
                    if attr in ['interruption_count', 'afc_threshold_adjustment']:
                        setattr(context, attr, 0)
                    else:
                        setattr(context, attr, time.time())

            # 重新计算能量
            self._update_stream_energy(stream_id)

            logger.info(f"清空上下文: {stream_id}")
            return True

        except Exception as e:
            logger.error(f"清空上下文失败 {stream_id}: {e}", exc_info=True)
            return False

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
                        message=message,
                        bot_nickname=global_config.bot.nickname
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

    def _update_stream_energy(self, stream_id: str):
        """更新流能量"""
        try:
            # 获取所有消息
            all_messages = self.get_context_messages(stream_id, self.max_context_size)
            unread_messages = self.get_unread_messages(stream_id)
            combined_messages = all_messages + unread_messages

            # 获取用户ID
            user_id = None
            if combined_messages:
                last_message = combined_messages[-1]
                user_id = last_message.user_info.user_id

            # 计算能量
            energy = energy_manager.calculate_focus_energy(
                stream_id=stream_id,
                messages=combined_messages,
                user_id=user_id
            )

            # 更新分发管理器
            distribution_manager.update_stream_energy(stream_id, energy)

        except Exception as e:
            logger.error(f"更新流能量失败 {stream_id}: {e}")

    def get_stream_statistics(self, stream_id: str) -> Optional[Dict[str, Any]]:
        """获取流统计信息

        Args:
            stream_id: 流ID

        Returns:
            Optional[Dict[str, Any]]: 统计信息
        """
        context = self.get_stream_context(stream_id, update_access=False)
        if not context:
            return None

        try:
            metadata = self.context_metadata.get(stream_id, {})
            current_time = time.time()
            created_time = metadata.get("created_time", current_time)
            last_access_time = metadata.get("last_access_time", current_time)
            access_count = metadata.get("access_count", 0)

            unread_messages = getattr(context, "unread_messages", [])
            history_messages = getattr(context, "history_messages", [])

            return {
                "stream_id": stream_id,
                "context_type": type(context).__name__,
                "total_messages": len(history_messages) + len(unread_messages),
                "unread_messages": len(unread_messages),
                "history_messages": len(history_messages),
                "is_active": getattr(context, "is_active", True),
                "last_check_time": getattr(context, "last_check_time", current_time),
                "interruption_count": getattr(context, "interruption_count", 0),
                "afc_threshold_adjustment": getattr(context, "afc_threshold_adjustment", 0.0),
                "created_time": created_time,
                "last_access_time": last_access_time,
                "access_count": access_count,
                "uptime_seconds": current_time - created_time,
                "idle_seconds": current_time - last_access_time,
            }
        except Exception as e:
            logger.error(f"获取流统计失败 {stream_id}: {e}", exc_info=True)
            return None

    def get_manager_statistics(self) -> Dict[str, Any]:
        """获取管理器统计信息

        Returns:
            Dict[str, Any]: 管理器统计信息
        """
        current_time = time.time()
        uptime = current_time - self.stats.get("creation_time", current_time)

        return {
            **self.stats,
            "uptime_hours": uptime / 3600,
            "stream_count": len(self.stream_contexts),
            "metadata_count": len(self.context_metadata),
            "auto_cleanup_enabled": self.auto_cleanup,
            "cleanup_interval": self.cleanup_interval,
        }

    def cleanup_inactive_contexts(self, max_inactive_hours: int = 24) -> int:
        """清理不活跃的上下文

        Args:
            max_inactive_hours: 最大不活跃小时数

        Returns:
            int: 清理的上下文数量
        """
        current_time = time.time()
        max_inactive_seconds = max_inactive_hours * 3600

        inactive_streams = []
        for stream_id, context in self.stream_contexts.items():
            try:
                # 获取最后活动时间
                metadata = self.context_metadata.get(stream_id, {})
                last_activity = metadata.get("last_access_time", metadata.get("created_time", 0))
                context_last_activity = getattr(context, "last_check_time", 0)
                actual_last_activity = max(last_activity, context_last_activity)

                # 检查是否不活跃
                unread_count = len(getattr(context, "unread_messages", []))
                history_count = len(getattr(context, "history_messages", []))
                total_messages = unread_count + history_count

                if (current_time - actual_last_activity > max_inactive_seconds and
                    total_messages == 0):
                    inactive_streams.append(stream_id)
            except Exception as e:
                logger.warning(f"检查上下文活跃状态失败 {stream_id}: {e}")
                continue

        # 清理不活跃上下文
        cleaned_count = 0
        for stream_id in inactive_streams:
            if self.remove_stream_context(stream_id):
                cleaned_count += 1

        if cleaned_count > 0:
            logger.info(f"清理了 {cleaned_count} 个不活跃上下文")

        return cleaned_count

    def validate_context_integrity(self, stream_id: str) -> bool:
        """验证上下文完整性

        Args:
            stream_id: 流ID

        Returns:
            bool: 是否完整
        """
        context = self.get_stream_context(stream_id)
        if not context:
            return False

        try:
            # 检查基本属性
            required_attrs = ["stream_id", "unread_messages", "history_messages"]
            for attr in required_attrs:
                if not hasattr(context, attr):
                    logger.warning(f"上下文缺少必要属性: {attr}")
                    return False

            # 检查消息ID唯一性
            all_messages = getattr(context, "unread_messages", []) + getattr(context, "history_messages", [])
            message_ids = [msg.message_id for msg in all_messages if hasattr(msg, "message_id")]
            if len(message_ids) != len(set(message_ids)):
                logger.warning(f"上下文中存在重复消息ID: {stream_id}")
                return False

            return True

        except Exception as e:
            logger.error(f"验证上下文完整性失败 {stream_id}: {e}")
            return False

    async def start(self) -> None:
        """启动上下文管理器"""
        if self.is_running:
            logger.warning("上下文管理器已经在运行")
            return

        await self.start_auto_cleanup()
        logger.info("上下文管理器已启动")

    async def stop(self) -> None:
        """停止上下文管理器"""
        if not self.is_running:
            return

        await self.stop_auto_cleanup()
        logger.info("上下文管理器已停止")

    async def start_auto_cleanup(self, interval: Optional[float] = None) -> None:
        """启动自动清理

        Args:
            interval: 清理间隔（秒）
        """
        if not self.auto_cleanup:
            logger.info("自动清理已禁用")
            return

        if self.is_running:
            logger.warning("自动清理已在运行")
            return

        self.is_running = True
        cleanup_interval = interval or self.cleanup_interval
        logger.info(f"启动自动清理（间隔: {cleanup_interval}s）")

        import asyncio
        self.cleanup_task = asyncio.create_task(self._cleanup_loop(cleanup_interval))

    async def stop_auto_cleanup(self) -> None:
        """停止自动清理"""
        self.is_running = False
        if self.cleanup_task and not self.cleanup_task.done():
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except Exception:
                pass
        logger.info("自动清理已停止")

    async def _cleanup_loop(self, interval: float) -> None:
        """清理循环

        Args:
            interval: 清理间隔
        """
        while self.is_running:
            try:
                await asyncio.sleep(interval)
                self.cleanup_inactive_contexts()
                self._cleanup_expired_contexts()
                logger.debug("自动清理完成")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"清理循环出错: {e}", exc_info=True)
                await asyncio.sleep(interval)

    def _cleanup_expired_contexts(self) -> None:
        """清理过期上下文"""
        current_time = time.time()
        expired_contexts = []

        for stream_id, metadata in self.context_metadata.items():
            created_time = metadata.get("created_time", current_time)
            if current_time - created_time > self.context_ttl:
                expired_contexts.append(stream_id)

        for stream_id in expired_contexts:
            self.remove_stream_context(stream_id)

        if expired_contexts:
            logger.info(f"清理了 {len(expired_contexts)} 个过期上下文")

    def get_active_streams(self) -> List[str]:
        """获取活跃流列表

        Returns:
            List[str]: 活跃流ID列表
        """
        return list(self.stream_contexts.keys())


# 全局上下文管理器实例
context_manager = StreamContextManager()