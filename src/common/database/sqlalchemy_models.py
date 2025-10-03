"""SQLAlchemy数据库模型定义

替换Peewee ORM，使用SQLAlchemy提供更好的连接池管理和错误恢复能力
"""

import datetime
import os
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, String, Text, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Mapped, mapped_column

from src.common.database.connection_pool_manager import get_connection_pool_manager
from src.common.logger import get_logger

logger = get_logger("sqlalchemy_models")

# 创建基类
Base = declarative_base()


async def enable_sqlite_wal_mode(engine):
    """为 SQLite 启用 WAL 模式以提高并发性能"""
    try:
        async with engine.begin() as conn:
            # 启用 WAL 模式
            await conn.execute(text("PRAGMA journal_mode = WAL"))
            # 设置适中的同步级别，平衡性能和安全性
            await conn.execute(text("PRAGMA synchronous = NORMAL"))
            # 启用外键约束
            await conn.execute(text("PRAGMA foreign_keys = ON"))
            # 设置 busy_timeout，避免锁定错误
            await conn.execute(text("PRAGMA busy_timeout = 60000"))  # 60秒

        logger.info("[SQLite] WAL 模式已启用，并发性能已优化")
    except Exception as e:
        logger.warning(f"[SQLite] 启用 WAL 模式失败: {e}，将使用默认配置")


async def maintain_sqlite_database():
    """定期维护 SQLite 数据库性能"""
    try:
        engine, SessionLocal = await initialize_database()
        if not engine:
            return

        async with engine.begin() as conn:
            # 检查并确保 WAL 模式仍然启用
            result = await conn.execute(text("PRAGMA journal_mode"))
            journal_mode = result.scalar()

            if journal_mode != "wal":
                await conn.execute(text("PRAGMA journal_mode = WAL"))
                logger.info("[SQLite] WAL 模式已重新启用")

            # 优化数据库性能
            await conn.execute(text("PRAGMA synchronous = NORMAL"))
            await conn.execute(text("PRAGMA busy_timeout = 60000"))
            await conn.execute(text("PRAGMA foreign_keys = ON"))

            # 定期清理（可选，根据需要启用）
            # await conn.execute(text("PRAGMA optimize"))

        logger.info("[SQLite] 数据库维护完成")
    except Exception as e:
        logger.warning(f"[SQLite] 数据库维护失败: {e}")


def get_sqlite_performance_config():
    """获取 SQLite 性能优化配置"""
    return {
        "journal_mode": "WAL",  # 提高并发性能
        "synchronous": "NORMAL",  # 平衡性能和安全性
        "busy_timeout": 60000,  # 60秒超时
        "foreign_keys": "ON",  # 启用外键约束
        "cache_size": -10000,  # 10MB 缓存
        "temp_store": "MEMORY",  # 临时存储使用内存
        "mmap_size": 268435456,  # 256MB 内存映射
    }


# MySQL兼容的字段类型辅助函数
def get_string_field(max_length=255, **kwargs):
    """
    根据数据库类型返回合适的字符串字段
    MySQL需要指定长度的VARCHAR用于索引，SQLite可以使用Text
    """
    from src.config.config import global_config

    if global_config.database.database_type == "mysql":
        return String(max_length, **kwargs)
    else:
        return Text(**kwargs)


