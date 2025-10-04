"""
流循环管理器
为每个聊天流创建独立的无限循环任务，主动轮询处理消息
"""

import asyncio
import time
from typing import Any

from src.chat.chatter_manager import ChatterManager
from src.chat.energy_system import energy_manager
from src.common.data_models.message_manager_data_model import StreamContext
from src.common.logger import get_logger
from src.config.config import global_config
from src.plugin_system.apis.chat_api import get_chat_manager

logger = get_logger("stream_loop_manager")


class StreamLoopManager:
    """流循环管理器 - 每个流一个独立的无限循环任务"""

    def __init__(self, max_concurrent_streams: int | None = None):
        # 流循环任务管理
        self.stream_loops: dict[str, asyncio.Task] = {}
        # 跟踪流使用的管理器类型
        self.stream_management_type: dict[str, str] = {}  # stream_id -> "adaptive" or "fallback"

        # 统计信息
        self.stats: dict[str, Any] = {
            "active_streams": 0,
            "total_loops": 0,
            "total_process_cycles": 0,
            "total_failures": 0,
            "start_time": time.time(),
        }

        # 配置参数
        self.max_concurrent_streams = max_concurrent_streams or global_config.chat.max_concurrent_distributions

        # 强制分发策略
        self.force_dispatch_unread_threshold: int | None = getattr(
            global_config.chat, "force_dispatch_unread_threshold", 20
        )
        self.force_dispatch_min_interval: float = getattr(global_config.chat, "force_dispatch_min_interval", 0.1)

        # Chatter管理器
        self.chatter_manager: ChatterManager | None = None

        # 状态控制
        self.is_running = False

        logger.info(f"流循环管理器初始化完成 (最大并发流数: {self.max_concurrent_streams})")

    async def start(self) -> None:
        """启动流循环管理器"""
        if self.is_running:
            logger.warning("流循环管理器已经在运行")
            return

        self.is_running = True

    async def stop(self) -> None:
        """停止流循环管理器"""
        if not self.is_running:
            return

        self.is_running = False

        # 取消所有流循环
        try:
            # 创建任务列表以便并发取消
            cancel_tasks = []
            for stream_id, task in list(self.stream_loops.items()):
                if not task.done():
                    task.cancel()
                    cancel_tasks.append((stream_id, task))

            # 并发等待所有任务取消
            if cancel_tasks:
                logger.info(f"正在取消 {len(cancel_tasks)} 个流循环任务...")
                await asyncio.gather(
                    *[self._wait_for_task_cancel(stream_id, task) for stream_id, task in cancel_tasks],
                    return_exceptions=True
                )

            # 取消所有活跃的 chatter 处理任务
            if self.chatter_manager:
                try:
                    cancelled_count = await self.chatter_manager.cancel_all_processing_tasks()
                    logger.info(f"已取消 {cancelled_count} 个活跃的 chatter 处理任务")
                except Exception as e:
                    logger.error(f"取消 chatter 处理任务时出错: {e}")

            self.stream_loops.clear()
            logger.info("所有流循环已清理")
        except Exception as e:
            logger.error(f"停止管理器时出错: {e}")

        logger.info("流循环管理器已停止")

    async def start_stream_loop(self, stream_id: str, force: bool = False) -> bool:
        """启动指定流的循环任务 - 优化版本使用自适应管理器

        Args:
            stream_id: 流ID
            force: 是否强制启动

        Returns:
            bool: 是否成功启动
        """
        # 快速路径：如果流已存在，无需处理
        if stream_id in self.stream_loops:
            logger.debug(f"流 {stream_id} 循环已在运行")
            return True

        # 使用自适应流管理器获取槽位
        use_adaptive = False
        try:
            from src.chat.message_manager.adaptive_stream_manager import get_adaptive_stream_manager, StreamPriority
            adaptive_manager = get_adaptive_stream_manager()

            if adaptive_manager.is_running:
                # 确定流优先级
                priority = self._determine_stream_priority(stream_id)

                # 获取处理槽位
                slot_acquired = await adaptive_manager.acquire_stream_slot(
                    stream_id=stream_id,
                    priority=priority,
                    force=force
                )

                if slot_acquired:
                    use_adaptive = True
                    logger.debug(f"成功获取流处理槽位: {stream_id} (优先级: {priority.name})")
                else:
                    logger.debug(f"自适应管理器拒绝槽位请求: {stream_id}，尝试回退方案")
            else:
                logger.debug(f"自适应管理器未运行，使用原始方法")

        except Exception as e:
            logger.debug(f"自适应管理器获取槽位失败，使用原始方法: {e}")

        # 如果自适应管理器失败或未运行，使用回退方案
        if not use_adaptive:
            if not await self._fallback_acquire_slot(stream_id, force):
                logger.debug(f"回退方案也失败: {stream_id}")
                return False

        # 创建流循环任务
        try:
            loop_task = asyncio.create_task(
                self._stream_loop_worker(stream_id),
                name=f"stream_loop_{stream_id}"
            )
            self.stream_loops[stream_id] = loop_task
            # 记录管理器类型
            self.stream_management_type[stream_id] = "adaptive" if use_adaptive else "fallback"

            # 更新统计信息
            self.stats["active_streams"] += 1
            self.stats["total_loops"] += 1

            logger.info(f"启动流循环任务: {stream_id} (管理器: {'adaptive' if use_adaptive else 'fallback'})")
            return True

        except Exception as e:
            logger.error(f"启动流循环任务失败 {stream_id}: {e}")
            # 释放槽位
            if use_adaptive:
                try:
                    from src.chat.message_manager.adaptive_stream_manager import get_adaptive_stream_manager
                    adaptive_manager = get_adaptive_stream_manager()
                    adaptive_manager.release_stream_slot(stream_id)
                except:
                    pass
            return False

    async def _fallback_acquire_slot(self, stream_id: str, force: bool) -> bool:
        """回退方案：获取槽位（原始方法）"""
        # 判断是否需要强制分发
        should_force = force or await self._should_force_dispatch_for_stream(stream_id)

        # 检查是否超过最大并发限制
        current_streams = len(self.stream_loops)
        if current_streams >= self.max_concurrent_streams and not should_force:
            logger.warning(
                f"超过最大并发流数限制({current_streams}/{self.max_concurrent_streams})，无法启动流 {stream_id}"
            )
            return False

        # 处理强制分发情况
        if should_force and current_streams >= self.max_concurrent_streams:
            logger.warning(
                f"流 {stream_id} 未读消息积压严重(>{self.force_dispatch_unread_threshold})，突破并发限制强制启动分发 (当前: {current_streams}/{self.max_concurrent_streams})"
            )
            # 检查是否有现有的分发循环，如果有则先移除
            if stream_id in self.stream_loops:
                logger.info(f"发现现有流循环 {stream_id}，将先移除再重新创建")
                existing_task = self.stream_loops[stream_id]
                if not existing_task.done():
                    existing_task.cancel()
                    # 创建异步任务来等待取消完成，并添加异常处理
                    cancel_task = asyncio.create_task(
                        self._wait_for_task_cancel(stream_id, existing_task),
                        name=f"cancel_existing_loop_{stream_id}"
                    )
                    # 为取消任务添加异常处理，避免孤儿任务
                    cancel_task.add_done_callback(
                        lambda task: logger.debug(f"取消任务完成: {stream_id}") if not task.exception()
                        else logger.error(f"取消任务异常: {stream_id} - {task.exception()}")
                    )
                # 从字典中移除
                del self.stream_loops[stream_id]
                current_streams -= 1  # 更新当前流数量

        return True

    def _determine_stream_priority(self, stream_id: str) -> "StreamPriority":
        """确定流优先级"""
        try:
            from src.chat.message_manager.adaptive_stream_manager import StreamPriority

            # 这里可以基于流的历史数据、用户身份等确定优先级
            # 简化版本：基于流ID的哈希值分配优先级
            hash_value = hash(stream_id) % 10

            if hash_value >= 8:  # 20% 高优先级
                return StreamPriority.HIGH
            elif hash_value >= 5:  # 30% 中等优先级
                return StreamPriority.NORMAL
            else:  # 50% 低优先级
                return StreamPriority.LOW

        except Exception:
            from src.chat.message_manager.adaptive_stream_manager import StreamPriority
            return StreamPriority.NORMAL

        # 创建流循环任务
        try:
            task = asyncio.create_task(
                self._stream_loop(stream_id),
                name=f"stream_loop_{stream_id}"  # 为任务添加名称，便于调试
            )
            self.stream_loops[stream_id] = task
            self.stats["total_loops"] += 1

            logger.info(f"启动流循环: {stream_id} (当前总数: {len(self.stream_loops)})")
            return True
        except Exception as e:
            logger.error(f"创建流循环任务失败: {stream_id} - {e}")
            return False

    async def stop_stream_loop(self, stream_id: str) -> bool:
        """停止指定流的循环任务

        Args:
            stream_id: 流ID

        Returns:
            bool: 是否成功停止
        """
        # 快速路径：如果流不存在，无需处理
        if stream_id not in self.stream_loops:
            logger.debug(f"流 {stream_id} 循环不存在，无需停止")
            return False

        task = self.stream_loops[stream_id]
        if not task.done():
            task.cancel()
            try:
                # 设置取消超时，避免无限等待
                await asyncio.wait_for(task, timeout=5.0)
            except asyncio.CancelledError:
                logger.debug(f"流循环任务已取消: {stream_id}")
            except asyncio.TimeoutError:
                logger.warning(f"流循环任务取消超时: {stream_id}")
            except Exception as e:
                logger.error(f"等待流循环任务结束时出错: {stream_id} - {e}")

        # 取消关联的 chatter 处理任务
        if self.chatter_manager:
            cancelled = self.chatter_manager.cancel_processing_task(stream_id)
            if cancelled:
                logger.info(f"已取消关联的 chatter 处理任务: {stream_id}")

        del self.stream_loops[stream_id]
        logger.info(f"停止流循环: {stream_id} (剩余: {len(self.stream_loops)})")
        return True

    async def _stream_loop_worker(self, stream_id: str) -> None:
        """单个流的工作循环 - 优化版本

        Args:
            stream_id: 流ID
        """
        logger.info(f"流循环工作器启动: {stream_id}")

        try:
            while self.is_running:
                try:
                    # 1. 获取流上下文
                    context = await self._get_stream_context(stream_id)
                    if not context:
                        logger.warning(f"无法获取流上下文: {stream_id}")
                        await asyncio.sleep(10.0)
                        continue

                    # 2. 检查是否有消息需要处理
                    unread_count = self._get_unread_count(context)
                    force_dispatch = self._needs_force_dispatch_for_context(context, unread_count)

                    # 3. 更新自适应管理器指标
                    try:
                        from src.chat.message_manager.adaptive_stream_manager import get_adaptive_stream_manager
                        adaptive_manager = get_adaptive_stream_manager()
                        adaptive_manager.update_stream_metrics(
                            stream_id,
                            message_rate=unread_count / 5.0 if unread_count > 0 else 0.0,  # 简化计算
                            last_activity=time.time()
                        )
                    except Exception as e:
                        logger.debug(f"更新流指标失败: {e}")

                    has_messages = force_dispatch or await self._has_messages_to_process(context)

                    if has_messages:
                        if force_dispatch:
                            logger.info("流 %s 未读消息 %d 条，触发强制分发", stream_id, unread_count)
                        # 3. 激活chatter处理
                        success = await self._process_stream_messages(stream_id, context)

                        # 更新统计
                        self.stats["total_process_cycles"] += 1
                        if success:
                            logger.debug(f"流处理成功: {stream_id}")
                        else:
                            self.stats["total_failures"] += 1
                            logger.warning(f"流处理失败: {stream_id}")

                    # 4. 计算下次检查间隔
                    interval = await self._calculate_interval(stream_id, has_messages)

                    if has_messages:
                        updated_unread_count = self._get_unread_count(context)
                        if self._needs_force_dispatch_for_context(context, updated_unread_count):
                            interval = min(interval, max(self.force_dispatch_min_interval, 0.0))
                            logger.debug(
                                "流 %s 未读消息仍有 %d 条，使用加速分发间隔 %.2fs",
                                stream_id,
                                updated_unread_count,
                                interval,
                            )

                    # 5. sleep等待下次检查
                    logger.info(f"流 {stream_id} 等待 {interval:.2f}s")
                    await asyncio.sleep(interval)

                except asyncio.CancelledError:
                    logger.info(f"流循环被取消: {stream_id}")
                    if self.chatter_manager:
                        # 使用 ChatterManager 的新方法取消处理任务
                        cancelled = self.chatter_manager.cancel_processing_task(stream_id)
                        if cancelled:
                            logger.info(f"成功取消 chatter 处理任务: {stream_id}")
                        else:
                            logger.debug(f"没有需要取消的 chatter 处理任务: {stream_id}")
                    break
                except Exception as e:
                    logger.error(f"流循环出错 {stream_id}: {e}", exc_info=True)
                    self.stats["total_failures"] += 1
                    await asyncio.sleep(5.0)  # 错误时等待5秒再重试

        finally:
            # 清理循环标记
            if stream_id in self.stream_loops:
                del self.stream_loops[stream_id]
                logger.debug(f"清理流循环标记: {stream_id}")

            # 根据管理器类型释放相应的槽位
            management_type = self.stream_management_type.get(stream_id, "fallback")
            if management_type == "adaptive":
                # 释放自适应管理器的槽位
                try:
                    from src.chat.message_manager.adaptive_stream_manager import get_adaptive_stream_manager
                    adaptive_manager = get_adaptive_stream_manager()
                    adaptive_manager.release_stream_slot(stream_id)
                    logger.debug(f"释放自适应流处理槽位: {stream_id}")
                except Exception as e:
                    logger.debug(f"释放自适应流处理槽位失败: {e}")
            else:
                logger.debug(f"流 {stream_id} 使用回退方案，无需释放自适应槽位")

            # 清理管理器类型记录
            if stream_id in self.stream_management_type:
                del self.stream_management_type[stream_id]

            logger.info(f"流循环结束: {stream_id}")

    async def _get_stream_context(self, stream_id: str) -> Any | None:
        """获取流上下文

        Args:
            stream_id: 流ID

        Returns:
            Optional[Any]: 流上下文，如果不存在返回None
        """
        try:
            chat_manager = get_chat_manager()
            chat_stream = await chat_manager.get_stream(stream_id)
            if chat_stream:
                return chat_stream.context_manager.context
            return None
        except Exception as e:
            logger.error(f"获取流上下文失败 {stream_id}: {e}")
            return None

    async def _has_messages_to_process(self, context: Any) -> bool:
        """检查是否有消息需要处理

        Args:
            context: 流上下文

        Returns:
            bool: 是否有未读消息
        """
        try:
            # 检查是否有未读消息
            if hasattr(context, "unread_messages") and context.unread_messages:
                return True

            # 检查其他需要处理的条件
            if hasattr(context, "has_pending_messages") and context.has_pending_messages:
                return True

            return False
        except Exception as e:
            logger.error(f"检查消息状态失败: {e}")
            return False

    async def _process_stream_messages(self, stream_id: str, context: StreamContext) -> bool:
        """处理流消息

        Args:
            stream_id: 流ID
            context: 流上下文

        Returns:
            bool: 是否处理成功
        """
        if not self.chatter_manager:
            logger.warning(f"Chatter管理器未设置: {stream_id}")
            return False

        try:
            start_time = time.time()

            # 直接调用chatter_manager处理流上下文
            task = asyncio.create_task(self.chatter_manager.process_stream_context(stream_id, context))
            self.chatter_manager.set_processing_task(stream_id, task)
            results = await task
            success = results.get("success", False)

            if success:
                await self._refresh_focus_energy(stream_id)
                process_time = time.time() - start_time
                logger.debug(f"流处理成功: {stream_id} (耗时: {process_time:.2f}s)")
            else:
                logger.warning(f"流处理失败: {stream_id} - {results.get('error_message', '未知错误')}")

            return success

        except Exception as e:
            logger.error(f"流处理异常: {stream_id} - {e}", exc_info=True)
            return False

    async def _calculate_interval(self, stream_id: str, has_messages: bool) -> float:
        """计算下次检查间隔

        Args:
            stream_id: 流ID
            has_messages: 本次是否有消息处理

        Returns:
            float: 间隔时间（秒）
        """
        # 基础间隔
        base_interval = getattr(global_config.chat, "distribution_interval", 5.0)

        # 如果没有消息，使用更长的间隔
        if not has_messages:
            return base_interval * 2.0  # 无消息时间隔加倍

        # 尝试使用能量管理器计算间隔
        try:
            # 获取当前focus_energy
            focus_energy = energy_manager.energy_cache.get(stream_id, (0.5, 0))[0]

            # 使用能量管理器计算间隔
            interval = energy_manager.get_distribution_interval(focus_energy)

            logger.debug(f"流 {stream_id} 动态间隔: {interval:.2f}s (能量: {focus_energy:.3f})")
            return interval

        except Exception as e:
            logger.debug(f"流 {stream_id} 使用默认间隔: {base_interval:.2f}s ({e})")
            return base_interval

    def get_queue_status(self) -> dict[str, Any]:
        """获取队列状态

        Returns:
            Dict[str, Any]: 队列状态信息
        """
        current_time = time.time()
        uptime = current_time - self.stats["start_time"] if self.is_running else 0

        return {
            "active_streams": len(self.stream_loops),
            "total_loops": self.stats["total_loops"],
            "max_concurrent": self.max_concurrent_streams,
            "is_running": self.is_running,
            "uptime": uptime,
            "total_process_cycles": self.stats["total_process_cycles"],
            "total_failures": self.stats["total_failures"],
            "stats": self.stats.copy(),
        }

    def set_chatter_manager(self, chatter_manager: ChatterManager) -> None:
        """设置chatter管理器

        Args:
            chatter_manager: chatter管理器实例
        """
        self.chatter_manager = chatter_manager
        logger.info(f"设置chatter管理器: {chatter_manager.__class__.__name__}")

    async def _should_force_dispatch_for_stream(self, stream_id: str) -> bool:
        if not self.force_dispatch_unread_threshold or self.force_dispatch_unread_threshold <= 0:
            return False

        try:
            chat_manager = get_chat_manager()
            chat_stream = await chat_manager.get_stream(stream_id)
            if not chat_stream:
                return False

            unread = getattr(chat_stream.context_manager.context, "unread_messages", [])
            return len(unread) > self.force_dispatch_unread_threshold
        except Exception as e:
            logger.debug(f"检查流 {stream_id} 是否需要强制分发失败: {e}")
            return False

    def _get_unread_count(self, context: Any) -> int:
        try:
            unread_messages = getattr(context, "unread_messages", None)
            if unread_messages is None:
                return 0
            return len(unread_messages)
        except Exception:
            return 0

    def _needs_force_dispatch_for_context(self, context: Any, unread_count: int | None = None) -> bool:
        if not self.force_dispatch_unread_threshold or self.force_dispatch_unread_threshold <= 0:
            return False

        count = unread_count if unread_count is not None else self._get_unread_count(context)
        return count > self.force_dispatch_unread_threshold

    def get_performance_summary(self) -> dict[str, Any]:
        """获取性能摘要

        Returns:
            Dict[str, Any]: 性能摘要
        """
        current_time = time.time()
        uptime = current_time - self.stats["start_time"]

        # 计算吞吐量
        throughput = self.stats["total_process_cycles"] / max(1, uptime / 3600)  # 每小时处理次数

        return {
            "uptime_hours": uptime / 3600,
            "active_streams": len(self.stream_loops),
            "total_process_cycles": self.stats["total_process_cycles"],
            "total_failures": self.stats["total_failures"],
            "throughput_per_hour": throughput,
            "max_concurrent_streams": self.max_concurrent_streams,
        }

    async def _refresh_focus_energy(self, stream_id: str) -> None:
        """分发完成后基于历史消息刷新能量值"""
        try:
            chat_manager = get_chat_manager()
            chat_stream = await chat_manager.get_stream(stream_id)
            if not chat_stream:
                logger.debug(f"刷新能量时未找到聊天流: {stream_id}")
                return

            await chat_stream.context_manager.refresh_focus_energy_from_history()
            logger.debug(f"已刷新聊天流 {stream_id} 的聚焦能量")
        except Exception as e:
            logger.warning(f"刷新聊天流 {stream_id} 能量失败: {e}")

    async def _wait_for_task_cancel(self, stream_id: str, task: asyncio.Task) -> None:
        """等待任务取消完成，带有超时控制
        
        Args:
            stream_id: 流ID
            task: 要等待取消的任务
        """
        try:
            await asyncio.wait_for(task, timeout=5.0)
            logger.debug(f"流循环任务已正常结束: {stream_id}")
        except asyncio.CancelledError:
            logger.debug(f"流循环任务已取消: {stream_id}")
        except asyncio.TimeoutError:
            logger.warning(f"流循环任务取消超时: {stream_id}")
        except Exception as e:
            logger.error(f"等待流循环任务结束时出错: {stream_id} - {e}")

    async def _force_dispatch_stream(self, stream_id: str) -> None:
        """强制分发流处理
        
        当流的未读消息超过阈值时，强制触发分发处理
        这个方法主要用于突破并发限制时的紧急处理
        
        注意：此方法目前未被使用，相关功能已集成到 start_stream_loop 方法中
        
        Args:
            stream_id: 流ID
        """
        logger.info(f"强制分发流处理: {stream_id}")

        try:
            # 检查是否有现有的分发循环
            if stream_id in self.stream_loops:
                logger.info(f"发现现有流循环 {stream_id}，将先移除再重新创建")
                existing_task = self.stream_loops[stream_id]
                if not existing_task.done():
                    existing_task.cancel()
                    # 创建异步任务来等待取消完成，并添加异常处理
                    cancel_task = asyncio.create_task(
                        self._wait_for_task_cancel(stream_id, existing_task),
                        name=f"cancel_existing_loop_{stream_id}"
                    )
                    # 为取消任务添加异常处理，避免孤儿任务
                    cancel_task.add_done_callback(
                        lambda task: logger.debug(f"取消任务完成: {stream_id}") if not task.exception()
                        else logger.error(f"取消任务异常: {stream_id} - {task.exception()}")
                    )
                # 从字典中移除
                del self.stream_loops[stream_id]

            # 获取聊天管理器和流
            chat_manager = get_chat_manager()
            chat_stream = await chat_manager.get_stream(stream_id)
            if not chat_stream:
                logger.warning(f"强制分发时未找到流: {stream_id}")
                return

            # 获取流上下文
            context = chat_stream.context_manager.context
            if not context:
                logger.warning(f"强制分发时未找到流上下文: {stream_id}")
                return

            # 检查未读消息数量
            unread_count = self._get_unread_count(context)
            logger.info(f"流 {stream_id} 当前未读消息数: {unread_count}")

            # 创建新的流循环任务
            new_task = asyncio.create_task(
                self._stream_loop(stream_id),
                name=f"force_stream_loop_{stream_id}"
            )
            self.stream_loops[stream_id] = new_task
            self.stats["total_loops"] += 1

            logger.info(f"已创建强制分发流循环: {stream_id} (当前总数: {len(self.stream_loops)})")

        except Exception as e:
            logger.error(f"强制分发流处理失败 {stream_id}: {e}", exc_info=True)


# 全局流循环管理器实例
stream_loop_manager = StreamLoopManager()
