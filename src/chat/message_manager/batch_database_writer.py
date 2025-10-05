"""
异步批量数据库写入器
优化频繁的数据库写入操作，减少I/O阻塞
"""

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from src.common.database.sqlalchemy_database_api import get_db_session
from src.common.database.sqlalchemy_models import ChatStreams
from src.common.logger import get_logger
from src.config.config import global_config

logger = get_logger("batch_database_writer")


@dataclass
class StreamUpdatePayload:
    """流更新数据结构"""
    stream_id: str
    update_data: dict[str, Any]
    priority: int = 0  # 优先级，数字越大优先级越高
    timestamp: float = field(default_factory=time.time)


class BatchDatabaseWriter:
    """异步批量数据库写入器"""

    def __init__(self, batch_size: int = 50, flush_interval: float = 5.0, max_queue_size: int = 1000):
        """
        初始化批量写入器

        Args:
            batch_size: 批量写入的大小
            flush_interval: 刷新间隔（秒）
            max_queue_size: 最大队列大小
        """
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.max_queue_size = max_queue_size

        # 异步队列
        self.write_queue: asyncio.Queue[StreamUpdatePayload] = asyncio.Queue(maxsize=max_queue_size)

        # 运行状态
        self.is_running = False
        self.writer_task: asyncio.Task | None = None

        # 统计信息
        self.stats = {
            "total_writes": 0,
            "batch_writes": 0,
            "failed_writes": 0,
            "queue_size": 0,
            "avg_batch_size": 0,
            "last_flush_time": 0,
        }

        # 按优先级分类的批次
        self.priority_batches: dict[int, list[StreamUpdatePayload]] = defaultdict(list)

        logger.info(f"批量数据库写入器初始化完成 (batch_size={batch_size}, interval={flush_interval}s)")

    async def start(self):
        """启动批量写入器"""
        if self.is_running:
            logger.warning("批量写入器已经在运行")
            return

        self.is_running = True
        self.writer_task = asyncio.create_task(self._batch_writer_loop(), name="batch_database_writer")

    async def stop(self):
        """停止批量写入器"""
        if not self.is_running:
            return

        self.is_running = False

        # 等待当前批次写入完成
        if self.writer_task and not self.writer_task.done():
            try:
                # 先处理剩余的数据
                await self._flush_all_batches()
                # 取消任务
                self.writer_task.cancel()
                await asyncio.wait_for(self.writer_task, timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning("批量写入器停止超时")
            except Exception as e:
                logger.error(f"停止批量写入器时出错: {e}")

        logger.info("批量数据库写入器已停止")

    async def schedule_stream_update(
        self,
        stream_id: str,
        update_data: dict[str, Any],
        priority: int = 0
    ) -> bool:
        """
        调度流更新

        Args:
            stream_id: 流ID
            update_data: 更新数据
            priority: 优先级

        Returns:
            bool: 是否成功加入队列
        """
        try:
            if not self.is_running:
                logger.warning("批量写入器未运行，直接写入数据库")
                await self._direct_write(stream_id, update_data)
                return True

            # 创建更新载荷
            payload = StreamUpdatePayload(
                stream_id=stream_id,
                update_data=update_data,
                priority=priority
            )

            # 非阻塞方式加入队列
            try:
                self.write_queue.put_nowait(payload)
                self.stats["total_writes"] += 1
                self.stats["queue_size"] = self.write_queue.qsize()
                return True
            except asyncio.QueueFull:
                logger.warning(f"写入队列已满，丢弃低优先级更新: stream_id={stream_id}")
                return False

        except Exception as e:
            logger.error(f"调度流更新失败: {e}")
            return False

    async def _batch_writer_loop(self):
        """批量写入主循环"""
        logger.info("批量写入循环启动")

        while self.is_running:
            try:
                # 等待批次填满或超时
                batch = await self._collect_batch()

                if batch:
                    await self._write_batch(batch)

                # 更新统计信息
                self.stats["queue_size"] = self.write_queue.qsize()

            except asyncio.CancelledError:
                logger.info("批量写入循环被取消")
                break
            except Exception as e:
                logger.error(f"批量写入循环出错: {e}")
                # 短暂等待后继续
                await asyncio.sleep(1.0)

        # 循环结束前处理剩余数据
        await self._flush_all_batches()
        logger.info("批量写入循环结束")

    async def _collect_batch(self) -> list[StreamUpdatePayload]:
        """收集一个批次的数据"""
        batch = []
        deadline = time.time() + self.flush_interval

        while len(batch) < self.batch_size and time.time() < deadline:
            try:
                # 计算剩余等待时间
                remaining_time = max(0, deadline - time.time())
                if remaining_time == 0:
                    break

                payload = await asyncio.wait_for(
                    self.write_queue.get(),
                    timeout=remaining_time
                )
                batch.append(payload)

            except asyncio.TimeoutError:
                break

        return batch

    async def _write_batch(self, batch: list[StreamUpdatePayload]):
        """批量写入数据库"""
        if not batch:
            return

        start_time = time.time()

        try:
            # 按优先级排序
            batch.sort(key=lambda x: (-x.priority, x.timestamp))

            # 合并同一流ID的更新（保留最新的）
            merged_updates = {}
            for payload in batch:
                if payload.stream_id not in merged_updates or payload.timestamp > merged_updates[payload.stream_id].timestamp:
                    merged_updates[payload.stream_id] = payload

            # 批量写入
            await self._batch_write_to_database(list(merged_updates.values()))

            # 更新统计
            self.stats["batch_writes"] += 1
            self.stats["avg_batch_size"] = (
                self.stats["avg_batch_size"] * 0.9 + len(batch) * 0.1
            )  # 滑动平均
            self.stats["last_flush_time"] = start_time

            logger.debug(f"批量写入完成: {len(batch)} 个更新，耗时 {time.time() - start_time:.3f}s")

        except Exception as e:
            self.stats["failed_writes"] += 1
            logger.error(f"批量写入失败: {e}")
            # 降级到单个写入
            for payload in batch:
                try:
                    await self._direct_write(payload.stream_id, payload.update_data)
                except Exception as single_e:
                    logger.error(f"单个写入也失败: {single_e}")

    async def _batch_write_to_database(self, payloads: list[StreamUpdatePayload]):
        """批量写入数据库"""
        async with get_db_session() as session:
            for payload in payloads:
                stream_id = payload.stream_id
                update_data = payload.update_data

                # 根据数据库类型选择不同的插入/更新策略
                if global_config.database.database_type == "sqlite":
                    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
                    stmt = sqlite_insert(ChatStreams).values(
                        stream_id=stream_id, **update_data
                    )
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["stream_id"],
                        set_=update_data
                    )
                elif global_config.database.database_type == "mysql":
                    from sqlalchemy.dialects.mysql import insert as mysql_insert
                    stmt = mysql_insert(ChatStreams).values(
                        stream_id=stream_id, **update_data
                    )
                    stmt = stmt.on_duplicate_key_update(
                        **{key: value for key, value in update_data.items() if key != "stream_id"}
                    )
                else:
                    # 默认使用SQLite语法
                    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
                    stmt = sqlite_insert(ChatStreams).values(
                        stream_id=stream_id, **update_data
                    )
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["stream_id"],
                        set_=update_data
                    )

                await session.execute(stmt)

            await session.commit()

    async def _direct_write(self, stream_id: str, update_data: dict[str, Any]):
        """直接写入数据库（降级方案）"""
        async with get_db_session() as session:
            if global_config.database.database_type == "sqlite":
                from sqlalchemy.dialects.sqlite import insert as sqlite_insert
                stmt = sqlite_insert(ChatStreams).values(
                    stream_id=stream_id, **update_data
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["stream_id"],
                    set_=update_data
                )
            elif global_config.database.database_type == "mysql":
                from sqlalchemy.dialects.mysql import insert as mysql_insert
                stmt = mysql_insert(ChatStreams).values(
                    stream_id=stream_id, **update_data
                )
                stmt = stmt.on_duplicate_key_update(
                    **{key: value for key, value in update_data.items() if key != "stream_id"}
                )
            else:
                from sqlalchemy.dialects.sqlite import insert as sqlite_insert
                stmt = sqlite_insert(ChatStreams).values(
                    stream_id=stream_id, **update_data
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["stream_id"],
                    set_=update_data
                )

            await session.execute(stmt)
            await session.commit()

    async def _flush_all_batches(self):
        """刷新所有剩余批次"""
        # 收集所有剩余数据
        remaining_batch = []
        while not self.write_queue.empty():
            try:
                payload = self.write_queue.get_nowait()
                remaining_batch.append(payload)
            except asyncio.QueueEmpty:
                break

        if remaining_batch:
            await self._write_batch(remaining_batch)

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        stats = self.stats.copy()
        stats["is_running"] = self.is_running
        stats["current_queue_size"] = self.write_queue.qsize() if self.is_running else 0
        return stats


# 全局批量写入器实例
_batch_writer: BatchDatabaseWriter | None = None


def get_batch_writer() -> BatchDatabaseWriter:
    """获取批量写入器实例"""
    global _batch_writer
    if _batch_writer is None:
        _batch_writer = BatchDatabaseWriter()
    return _batch_writer


async def init_batch_writer():
    """初始化批量写入器"""
    writer = get_batch_writer()
    await writer.start()


async def shutdown_batch_writer():
    """关闭批量写入器"""
    writer = get_batch_writer()
    await writer.stop()