class ChatStreams(Base):
    """聊天流模型"""

    __tablename__ = "chat_streams"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    stream_id = mapped_column(get_string_field(64), nullable=False, unique=True, index=True)
    create_time = mapped_column(Float, nullable=False)
    group_platform = mapped_column(Text, nullable=True)
    group_id = mapped_column(get_string_field(100), nullable=True, index=True)
    group_name = mapped_column(Text, nullable=True)
    last_active_time = mapped_column(Float, nullable=False)
    platform = mapped_column(Text, nullable=False)
    user_platform = mapped_column(Text, nullable=False)
    user_id = mapped_column(get_string_field(100), nullable=False, index=True)
    user_nickname = mapped_column(Text, nullable=False)
    user_cardname = mapped_column(Text, nullable=True)
    energy_value = mapped_column(Float, nullable=True, default=5.0)
    sleep_pressure = mapped_column(Float, nullable=True, default=0.0)
    focus_energy = mapped_column(Float, nullable=True, default=0.5)
    # 动态兴趣度系统字段
    base_interest_energy = mapped_column(Float, nullable=True, default=0.5)
    message_interest_total = mapped_column(Float, nullable=True, default=0.0)
    message_count = mapped_column(Integer, nullable=True, default=0)
    action_count = mapped_column(Integer, nullable=True, default=0)
    reply_count = mapped_column(Integer, nullable=True, default=0)
    last_interaction_time = mapped_column(Float, nullable=True, default=None)
    consecutive_no_reply = mapped_column(Integer, nullable=True, default=0)
    # 消息打断系统字段
    interruption_count = mapped_column(Integer, nullable=True, default=0)

    __table_args__ = (
        Index("idx_chatstreams_stream_id", "stream_id"),
        Index("idx_chatstreams_user_id", "user_id"),
        Index("idx_chatstreams_group_id", "group_id"),
    )


class LLMUsage(Base):
    """LLM使用记录模型"""

    __tablename__ = "llm_usage"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_name = mapped_column(get_string_field(100), nullable=False, index=True)
    model_assign_name = mapped_column(get_string_field(100), index=True)  # 添加索引
    model_api_provider = mapped_column(get_string_field(100), index=True)  # 添加索引
    user_id = mapped_column(get_string_field(50), nullable=False, index=True)
    request_type = mapped_column(get_string_field(50), nullable=False, index=True)
    endpoint = mapped_column(Text, nullable=False)
    prompt_tokens = mapped_column(Integer, nullable=False)
    completion_tokens = mapped_column(Integer, nullable=False)
    time_cost = mapped_column(Float, nullable=True)
    total_tokens = mapped_column(Integer, nullable=False)
    cost = mapped_column(Float, nullable=False)
    status = mapped_column(Text, nullable=False)
    timestamp = mapped_column(DateTime, nullable=False, index=True, default=datetime.datetime.now)

    __table_args__ = (
        Index("idx_llmusage_model_name", "model_name"),
        Index("idx_llmusage_model_assign_name", "model_assign_name"),
        Index("idx_llmusage_model_api_provider", "model_api_provider"),
        Index("idx_llmusage_time_cost", "time_cost"),
        Index("idx_llmusage_user_id", "user_id"),
        Index("idx_llmusage_request_type", "request_type"),
        Index("idx_llmusage_timestamp", "timestamp"),
    )


class Emoji(Base):
    """表情包模型"""

    __tablename__ = "emoji"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    full_path = mapped_column(get_string_field(500), nullable=False, unique=True, index=True)
    format = mapped_column(Text, nullable=False)
    emoji_hash = mapped_column(get_string_field(64), nullable=False, index=True)
    description = mapped_column(Text, nullable=False)
    query_count = mapped_column(Integer, nullable=False, default=0)
    is_registered = mapped_column(Boolean, nullable=False, default=False)
    is_banned = mapped_column(Boolean, nullable=False, default=False)
    emotion = mapped_column(Text, nullable=True)
    record_time = mapped_column(Float, nullable=False)
    register_time = mapped_column(Float, nullable=True)
    usage_count = mapped_column(Integer, nullable=False, default=0)
    last_used_time = mapped_column(Float, nullable=True)

    __table_args__ = (
        Index("idx_emoji_full_path", "full_path"),
        Index("idx_emoji_hash", "emoji_hash"),
    )


