"""
消息管理模块
管理每个聊天流的上下文信息，包含历史记录和未读消息，定期检查并处理新消息
"""

import asyncio
import random
import time
from typing import TYPE_CHECKING, Any

from src.chat.chatter_manager import ChatterManager
from src.chat.message_receive.chat_stream import ChatStream
from src.chat.planner_actions.action_manager import ChatterActionManager
from src.common.data_models.database_data_model import DatabaseMessages
from src.common.data_models.message_manager_data_model import MessageManagerStats, StreamStats
from src.common.logger import get_logger
from src.config.config import global_config
from src.plugin_system.apis.chat_api import get_chat_manager

from .distribution_manager import stream_loop_manager
from .sleep_manager.sleep_manager import SleepManager
from .sleep_manager.wakeup_manager import WakeUpManager

if TYPE_CHECKING:
    pass

logger = get_logger("message_manager")


class MessageManager:
    """消息管理器"""

    def __init__(self, check_interval: float = 5.0):
        self.check_interval = check_interval  # 检查间隔（秒）
        self.is_running = False
        self.manager_task: asyncio.Task | None = None

        # 统计信息
        self.stats = MessageManagerStats()

        # 初始化chatter manager
        self.action_manager = ChatterActionManager()
        self.chatter_manager = ChatterManager(self.action_manager)

        # 初始化睡眠和唤醒管理器
        self.sleep_manager = SleepManager()
        self.wakeup_manager = WakeUpManager(self.sleep_manager)

        # 不再需要全局上下文管理器，直接通过 ChatManager 访问各个 ChatStream 的 context_manager

    async def start(self):
        """启动消息管理器"""
        if self.is_running:
            logger.warning("消息管理器已经在运行")
            return

        self.is_running = True

        # 启动批量数据库写入器
        try:
            from src.chat.message_manager.batch_database_writer import init_batch_writer
            await init_batch_writer()
        except Exception as e:
            logger.error(f"启动批量数据库写入器失败: {e}")

        # 启动流缓存管理器
        try:
            from src.chat.message_manager.stream_cache_manager import init_stream_cache_manager
            await init_stream_cache_manager()
        except Exception as e:
            logger.error(f"启动流缓存管理器失败: {e}")

        # 启动自适应流管理器
        try:
            from src.chat.message_manager.adaptive_stream_manager import init_adaptive_stream_manager
            await init_adaptive_stream_manager()
            logger.info("🎯 自适应流管理器已启动")
        except Exception as e:
            logger.error(f"启动自适应流管理器失败: {e}")

        # 启动睡眠和唤醒管理器
        await self.wakeup_manager.start()

        # 启动流循环管理器并设置chatter_manager
        await stream_loop_manager.start()
        stream_loop_manager.set_chatter_manager(self.chatter_manager)

        logger.info("🚀 消息管理器已启动 | 流循环管理器已启动")

    async def stop(self):
        """停止消息管理器"""
        if not self.is_running:
            return

        self.is_running = False

        # 停止批量数据库写入器
        try:
            from src.chat.message_manager.batch_database_writer import shutdown_batch_writer
            await shutdown_batch_writer()
            logger.info("📦 批量数据库写入器已停止")
        except Exception as e:
            logger.error(f"停止批量数据库写入器失败: {e}")

        # 停止流缓存管理器
        try:
            from src.chat.message_manager.stream_cache_manager import shutdown_stream_cache_manager
            await shutdown_stream_cache_manager()
            logger.info("🗄️ 流缓存管理器已停止")
        except Exception as e:
            logger.error(f"停止流缓存管理器失败: {e}")

        # 停止自适应流管理器
        try:
            from src.chat.message_manager.adaptive_stream_manager import shutdown_adaptive_stream_manager
            await shutdown_adaptive_stream_manager()
            logger.info("🎯 自适应流管理器已停止")
        except Exception as e:
            logger.error(f"停止自适应流管理器失败: {e}")

        # 停止睡眠和唤醒管理器
        await self.wakeup_manager.stop()

        # 停止流循环管理器
        await stream_loop_manager.stop()

        logger.info("🛑 消息管理器已停止 | 流循环管理器已停止")

    async def add_message(self, stream_id: str, message: DatabaseMessages):
        """添加消息到指定聊天流"""
        try:
            chat_manager = get_chat_manager()
            chat_stream = await chat_manager.get_stream(stream_id)
            if not chat_stream:
                logger.warning(f"MessageManager.add_message: 聊天流 {stream_id} 不存在")
                return
            await self._check_and_handle_interruption(chat_stream)
            await chat_stream.context_manager.add_message(message)

        except Exception as e:
            logger.error(f"添加消息到聊天流 {stream_id} 时发生错误: {e}")

    async def update_message(
        self,
        stream_id: str,
        message_id: str,
        interest_value: float | None = None,
        actions: list | None = None,
        should_reply: bool | None = None,
    ):
        """更新消息信息"""
        try:
            chat_manager = get_chat_manager()
            chat_stream = await chat_manager.get_stream(stream_id)
            if not chat_stream:
                logger.warning(f"MessageManager.update_message: 聊天流 {stream_id} 不存在")
                return
            updates = {}
            if interest_value is not None:
                updates["interest_value"] = interest_value
            if actions is not None:
                updates["actions"] = actions
            if should_reply is not None:
                updates["should_reply"] = should_reply
            if updates:
                success = await chat_stream.context_manager.update_message(message_id, updates)
                if success:
                    logger.debug(f"更新消息 {message_id} 成功")
                else:
                    logger.warning(f"更新消息 {message_id} 失败")
        except Exception as e:
            logger.error(f"更新消息 {message_id} 时发生错误: {e}")

    async def bulk_update_messages(self, stream_id: str, updates: list[dict[str, Any]]) -> int:
        """批量更新消息信息，降低更新频率"""
        if not updates:
            return 0

        try:
            chat_manager = get_chat_manager()
            chat_stream = await chat_manager.get_stream(stream_id)
            if not chat_stream:
                logger.warning(f"MessageManager.bulk_update_messages: 聊天流 {stream_id} 不存在")
                return 0

            updated_count = 0
            for item in updates:
                message_id = item.get("message_id")
                if not message_id:
                    continue

                payload = {key: value for key, value in item.items() if key != "message_id" and value is not None}

                if not payload:
                    continue

                success = await chat_stream.context_manager.update_message(message_id, payload)
                if success:
                    updated_count += 1

            if updated_count:
                logger.debug(f"批量更新消息 {updated_count} 条 (stream={stream_id})")
            return updated_count
        except Exception as e:
            logger.error(f"批量更新聊天流 {stream_id} 消息失败: {e}")
            return 0

    async def add_action(self, stream_id: str, message_id: str, action: str):
        """添加动作到消息"""
        try:
            chat_manager = get_chat_manager()
            chat_stream = await chat_manager.get_stream(stream_id)
            if not chat_stream:
                logger.warning(f"MessageManager.add_action: 聊天流 {stream_id} 不存在")
                return
            success = await chat_stream.context_manager.update_message(message_id, {"actions": [action]})
            if success:
                logger.debug(f"为消息 {message_id} 添加动作 {action} 成功")
            else:
                logger.warning(f"为消息 {message_id} 添加动作 {action} 失败")
        except Exception as e:
            logger.error(f"为消息 {message_id} 添加动作时发生错误: {e}")

    async def deactivate_stream(self, stream_id: str):
        """停用聊天流"""
        try:
            # 通过 ChatManager 获取 ChatStream
            chat_manager = get_chat_manager()
            chat_stream = await chat_manager.get_stream(stream_id)
            if not chat_stream:
                logger.warning(f"停用流失败: 聊天流 {stream_id} 不存在")
                return

            context = chat_stream.stream_context
            context.is_active = False

            # 取消处理任务
            if hasattr(context, "processing_task") and context.processing_task and not context.processing_task.done():
                context.processing_task.cancel()

            logger.info(f"停用聊天流: {stream_id}")

        except Exception as e:
            logger.error(f"停用聊天流 {stream_id} 时发生错误: {e}")

    async def activate_stream(self, stream_id: str):
        """激活聊天流"""
        try:
            # 通过 ChatManager 获取 ChatStream
            chat_manager = get_chat_manager()
            chat_stream = await chat_manager.get_stream(stream_id)
            if not chat_stream:
                logger.warning(f"激活流失败: 聊天流 {stream_id} 不存在")
                return

            context = chat_stream.stream_context
            context.is_active = True
            logger.info(f"激活聊天流: {stream_id}")

        except Exception as e:
            logger.error(f"激活聊天流 {stream_id} 时发生错误: {e}")

    async def get_stream_stats(self, stream_id: str) -> StreamStats | None:
        """获取聊天流统计"""
        try:
            # 通过 ChatManager 获取 ChatStream
            chat_manager = get_chat_manager()
            chat_stream = await chat_manager.get_stream(stream_id)
            if not chat_stream:
                return None

            context = chat_stream.stream_context
            unread_count = len(chat_stream.context_manager.get_unread_messages())

            return StreamStats(
                stream_id=stream_id,
                is_active=context.is_active,
                unread_count=unread_count,
                history_count=len(context.history_messages),
                last_check_time=context.last_check_time,
                has_active_task=bool(
                    hasattr(context, "processing_task")
                    and context.processing_task
                    and not context.processing_task.done()
                ),
            )

        except Exception as e:
            logger.error(f"获取聊天流 {stream_id} 统计时发生错误: {e}")
            return None

    def get_manager_stats(self) -> dict[str, Any]:
        """获取管理器统计"""
        return {
            "total_streams": self.stats.total_streams,
            "active_streams": self.stats.active_streams,
            "total_unread_messages": self.stats.total_unread_messages,
            "total_processed_messages": self.stats.total_processed_messages,
            "uptime": self.stats.uptime,
            "start_time": self.stats.start_time,
        }

    async def cleanup_inactive_streams(self, max_inactive_hours: int = 24):
        """清理不活跃的聊天流"""
        try:
            chat_manager = get_chat_manager()
            current_time = time.time()
            max_inactive_seconds = max_inactive_hours * 3600
            inactive_streams = []
            for stream_id, chat_stream in chat_manager.streams.items():
                if current_time - chat_stream.last_active_time > max_inactive_seconds:
                    inactive_streams.append(stream_id)
            for stream_id in inactive_streams:
                try:
                    await chat_stream.context_manager.clear_context()
                    del chat_manager.streams[stream_id]
                    logger.info(f"清理不活跃聊天流: {stream_id}")
                except Exception as e:
                    logger.error(f"清理聊天流 {stream_id} 失败: {e}")
            if inactive_streams:
                logger.info(f"已清理 {len(inactive_streams)} 个不活跃聊天流")
            else:
                logger.debug("没有需要清理的不活跃聊天流")
        except Exception as e:
            logger.error(f"清理不活跃聊天流时发生错误: {e}")

    async def _check_and_handle_interruption(self, chat_stream: ChatStream | None = None):
        """检查并处理消息打断"""
        if not global_config.chat.interruption_enabled or not chat_stream:
            return

        # 从 chatter_manager 检查是否有正在进行的处理任务
        processing_task = self.chatter_manager.get_processing_task(chat_stream.stream_id)

        if processing_task and not processing_task.done():
            # 计算打断概率
            interruption_probability = chat_stream.context_manager.context.calculate_interruption_probability(
                global_config.chat.interruption_max_limit, global_config.chat.interruption_probability_factor
            )

            # 检查是否已达到最大打断次数
            if chat_stream.context_manager.context.interruption_count >= global_config.chat.interruption_max_limit:
                logger.debug(
                    f"聊天流 {chat_stream.stream_id} 已达到最大打断次数 {chat_stream.context_manager.context.interruption_count}/{global_config.chat.interruption_max_limit}，跳过打断检查"
                )
                return

            # 根据概率决定是否打断
            if random.random() < interruption_probability:
                logger.info(f"聊天流 {chat_stream.stream_id} 触发消息打断，打断概率: {interruption_probability:.2f}")

                # 取消现有任务
                processing_task.cancel()
                try:
                    await processing_task
                except asyncio.CancelledError:
                    logger.debug(f"消息打断成功取消任务: {chat_stream.stream_id}")

                # 增加打断计数并应用afc阈值降低
                await chat_stream.context_manager.context.increment_interruption_count()
                chat_stream.context_manager.context.apply_interruption_afc_reduction(
                    global_config.chat.interruption_afc_reduction
                )

                # 检查是否已达到最大次数
                if chat_stream.context_manager.context.interruption_count >= global_config.chat.interruption_max_limit:
                    logger.warning(
                        f"聊天流 {chat_stream.stream_id} 已达到最大打断次数 {chat_stream.context_manager.context.interruption_count}/{global_config.chat.interruption_max_limit}，后续消息将不再打断"
                    )
                else:
                    logger.info(
                        f"聊天流 {chat_stream.stream_id} 已打断，当前打断次数: {chat_stream.context_manager.context.interruption_count}/{global_config.chat.interruption_max_limit}, afc阈值调整: {chat_stream.context_manager.context.get_afc_threshold_adjustment()}"
                    )
            else:
                logger.debug(f"聊天流 {chat_stream.stream_id} 未触发打断，打断概率: {interruption_probability:.2f}")

    async def clear_all_unread_messages(self, stream_id: str):
        """清除指定上下文中的所有未读消息，在消息处理完成后调用"""
        try:
            # 通过 ChatManager 获取 ChatStream
            chat_manager = get_chat_manager()
            chat_stream = await chat_manager.get_stream(stream_id)
            if not chat_stream:
                logger.warning(f"清除消息失败: 聊天流 {stream_id} 不存在")
                return

            # 获取未读消息
            unread_messages = chat_stream.context_manager.get_unread_messages()
            if not unread_messages:
                return

            logger.warning(f"正在清除 {len(unread_messages)} 条未读消息")

            # 将所有未读消息标记为已读
            message_ids = [msg.message_id for msg in unread_messages]
            success = chat_stream.context_manager.mark_messages_as_read(message_ids)

            if success:
                self.stats.total_processed_messages += len(unread_messages)
                logger.debug(f"强制清除 {len(unread_messages)} 条消息，标记为已读")
            else:
                logger.error("标记未读消息为已读失败")

        except Exception as e:
            logger.error(f"清除未读消息时发生错误: {e}")

    async def clear_stream_unread_messages(self, stream_id: str):
        """清除指定聊天流的所有未读消息"""
        try:
            chat_manager = get_chat_manager()
            chat_stream = await chat_manager.get_stream(stream_id)
            if not chat_stream:
                logger.warning(f"clear_stream_unread_messages: 聊天流 {stream_id} 不存在")
                return

            context = chat_stream.context_manager.context
            if hasattr(context, "unread_messages") and context.unread_messages:
                logger.debug(f"正在为流 {stream_id} 清除 {len(context.unread_messages)} 条未读消息")
                context.unread_messages.clear()
            else:
                logger.debug(f"流 {stream_id} 没有需要清除的未读消息")

        except Exception as e:
            logger.error(f"清除流 {stream_id} 的未读消息时发生错误: {e}")


# 创建全局消息管理器实例
message_manager = MessageManager()