class Messages(Base):
    """消息模型"""

    __tablename__ = "messages"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id = mapped_column(get_string_field(100), nullable=False, index=True)
    time = mapped_column(Float, nullable=False)
    chat_id = mapped_column(get_string_field(64), nullable=False, index=True)
    reply_to = mapped_column(Text, nullable=True)
    interest_value = mapped_column(Float, nullable=True)
    key_words = mapped_column(Text, nullable=True)
    key_words_lite = mapped_column(Text, nullable=True)
    is_mentioned = mapped_column(Boolean, nullable=True)

    # 从 chat_info 扁平化而来的字段
    chat_info_stream_id = mapped_column(Text, nullable=False)
    chat_info_platform = mapped_column(Text, nullable=False)
    chat_info_user_platform = mapped_column(Text, nullable=False)
    chat_info_user_id = mapped_column(Text, nullable=False)
    chat_info_user_nickname = mapped_column(Text, nullable=False)
    chat_info_user_cardname = mapped_column(Text, nullable=True)
    chat_info_group_platform = mapped_column(Text, nullable=True)
    chat_info_group_id = mapped_column(Text, nullable=True)
    chat_info_group_name = mapped_column(Text, nullable=True)
    chat_info_create_time = mapped_column(Float, nullable=False)
    chat_info_last_active_time = mapped_column(Float, nullable=False)

    # 从顶层 user_info 扁平化而来的字段
    user_platform = mapped_column(Text, nullable=True)
    user_id = mapped_column(get_string_field(100), nullable=True, index=True)
    user_nickname = mapped_column(Text, nullable=True)
    user_cardname = mapped_column(Text, nullable=True)

    processed_plain_text = mapped_column(Text, nullable=True)
    display_message = mapped_column(Text, nullable=True)
    memorized_times = mapped_column(Integer, nullable=False, default=0)
    priority_mode = mapped_column(Text, nullable=True)
    priority_info = mapped_column(Text, nullable=True)
    additional_config = mapped_column(Text, nullable=True)
    is_emoji = mapped_column(Boolean, nullable=False, default=False)
    is_picid = mapped_column(Boolean, nullable=False, default=False)
    is_command = mapped_column(Boolean, nullable=False, default=False)
    is_notify = mapped_column(Boolean, nullable=False, default=False)

    # 兴趣度系统字段
    actions = mapped_column(Text, nullable=True)  # JSON格式存储动作列表
    should_reply = mapped_column(Boolean, nullable=True, default=False)

    __table_args__ = (
        Index("idx_messages_message_id", "message_id"),
        Index("idx_messages_chat_id", "chat_id"),
        Index("idx_messages_time", "time"),
        Index("idx_messages_user_id", "user_id"),
        Index("idx_messages_should_reply", "should_reply"),
    )


class ActionRecords(Base):
    """动作记录模型"""

    __tablename__ = "action_records"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    action_id = mapped_column(get_string_field(100), nullable=False, index=True)
    time = mapped_column(Float, nullable=False)
    action_name = mapped_column(Text, nullable=False)
    action_data = mapped_column(Text, nullable=False)
    action_done = mapped_column(Boolean, nullable=False, default=False)
    action_build_into_prompt = mapped_column(Boolean, nullable=False, default=False)
    action_prompt_display = mapped_column(Text, nullable=False)
    chat_id = mapped_column(get_string_field(64), nullable=False, index=True)
    chat_info_stream_id = mapped_column(Text, nullable=False)
    chat_info_platform = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("idx_actionrecords_action_id", "action_id"),
        Index("idx_actionrecords_chat_id", "chat_id"),
        Index("idx_actionrecords_time", "time"),
    )


class Images(Base):
    """图像信息模型"""

    __tablename__ = "images"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    image_id = mapped_column(Text, nullable=False, default="")
    emoji_hash = mapped_column(get_string_field(64), nullable=False, index=True)
    description = mapped_column(Text, nullable=True)
    path = mapped_column(get_string_field(500), nullable=False, unique=True)
    count = mapped_column(Integer, nullable=False, default=1)
    timestamp = mapped_column(Float, nullable=False)
    type = mapped_column(Text, nullable=False)
    vlm_processed = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("idx_images_emoji_hash", "emoji_hash"),
        Index("idx_images_path", "path"),
    )


class ImageDescriptions(Base):
    """图像描述信息模型"""

    __tablename__ = "image_descriptions"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    type = mapped_column(Text, nullable=False)
    image_description_hash = mapped_column(get_string_field(64), nullable=False, index=True)
    description = mapped_column(Text, nullable=False)
    timestamp = mapped_column(Float, nullable=False)

    __table_args__ = (Index("idx_imagedesc_hash", "image_description_hash"),)


class Videos(Base):
    """视频信息模型"""

    __tablename__ = "videos"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id = mapped_column(Text, nullable=False, default="")
    video_hash = mapped_column(get_string_field(64), nullable=False, index=True, unique=True)
    description = mapped_column(Text, nullable=True)
    count = mapped_column(Integer, nullable=False, default=1)
    timestamp = mapped_column(Float, nullable=False)
    vlm_processed = mapped_column(Boolean, nullable=False, default=False)

    # 视频特有属性
    duration = mapped_column(Float, nullable=True)  # 视频时长（秒）
    frame_count = mapped_column(Integer, nullable=True)  # 总帧数
    fps = mapped_column(Float, nullable=True)  # 帧率
    resolution = mapped_column(Text, nullable=True)  # 分辨率
    file_size = mapped_column(Integer, nullable=True)  # 文件大小（字节）

    __table_args__ = (
        Index("idx_videos_video_hash", "video_hash"),
        Index("idx_videos_timestamp", "timestamp"),
    )


class OnlineTime(Base):
    """在线时长记录模型"""

    __tablename__ = "online_time"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp = mapped_column(Text, nullable=False, default=str(datetime.datetime.now))
    duration = mapped_column(Integer, nullable=False)
    start_timestamp = mapped_column(DateTime, nullable=False, default=datetime.datetime.now)
    end_timestamp = mapped_column(DateTime, nullable=False, index=True)

    __table_args__ = (Index("idx_onlinetime_end_timestamp", "end_timestamp"),)


class PersonInfo(Base):
    """人物信息模型"""

    __tablename__ = "person_info"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    person_id = mapped_column(get_string_field(100), nullable=False, unique=True, index=True)
    person_name = mapped_column(Text, nullable=True)
    name_reason = mapped_column(Text, nullable=True)
    platform = mapped_column(Text, nullable=False)
    user_id = mapped_column(get_string_field(50), nullable=False, index=True)
    nickname = mapped_column(Text, nullable=True)
    impression = mapped_column(Text, nullable=True)
    short_impression = mapped_column(Text, nullable=True)
    points = mapped_column(Text, nullable=True)
    forgotten_points = mapped_column(Text, nullable=True)
    info_list = mapped_column(Text, nullable=True)
    know_times = mapped_column(Float, nullable=True)
    know_since = mapped_column(Float, nullable=True)
    last_know = mapped_column(Float, nullable=True)
    attitude = mapped_column(Integer, nullable=True, default=50)

    __table_args__ = (
        Index("idx_personinfo_person_id", "person_id"),
        Index("idx_personinfo_user_id", "user_id"),
    )


class BotPersonalityInterests(Base):
    """机器人人格兴趣标签模型"""

    __tablename__ = "bot_personality_interests"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    personality_id = mapped_column(get_string_field(100), nullable=False, index=True)
    personality_description: Mapped[str] = mapped_column(Text, nullable=False)
    interest_tags: Mapped[str] = mapped_column(Text, nullable=False)  # JSON格式存储的兴趣标签列表
    embedding_model = mapped_column(get_string_field(100), nullable=False, default="text-embedding-ada-002")
    version = mapped_column(Integer, nullable=False, default=1)
    last_updated = mapped_column(DateTime, nullable=False, default=datetime.datetime.now, index=True)

    __table_args__ = (
        Index("idx_botpersonality_personality_id", "personality_id"),
        Index("idx_botpersonality_version", "version"),
        Index("idx_botpersonality_last_updated", "last_updated"),
    )


class Memory(Base):
    """记忆模型"""

    __tablename__ = "memory"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    memory_id = mapped_column(get_string_field(64), nullable=False, index=True)
    chat_id = mapped_column(Text, nullable=True)
    memory_text = mapped_column(Text, nullable=True)
    keywords = mapped_column(Text, nullable=True)
    create_time = mapped_column(Float, nullable=True)
    last_view_time = mapped_column(Float, nullable=True)

    __table_args__ = (Index("idx_memory_memory_id", "memory_id"),)


class Expression(Base):
    """表达风格模型"""

    __tablename__ = "expression"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    situation: Mapped[str] = mapped_column(Text, nullable=False)
    style: Mapped[str] = mapped_column(Text, nullable=False)
    count: Mapped[float] = mapped_column(Float, nullable=False)
    last_active_time: Mapped[float] = mapped_column(Float, nullable=False)
    chat_id: Mapped[str] = mapped_column(get_string_field(64), nullable=False, index=True)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    create_date: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (Index("idx_expression_chat_id", "chat_id"),)


class ThinkingLog(Base):
    """思考日志模型"""

    __tablename__ = "thinking_logs"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id = mapped_column(get_string_field(64), nullable=False, index=True)
    trigger_text = mapped_column(Text, nullable=True)
    response_text = mapped_column(Text, nullable=True)
    trigger_info_json = mapped_column(Text, nullable=True)
    response_info_json = mapped_column(Text, nullable=True)
    timing_results_json = mapped_column(Text, nullable=True)
    chat_history_json = mapped_column(Text, nullable=True)
    chat_history_in_thinking_json = mapped_column(Text, nullable=True)
    chat_history_after_response_json = mapped_column(Text, nullable=True)
    heartflow_data_json = mapped_column(Text, nullable=True)
    reasoning_data_json = mapped_column(Text, nullable=True)
    created_at = mapped_column(DateTime, nullable=False, default=datetime.datetime.now)

    __table_args__ = (Index("idx_thinkinglog_chat_id", "chat_id"),)


class GraphNodes(Base):
    """记忆图节点模型"""

    __tablename__ = "graph_nodes"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    concept = mapped_column(get_string_field(255), nullable=False, unique=True, index=True)
    memory_items = mapped_column(Text, nullable=False)
    hash = mapped_column(Text, nullable=False)
    weight = mapped_column(Float, nullable=False, default=1.0)
    created_time = mapped_column(Float, nullable=False)
    last_modified = mapped_column(Float, nullable=False)

    __table_args__ = (Index("idx_graphnodes_concept", "concept"),)


class GraphEdges(Base):
    """记忆图边模型"""

    __tablename__ = "graph_edges"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    source = mapped_column(get_string_field(255), nullable=False, index=True)
    target = mapped_column(get_string_field(255), nullable=False, index=True)
    strength = mapped_column(Integer, nullable=False)
    hash = mapped_column(Text, nullable=False)
    created_time = mapped_column(Float, nullable=False)
    last_modified = mapped_column(Float, nullable=False)

    __table_args__ = (
        Index("idx_graphedges_source", "source"),
        Index("idx_graphedges_target", "target"),
    )


class Schedule(Base):
    """日程模型"""

    __tablename__ = "schedule"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    date = mapped_column(get_string_field(10), nullable=False, unique=True, index=True)  # YYYY-MM-DD格式
    schedule_data = mapped_column(Text, nullable=False)  # JSON格式的日程数据
    created_at = mapped_column(DateTime, nullable=False, default=datetime.datetime.now)
    updated_at = mapped_column(DateTime, nullable=False, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    __table_args__ = (Index("idx_schedule_date", "date"),)


class MaiZoneScheduleStatus(Base):
    """麦麦空间日程处理状态模型"""

    __tablename__ = "maizone_schedule_status"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    datetime_hour = mapped_column(
        get_string_field(13), nullable=False, unique=True, index=True
    )  # YYYY-MM-DD HH格式，精确到小时
    activity = mapped_column(Text, nullable=False)  # 该小时的活动内容
    is_processed = mapped_column(Boolean, nullable=False, default=False)  # 是否已处理
    processed_at = mapped_column(DateTime, nullable=True)  # 处理时间
    story_content = mapped_column(Text, nullable=True)  # 生成的说说内容
    send_success = mapped_column(Boolean, nullable=False, default=False)  # 是否发送成功
    created_at = mapped_column(DateTime, nullable=False, default=datetime.datetime.now)
    updated_at = mapped_column(DateTime, nullable=False, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    __table_args__ = (
        Index("idx_maizone_datetime_hour", "datetime_hour"),
        Index("idx_maizone_is_processed", "is_processed"),
    )


class BanUser(Base):
    """被禁用用户模型"""

    __tablename__ = "ban_users"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform = mapped_column(Text, nullable=False)
    user_id = mapped_column(get_string_field(50), nullable=False, index=True)
    violation_num = mapped_column(Integer, nullable=False, default=0)
    reason = mapped_column(Text, nullable=False)
    created_at = mapped_column(DateTime, nullable=False, default=datetime.datetime.now)

    __table_args__ = (
        Index("idx_violation_num", "violation_num"),
        Index("idx_banuser_user_id", "user_id"),
        Index("idx_banuser_platform", "platform"),
        Index("idx_banuser_platform_user_id", "platform", "user_id"),
    )


class AntiInjectionStats(Base):
    """反注入系统统计模型"""

    __tablename__ = "anti_injection_stats"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    total_messages = mapped_column(Integer, nullable=False, default=0)
    """总处理消息数"""

    detected_injections = mapped_column(Integer, nullable=False, default=0)
    """检测到的注入攻击数"""

    blocked_messages = mapped_column(Integer, nullable=False, default=0)
    """被阻止的消息数"""

    shielded_messages = mapped_column(Integer, nullable=False, default=0)
    """被加盾的消息数"""

    processing_time_total = mapped_column(Float, nullable=False, default=0.0)
    """总处理时间"""

    total_process_time = mapped_column(Float, nullable=False, default=0.0)
    """累计总处理时间"""

    last_process_time = mapped_column(Float, nullable=False, default=0.0)
    """最近一次处理时间"""

    error_count = mapped_column(Integer, nullable=False, default=0)
    """错误计数"""

    start_time = mapped_column(DateTime, nullable=False, default=datetime.datetime.now)
    """统计开始时间"""

    created_at = mapped_column(DateTime, nullable=False, default=datetime.datetime.now)
    """记录创建时间"""

    updated_at = mapped_column(DateTime, nullable=False, default=datetime.datetime.now, onupdate=datetime.datetime.now)
    """记录更新时间"""

    __table_args__ = (
        Index("idx_anti_injection_stats_created_at", "created_at"),
        Index("idx_anti_injection_stats_updated_at", "updated_at"),
    )


class CacheEntries(Base):
    """工具缓存条目模型"""

    __tablename__ = "cache_entries"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    cache_key = mapped_column(get_string_field(500), nullable=False, unique=True, index=True)
    """缓存键，包含工具名、参数和代码哈希"""

    cache_value = mapped_column(Text, nullable=False)
    """缓存的数据，JSON格式"""

    expires_at = mapped_column(Float, nullable=False, index=True)
    """过期时间戳"""

    tool_name = mapped_column(get_string_field(100), nullable=False, index=True)
    """工具名称"""

    created_at = mapped_column(Float, nullable=False, default=lambda: time.time())
    """创建时间戳"""

    last_accessed = mapped_column(Float, nullable=False, default=lambda: time.time())
    """最后访问时间戳"""

    access_count = mapped_column(Integer, nullable=False, default=0)
    """访问次数"""

    __table_args__ = (
        Index("idx_cache_entries_key", "cache_key"),
        Index("idx_cache_entries_expires_at", "expires_at"),
        Index("idx_cache_entries_tool_name", "tool_name"),
        Index("idx_cache_entries_created_at", "created_at"),
    )


class MonthlyPlan(Base):
    """月度计划模型"""

    __tablename__ = "monthly_plans"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_text = mapped_column(Text, nullable=False)
    target_month = mapped_column(String(7), nullable=False, index=True)  # "YYYY-MM"
    status = mapped_column(
        get_string_field(20), nullable=False, default="active", index=True
    )  # 'active', 'completed', 'archived'
    usage_count = mapped_column(Integer, nullable=False, default=0)
    last_used_date = mapped_column(String(10), nullable=True, index=True)  # "YYYY-MM-DD" format
    created_at = mapped_column(DateTime, nullable=False, default=datetime.datetime.now)

    # 保留 is_deleted 字段以兼容现有数据，但标记为已弃用
    is_deleted = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("idx_monthlyplan_target_month_status", "target_month", "status"),
        Index("idx_monthlyplan_last_used_date", "last_used_date"),
        Index("idx_monthlyplan_usage_count", "usage_count"),
        # 保留旧索引以兼容
        Index("idx_monthlyplan_target_month_is_deleted", "target_month", "is_deleted"),
    )


# 数据库引擎和会话管理
_engine = None
_SessionLocal = None


def get_database_url():
    """获取数据库连接URL"""
    from src.config.config import global_config

    config = global_config.database

    if config.database_type == "mysql":
        # 对用户名和密码进行URL编码，处理特殊字符
        from urllib.parse import quote_plus

        encoded_user = quote_plus(config.mysql_user)
        encoded_password = quote_plus(config.mysql_password)

        # 检查是否配置了Unix socket连接
        if config.mysql_unix_socket:
            # 使用Unix socket连接
            encoded_socket = quote_plus(config.mysql_unix_socket)
            return (
                f"mysql+aiomysql://{encoded_user}:{encoded_password}"
                f"@/{config.mysql_database}"
                f"?unix_socket={encoded_socket}&charset={config.mysql_charset}"
            )
        else:
            # 使用标准TCP连接
            return (
                f"mysql+aiomysql://{encoded_user}:{encoded_password}"
                f"@{config.mysql_host}:{config.mysql_port}/{config.mysql_database}"
                f"?charset={config.mysql_charset}"
            )
    else:  # SQLite
        # 如果是相对路径，则相对于项目根目录
        if not os.path.isabs(config.sqlite_path):
            ROOT_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
            db_path = os.path.join(ROOT_PATH, config.sqlite_path)
        else:
            db_path = config.sqlite_path

        # 确保数据库目录存在
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        return f"sqlite+aiosqlite:///{db_path}"


async def initialize_database():
    """初始化异步数据库引擎和会话"""
    global _engine, _SessionLocal

    if _engine is not None:
        return _engine, _SessionLocal

    database_url = get_database_url()
    from src.config.config import global_config

    config = global_config.database

    # 配置引擎参数
    engine_kwargs: dict[str, Any] = {
        "echo": False,  # 生产环境关闭SQL日志
        "future": True,
    }

    if config.database_type == "mysql":
        # MySQL连接池配置 - 异步引擎使用默认连接池
        engine_kwargs.update(
            {
                "pool_size": config.connection_pool_size,
                "max_overflow": config.connection_pool_size * 2,
                "pool_timeout": config.connection_timeout,
                "pool_recycle": 3600,  # 1小时回收连接
                "pool_pre_ping": True,  # 连接前ping检查
                "connect_args": {
                    "autocommit": config.mysql_autocommit,
                    "charset": config.mysql_charset,
                    "connect_timeout": config.connection_timeout,
                },
            }
        )
    else:
        # SQLite配置 - aiosqlite不支持连接池参数
        engine_kwargs.update(
            {
                "connect_args": {
                    "check_same_thread": False,
                    "timeout": 60,  # 增加超时时间
                },
            }
        )

    _engine = create_async_engine(database_url, **engine_kwargs)
    _SessionLocal = async_sessionmaker(bind=_engine, class_=AsyncSession, expire_on_commit=False)

    # 调用新的迁移函数，它会处理表的创建和列的添加
    from src.common.database.db_migration import check_and_migrate_database

    await check_and_migrate_database()

    # 如果是 SQLite，启用 WAL 模式以提高并发性能
    if config.database_type == "sqlite":
        await enable_sqlite_wal_mode(_engine)

    logger.info(f"SQLAlchemy异步数据库初始化成功: {config.database_type}")
    return _engine, _SessionLocal


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession]:
    """
    异步数据库会话上下文管理器。
    在初始化失败时会yield None，调用方需要检查会话是否为None。

    现在使用透明的连接池管理器来复用现有连接，提高并发性能。
    """
    SessionLocal = None
    try:
        _, SessionLocal = await initialize_database()
        if not SessionLocal:
            raise RuntimeError("数据库会话工厂 (_SessionLocal) 未初始化。")
    except Exception as e:
        logger.error(f"数据库初始化失败，无法创建会话: {e}")
        raise

    # 使用连接池管理器获取会话
    pool_manager = get_connection_pool_manager()

    async with pool_manager.get_session(SessionLocal) as session:
        # 对于 SQLite，在会话开始时设置 PRAGMA（仅对新连接）
        from src.config.config import global_config

        if global_config.database.database_type == "sqlite":
            try:
                await session.execute(text("PRAGMA busy_timeout = 60000"))
                await session.execute(text("PRAGMA foreign_keys = ON"))
            except Exception as e:
                logger.debug(f"设置 SQLite PRAGMA 时出错（可能是复用连接）: {e}")

        yield session


async def get_engine():
    """获取异步数据库引擎"""
    engine, _ = await initialize_database()
    return engine


class PermissionNodes(Base):
    """权限节点模型"""

    __tablename__ = "permission_nodes"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_name = mapped_column(get_string_field(255), nullable=False, unique=True, index=True)  # 权限节点名称
    description = mapped_column(Text, nullable=False)  # 权限描述
    plugin_name = mapped_column(get_string_field(100), nullable=False, index=True)  # 所属插件
    default_granted = mapped_column(Boolean, default=False, nullable=False)  # 默认是否授权
    created_at = mapped_column(DateTime, default=datetime.datetime.utcnow, nullable=False)  # 创建时间

    __table_args__ = (
        Index("idx_permission_plugin", "plugin_name"),
        Index("idx_permission_node", "node_name"),
    )


class UserPermissions(Base):
    """用户权限模型"""

    __tablename__ = "user_permissions"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform = mapped_column(get_string_field(50), nullable=False, index=True)  # 平台类型
    user_id = mapped_column(get_string_field(100), nullable=False, index=True)  # 用户ID
    permission_node = mapped_column(get_string_field(255), nullable=False, index=True)  # 权限节点名称
    granted = mapped_column(Boolean, default=True, nullable=False)  # 是否授权
    granted_at = mapped_column(DateTime, default=datetime.datetime.utcnow, nullable=False)  # 授权时间
    granted_by = mapped_column(get_string_field(100), nullable=True)  # 授权者信息

    __table_args__ = (
        Index("idx_user_platform_id", "platform", "user_id"),
        Index("idx_user_permission", "platform", "user_id", "permission_node"),
        Index("idx_permission_granted", "permission_node", "granted"),
    )


class UserRelationships(Base):
    """用户关系模型 - 存储用户与bot的关系数据"""

    __tablename__ = "user_relationships"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id = mapped_column(get_string_field(100), nullable=False, unique=True, index=True)  # 用户ID
    user_name = mapped_column(get_string_field(100), nullable=True)  # 用户名
    relationship_text = mapped_column(Text, nullable=True)  # 关系印象描述
    relationship_score = mapped_column(Float, nullable=False, default=0.3)  # 关系分数(0-1)
    last_updated = mapped_column(Float, nullable=False, default=time.time)  # 最后更新时间
    created_at = mapped_column(DateTime, default=datetime.datetime.utcnow, nullable=False)  # 创建时间

    __table_args__ = (
        Index("idx_user_relationship_id", "user_id"),
        Index("idx_relationship_score", "relationship_score"),
        Index("idx_relationship_updated", "last_updated"),
    )
