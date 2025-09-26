import asyncio
import hashlib
import time
import copy
from typing import Dict, Optional, TYPE_CHECKING
from rich.traceback import install
from maim_message import GroupInfo, UserInfo

from src.common.logger import get_logger
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.mysql import insert as mysql_insert
from src.common.database.sqlalchemy_models import ChatStreams  # 新增导入
from src.common.database.sqlalchemy_database_api import get_db_session
from src.config.config import global_config  # 新增导入

# 避免循环导入，使用TYPE_CHECKING进行类型提示
if TYPE_CHECKING:
    from .message import MessageRecv


install(extra_lines=3)


logger = get_logger("chat_stream")


class ChatStream:
    """聊天流对象，存储一个完整的聊天上下文"""

    def __init__(
        self,
        stream_id: str,
        platform: str,
        user_info: UserInfo,
        group_info: Optional[GroupInfo] = None,
        data: Optional[dict] = None,
    ):
        self.stream_id = stream_id
        self.platform = platform
        self.user_info = user_info
        self.group_info = group_info
        self.create_time = data.get("create_time", time.time()) if data else time.time()
        self.last_active_time = data.get("last_active_time", self.create_time) if data else self.create_time
        self.sleep_pressure = data.get("sleep_pressure", 0.0) if data else 0.0
        self.saved = False

        # 使用StreamContext替代ChatMessageContext
        from src.common.data_models.message_manager_data_model import StreamContext
        from src.plugin_system.base.component_types import ChatType, ChatMode

        self.stream_context: StreamContext = StreamContext(
            stream_id=stream_id, chat_type=ChatType.GROUP if group_info else ChatType.PRIVATE, chat_mode=ChatMode.NORMAL
        )

        # 基础参数
        self.base_interest_energy = 0.5  # 默认基础兴趣度
        self._focus_energy = 0.5  # 内部存储的focus_energy值
        self.no_reply_consecutive = 0

        # 自动加载历史消息
        self._load_history_messages()

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "stream_id": self.stream_id,
            "platform": self.platform,
            "user_info": self.user_info.to_dict() if self.user_info else None,
            "group_info": self.group_info.to_dict() if self.group_info else None,
            "create_time": self.create_time,
            "last_active_time": self.last_active_time,
            "sleep_pressure": self.sleep_pressure,
            "focus_energy": self.focus_energy,
            # 基础兴趣度
            "base_interest_energy": self.base_interest_energy,
            # 新增stream_context信息
            "stream_context_chat_type": self.stream_context.chat_type.value,
            "stream_context_chat_mode": self.stream_context.chat_mode.value,
            # 新增interruption_count信息
            "interruption_count": self.stream_context.interruption_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ChatStream":
        """从字典创建实例"""
        user_info = UserInfo.from_dict(data.get("user_info", {})) if data.get("user_info") else None
        group_info = GroupInfo.from_dict(data.get("group_info", {})) if data.get("group_info") else None

        instance = cls(
            stream_id=data["stream_id"],
            platform=data["platform"],
            user_info=user_info,  # type: ignore
            group_info=group_info,
            data=data,
        )

        # 恢复stream_context信息
        if "stream_context_chat_type" in data:
            from src.plugin_system.base.component_types import ChatType, ChatMode

            instance.stream_context.chat_type = ChatType(data["stream_context_chat_type"])
        if "stream_context_chat_mode" in data:
            from src.plugin_system.base.component_types import ChatType, ChatMode

            instance.stream_context.chat_mode = ChatMode(data["stream_context_chat_mode"])

        # 恢复interruption_count信息
        if "interruption_count" in data:
            instance.stream_context.interruption_count = data["interruption_count"]

        return instance

    def update_active_time(self):
        """更新最后活跃时间"""
        self.last_active_time = time.time()
        self.saved = False

    def set_context(self, message: "MessageRecv"):
        """设置聊天消息上下文"""
        # 将MessageRecv转换为DatabaseMessages并设置到stream_context
        from src.common.data_models.database_data_model import DatabaseMessages

        # 简化转换，实际可能需要更完整的转换逻辑
        db_message = DatabaseMessages(
            message_id=getattr(message, "message_id", ""),
            time=getattr(message, "time", time.time()),
            chat_id=getattr(message, "chat_id", ""),
            user_id=str(getattr(message.message_info, "user_info", {}).user_id)
            if hasattr(message, "message_info") and hasattr(message.message_info, "user_info")
            else "",
            user_nickname=getattr(message.message_info, "user_info", {}).user_nickname
            if hasattr(message, "message_info") and hasattr(message.message_info, "user_info")
            else "",
            user_platform=getattr(message.message_info, "user_info", {}).platform
            if hasattr(message, "message_info") and hasattr(message.message_info, "user_info")
            else "",
            priority_mode=getattr(message, "priority_mode", None),
            priority_info=str(getattr(message, "priority_info", None))
            if hasattr(message, "priority_info") and message.priority_info
            else None,
            additional_config=getattr(getattr(message, "message_info", {}), "additional_config", None),
        )

        self.stream_context.set_current_message(db_message)
        self.stream_context.priority_mode = getattr(message, "priority_mode", None)
        self.stream_context.priority_info = getattr(message, "priority_info", None)

    @property
    def focus_energy(self) -> float:
        """动态计算的聊天流总体兴趣度，访问时自动更新"""
        self._focus_energy = self._calculate_dynamic_focus_energy()
        return self._focus_energy

    @focus_energy.setter
    def focus_energy(self, value: float):
        """设置focus_energy值（主要用于初始化或特殊场景）"""
        self._focus_energy = max(0.0, min(1.0, value))

    def _calculate_dynamic_focus_energy(self) -> float:
        """动态计算聊天流的总体兴趣度，使用StreamContext历史消息"""
        try:
            # 从StreamContext获取历史消息计算统计数据
            history_messages = self.stream_context.get_history_messages(limit=global_config.chat.max_context_size)
            unread_messages = self.stream_context.get_unread_messages()
            all_messages = history_messages + unread_messages

            # 计算基于历史消息的统计数据
            if all_messages:
                # 基础分：平均消息兴趣度
                message_interests = [msg.interest_degree for msg in all_messages if hasattr(msg, "interest_degree")]
                avg_message_interest = sum(message_interests) / len(message_interests) if message_interests else 0.3

                # 动作参与度：有动作的消息比例
                messages_with_actions = [msg for msg in all_messages if hasattr(msg, "actions") and msg.actions]
                action_rate = len(messages_with_actions) / len(all_messages)

                # 回复活跃度：应该回复且已回复的消息比例
                should_reply_messages = [
                    msg for msg in all_messages if hasattr(msg, "should_reply") and msg.should_reply
                ]
                replied_messages = [
                    msg for msg in should_reply_messages if hasattr(msg, "actions") and "reply" in (msg.actions or [])
                ]
                reply_rate = len(replied_messages) / len(should_reply_messages) if should_reply_messages else 0.0

                # 获取最后交互时间
                if all_messages:
                    self.last_interaction_time = max(msg.time for msg in all_messages)

                # 连续无回复计算：从最近的未回复消息计数
                consecutive_no_reply = 0
                for msg in reversed(all_messages):
                    if hasattr(msg, "should_reply") and msg.should_reply:
                        if not (hasattr(msg, "actions") and "reply" in (msg.actions or [])):
                            consecutive_no_reply += 1
                        else:
                            break
            else:
                # 没有历史消息时的默认值
                avg_message_interest = 0.3
                action_rate = 0.0
                reply_rate = 0.0
                consecutive_no_reply = 0
                self.last_interaction_time = time.time()

            # 获取用户关系分（对于私聊，群聊无效）
            relationship_factor = self._get_user_relationship_score()

            # 时间衰减因子：最近活跃度
            current_time = time.time()
            if not hasattr(self, "last_interaction_time") or not self.last_interaction_time:
                self.last_interaction_time = current_time
            time_since_interaction = current_time - self.last_interaction_time
            time_decay = max(0.3, 1.0 - min(time_since_interaction / (7 * 24 * 3600), 0.7))  # 7天衰减

            # 连续无回复惩罚
            no_reply_penalty = max(0.1, 1.0 - consecutive_no_reply * 0.1)

            # 获取AFC系统阈值，添加None值检查
            reply_threshold = getattr(global_config.affinity_flow, "reply_action_interest_threshold", 0.4)
            non_reply_threshold = getattr(global_config.affinity_flow, "non_reply_action_interest_threshold", 0.2)
            high_match_threshold = getattr(global_config.affinity_flow, "high_match_interest_threshold", 0.8)

            # 计算与不同阈值的差距比例
            reply_gap_ratio = max(0, (avg_message_interest - reply_threshold) / max(0.1, (1.0 - reply_threshold)))
            non_reply_gap_ratio = max(
                0, (avg_message_interest - non_reply_threshold) / max(0.1, (1.0 - non_reply_threshold))
            )
            high_match_gap_ratio = max(
                0, (avg_message_interest - high_match_threshold) / max(0.1, (1.0 - high_match_threshold))
            )

            # 基于阈值差距比例的基础分计算
            threshold_based_score = (
                reply_gap_ratio * 0.6  # 回复阈值差距权重60%
                + non_reply_gap_ratio * 0.2  # 非回复阈值差距权重20%
                + high_match_gap_ratio * 0.2  # 高匹配阈值差距权重20%
            )

            # 动态权重调整：根据平均兴趣度水平调整权重分配
            if avg_message_interest >= high_match_threshold:
                # 高兴趣度：更注重阈值差距
                threshold_weight = 0.7
                activity_weight = 0.2
                relationship_weight = 0.1
            elif avg_message_interest >= reply_threshold:
                # 中等兴趣度：平衡权重
                threshold_weight = 0.5
                activity_weight = 0.3
                relationship_weight = 0.2
            else:
                # 低兴趣度：更注重活跃度提升
                threshold_weight = 0.3
                activity_weight = 0.5
                relationship_weight = 0.2

            # 计算活跃度得分
            activity_score = action_rate * 0.6 + reply_rate * 0.4

            # 综合计算：基于阈值的动态加权
            focus_energy = (
                (
                    threshold_based_score * threshold_weight  # 阈值差距基础分
                    + activity_score * activity_weight  # 活跃度得分
                    + relationship_factor * relationship_weight  # 关系得分
                    + self.base_interest_energy * 0.05  # 基础兴趣微调
                )
                * time_decay
                * no_reply_penalty
            )

            # 确保在合理范围内
            focus_energy = max(0.1, min(1.0, focus_energy))

            # 应用非线性变换增强区分度
            if focus_energy >= 0.7:
                # 高兴趣度区域：指数增强，更敏感
                focus_energy = 0.7 + (focus_energy - 0.7) ** 0.8
            elif focus_energy >= 0.4:
                # 中等兴趣度区域：线性保持
                pass
            else:
                # 低兴趣度区域：对数压缩，减少区分度
                focus_energy = 0.4 * (focus_energy / 0.4) ** 1.2

            return max(0.1, min(1.0, focus_energy))

        except Exception as e:
            logger.error(f"计算动态focus_energy失败: {e}")
            return self.base_interest_energy

    def _get_user_relationship_score(self) -> float:
        """从外部系统获取用户关系分"""
        try:
            # 尝试从兴趣评分系统获取用户关系分
            from src.plugins.built_in.affinity_flow_chatter.interest_scoring import (
                chatter_interest_scoring_system,
            )

            if self.user_info and hasattr(self.user_info, "user_id"):
                return chatter_interest_scoring_system.get_user_relationship(str(self.user_info.user_id))
        except Exception:
            pass

        # 默认基础分
        return 0.3

    def _load_history_messages(self):
        """从数据库加载历史消息到StreamContext"""
        try:
            from src.common.database.sqlalchemy_models import Messages
            from src.common.database.sqlalchemy_database_api import get_db_session
            from src.common.data_models.database_data_model import DatabaseMessages
            from sqlalchemy import select, desc
            import asyncio

            async def _load_messages():
                def _db_query():
                    with get_db_session() as session:
                        # 查询该stream_id的最近20条消息
                        stmt = (
                            select(Messages)
                            .where(Messages.chat_info_stream_id == self.stream_id)
                            .order_by(desc(Messages.time))
                            .limit(global_config.chat.max_context_size)
                        )
                        results = session.execute(stmt).scalars().all()
                        return results

                # 在线程中执行数据库查询
                db_messages = await asyncio.to_thread(_db_query)

                # 转换为DatabaseMessages对象并添加到StreamContext
                for db_msg in db_messages:
                    try:
                        # 从SQLAlchemy模型转换为DatabaseMessages数据模型
                        import orjson

                        # 解析actions字段（JSON格式）
                        actions = None
                        if db_msg.actions:
                            try:
                                actions = orjson.loads(db_msg.actions)
                            except (orjson.JSONDecodeError, TypeError):
                                actions = None

                        db_message = DatabaseMessages(
                            message_id=db_msg.message_id,
                            time=db_msg.time,
                            chat_id=db_msg.chat_id,
                            reply_to=db_msg.reply_to,
                            interest_value=db_msg.interest_value,
                            key_words=db_msg.key_words,
                            key_words_lite=db_msg.key_words_lite,
                            is_mentioned=db_msg.is_mentioned,
                            processed_plain_text=db_msg.processed_plain_text,
                            display_message=db_msg.display_message,
                            priority_mode=db_msg.priority_mode,
                            priority_info=db_msg.priority_info,
                            additional_config=db_msg.additional_config,
                            is_emoji=db_msg.is_emoji,
                            is_picid=db_msg.is_picid,
                            is_command=db_msg.is_command,
                            is_notify=db_msg.is_notify,
                            user_id=db_msg.user_id,
                            user_nickname=db_msg.user_nickname,
                            user_cardname=db_msg.user_cardname,
                            user_platform=db_msg.user_platform,
                            chat_info_group_id=db_msg.chat_info_group_id,
                            chat_info_group_name=db_msg.chat_info_group_name,
                            chat_info_group_platform=db_msg.chat_info_group_platform,
                            chat_info_user_id=db_msg.chat_info_user_id,
                            chat_info_user_nickname=db_msg.chat_info_user_nickname,
                            chat_info_user_cardname=db_msg.chat_info_user_cardname,
                            chat_info_user_platform=db_msg.chat_info_user_platform,
                            chat_info_stream_id=db_msg.chat_info_stream_id,
                            chat_info_platform=db_msg.chat_info_platform,
                            chat_info_create_time=db_msg.chat_info_create_time,
                            chat_info_last_active_time=db_msg.chat_info_last_active_time,
                            # 新增的兴趣度系统字段
                            interest_degree=getattr(db_msg, "interest_degree", 0.0) or 0.0,
                            actions=actions,
                            should_reply=getattr(db_msg, "should_reply", False) or False,
                        )

                        # 标记为已读并添加到历史消息
                        db_message.is_read = True
                        self.stream_context.history_messages.append(db_message)

                    except Exception as e:
                        logger.warning(f"转换消息 {db_msg.message_id} 失败: {e}")
                        continue

                if self.stream_context.history_messages:
                    logger.info(
                        f"已从数据库加载 {len(self.stream_context.history_messages)} 条历史消息到聊天流 {self.stream_id}"
                    )

            # 创建任务来加载历史消息
            asyncio.create_task(_load_messages())

        except Exception as e:
            logger.error(f"加载历史消息失败: {e}")


class ChatManager:
    """聊天管理器，管理所有聊天流"""

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.streams: Dict[str, ChatStream] = {}  # stream_id -> ChatStream
            self.last_messages: Dict[str, "MessageRecv"] = {}  # stream_id -> last_message
            # try:
            # with get_db_session() as session:
            #     db.connect(reuse_if_open=True)
            #     # 确保 ChatStreams 表存在
            #     session.execute(text("CREATE TABLE IF NOT EXISTS chat_streams (stream_id TEXT PRIMARY KEY, platform TEXT, create_time REAL, last_active_time REAL, user_platform TEXT, user_id TEXT, user_nickname TEXT, user_cardname TEXT, group_platform TEXT, group_id TEXT, group_name TEXT)"))
            #     session.commit()
            # except Exception as e:
            #     logger.error(f"数据库连接或 ChatStreams 表创建失败: {e}")

            self._initialized = True
            # 在事件循环中启动初始化
            # asyncio.create_task(self._initialize())
            # # 启动自动保存任务
            # asyncio.create_task(self._auto_save_task())

    async def _initialize(self):
        """异步初始化"""
        try:
            await self.load_all_streams()
            logger.info(f"聊天管理器已启动，已加载 {len(self.streams)} 个聊天流")
        except Exception as e:
            logger.error(f"聊天管理器启动失败: {str(e)}")

    async def _auto_save_task(self):
        """定期自动保存所有聊天流"""
        while True:
            await asyncio.sleep(300)  # 每5分钟保存一次
            try:
                await self._save_all_streams()
                logger.info("聊天流自动保存完成")
            except Exception as e:
                logger.error(f"聊天流自动保存失败: {str(e)}")

    def register_message(self, message: "MessageRecv"):
        """注册消息到聊天流"""
        stream_id = self._generate_stream_id(
            message.message_info.platform,  # type: ignore
            message.message_info.user_info,
            message.message_info.group_info,
        )
        self.last_messages[stream_id] = message
        # logger.debug(f"注册消息到聊天流: {stream_id}")

    @staticmethod
    def _generate_stream_id(
        platform: str, user_info: Optional[UserInfo], group_info: Optional[GroupInfo] = None
    ) -> str:
        """生成聊天流唯一ID"""
        if not user_info and not group_info:
            raise ValueError("用户信息或群组信息必须提供")

        if group_info:
            # 组合关键信息
            components = [platform, str(group_info.group_id)]
        else:
            components = [platform, str(user_info.user_id), "private"]  # type: ignore

        # 使用MD5生成唯一ID
        key = "_".join(components)
        return hashlib.md5(key.encode()).hexdigest()

    def get_stream_id(self, platform: str, id: str, is_group: bool = True) -> str:
        """获取聊天流ID"""
        components = [platform, id] if is_group else [platform, id, "private"]
        key = "_".join(components)
        return hashlib.md5(key.encode()).hexdigest()

    async def get_or_create_stream(
        self, platform: str, user_info: UserInfo, group_info: Optional[GroupInfo] = None
    ) -> ChatStream:
        """获取或创建聊天流

        Args:
            platform: 平台标识
            user_info: 用户信息
            group_info: 群组信息（可选）

        Returns:
            ChatStream: 聊天流对象
        """
        # 生成stream_id
        try:
            stream_id = self._generate_stream_id(platform, user_info, group_info)

            # 检查内存中是否存在
            if stream_id in self.streams:
                stream = self.streams[stream_id]

                # 更新用户信息和群组信息
                stream.update_active_time()
                stream = copy.deepcopy(stream)  # 返回副本以避免外部修改影响缓存
                if user_info.platform and user_info.user_id:
                    stream.user_info = user_info
                if group_info:
                    stream.group_info = group_info
                from .message import MessageRecv  # 延迟导入，避免循环引用

                if stream_id in self.last_messages and isinstance(self.last_messages[stream_id], MessageRecv):
                    stream.set_context(self.last_messages[stream_id])
                else:
                    logger.error(f"聊天流 {stream_id} 不在最后消息列表中，可能是新创建的")
                return stream

            # 检查数据库中是否存在
            def _db_find_stream_sync(s_id: str):
                with get_db_session() as session:
                    return session.execute(select(ChatStreams).where(ChatStreams.stream_id == s_id)).scalar()

            model_instance = await asyncio.to_thread(_db_find_stream_sync, stream_id)

            if model_instance:
                # 从 Peewee 模型转换回 ChatStream.from_dict 期望的格式
                user_info_data = {
                    "platform": model_instance.user_platform,
                    "user_id": model_instance.user_id,
                    "user_nickname": model_instance.user_nickname,
                    "user_cardname": model_instance.user_cardname or "",
                }
                group_info_data = None
                if model_instance and getattr(model_instance, "group_id", None):
                    group_info_data = {
                        "platform": model_instance.group_platform,
                        "group_id": model_instance.group_id,
                        "group_name": model_instance.group_name,
                    }

                data_for_from_dict = {
                    "stream_id": model_instance.stream_id,
                    "platform": model_instance.platform,
                    "user_info": user_info_data,
                    "group_info": group_info_data,
                    "create_time": model_instance.create_time,
                    "last_active_time": model_instance.last_active_time,
                    "energy_value": model_instance.energy_value,
                    "sleep_pressure": model_instance.sleep_pressure,
                }
                stream = ChatStream.from_dict(data_for_from_dict)
                # 更新用户信息和群组信息
                stream.user_info = user_info
                if group_info:
                    stream.group_info = group_info
                stream.update_active_time()
            else:
                # 创建新的聊天流
                stream = ChatStream(
                    stream_id=stream_id,
                    platform=platform,
                    user_info=user_info,
                    group_info=group_info,
                )
        except Exception as e:
            logger.error(f"获取或创建聊天流失败: {e}", exc_info=True)
            raise e

        stream = copy.deepcopy(stream)
        from .message import MessageRecv  # 延迟导入，避免循环引用

        if stream_id in self.last_messages and isinstance(self.last_messages[stream_id], MessageRecv):
            stream.set_context(self.last_messages[stream_id])
        else:
            logger.error(f"聊天流 {stream_id} 不在最后消息列表中，可能是新创建的")
        # 保存到内存和数据库
        self.streams[stream_id] = stream
        await self._save_stream(stream)
        return stream

    def get_stream(self, stream_id: str) -> Optional[ChatStream]:
        """通过stream_id获取聊天流"""
        stream = self.streams.get(stream_id)
        if not stream:
            return None
        if stream_id in self.last_messages:
            stream.set_context(self.last_messages[stream_id])
        return stream

    def get_stream_by_info(
        self, platform: str, user_info: UserInfo, group_info: Optional[GroupInfo] = None
    ) -> Optional[ChatStream]:
        """通过信息获取聊天流"""
        stream_id = self._generate_stream_id(platform, user_info, group_info)
        return self.streams.get(stream_id)

    def get_stream_name(self, stream_id: str) -> Optional[str]:
        """根据 stream_id 获取聊天流名称"""
        stream = self.get_stream(stream_id)
        if not stream:
            return None

        if stream.group_info and stream.group_info.group_name:
            return stream.group_info.group_name
        elif stream.user_info and stream.user_info.user_nickname:
            return f"{stream.user_info.user_nickname}的私聊"
        else:
            return None

    @staticmethod
    async def _save_stream(stream: ChatStream):
        """保存聊天流到数据库"""
        if stream.saved:
            return
        stream_data_dict = stream.to_dict()

        def _db_save_stream_sync(s_data_dict: dict):
            with get_db_session() as session:
                user_info_d = s_data_dict.get("user_info")
                group_info_d = s_data_dict.get("group_info")

                fields_to_save = {
                    "platform": s_data_dict["platform"],
                    "create_time": s_data_dict["create_time"],
                    "last_active_time": s_data_dict["last_active_time"],
                    "user_platform": user_info_d["platform"] if user_info_d else "",
                    "user_id": user_info_d["user_id"] if user_info_d else "",
                    "user_nickname": user_info_d["user_nickname"] if user_info_d else "",
                    "user_cardname": user_info_d.get("user_cardname", "") if user_info_d else None,
                    "group_platform": group_info_d["platform"] if group_info_d else "",
                    "group_id": group_info_d["group_id"] if group_info_d else "",
                    "group_name": group_info_d["group_name"] if group_info_d else "",
                    "energy_value": s_data_dict.get("energy_value", 5.0),
                    "sleep_pressure": s_data_dict.get("sleep_pressure", 0.0),
                    "focus_energy": s_data_dict.get("focus_energy", 0.5),
                    # 新增动态兴趣度系统字段
                    "base_interest_energy": s_data_dict.get("base_interest_energy", 0.5),
                    "message_interest_total": s_data_dict.get("message_interest_total", 0.0),
                    "message_count": s_data_dict.get("message_count", 0),
                    "action_count": s_data_dict.get("action_count", 0),
                    "reply_count": s_data_dict.get("reply_count", 0),
                    "last_interaction_time": s_data_dict.get("last_interaction_time", time.time()),
                    "consecutive_no_reply": s_data_dict.get("consecutive_no_reply", 0),
                    "interruption_count": s_data_dict.get("interruption_count", 0),
                }

                # 根据数据库类型选择插入语句
                if global_config.database.database_type == "sqlite":
                    stmt = sqlite_insert(ChatStreams).values(stream_id=s_data_dict["stream_id"], **fields_to_save)
                    stmt = stmt.on_conflict_do_update(index_elements=["stream_id"], set_=fields_to_save)
                elif global_config.database.database_type == "mysql":
                    stmt = mysql_insert(ChatStreams).values(stream_id=s_data_dict["stream_id"], **fields_to_save)
                    stmt = stmt.on_duplicate_key_update(
                        **{key: value for key, value in fields_to_save.items() if key != "stream_id"}
                    )
                else:
                    # 默认使用通用插入，尝试SQLite语法
                    stmt = sqlite_insert(ChatStreams).values(stream_id=s_data_dict["stream_id"], **fields_to_save)
                    stmt = stmt.on_conflict_do_update(index_elements=["stream_id"], set_=fields_to_save)

                session.execute(stmt)
                session.commit()

        try:
            await asyncio.to_thread(_db_save_stream_sync, stream_data_dict)
            stream.saved = True
        except Exception as e:
            logger.error(f"保存聊天流 {stream.stream_id} 到数据库失败 (Peewee): {e}", exc_info=True)

    async def _save_all_streams(self):
        """保存所有聊天流"""
        for stream in self.streams.values():
            await self._save_stream(stream)

    async def load_all_streams(self):
        """从数据库加载所有聊天流"""
        logger.info("正在从数据库加载所有聊天流")

        def _db_load_all_streams_sync():
            loaded_streams_data = []
            with get_db_session() as session:
                for model_instance in session.execute(select(ChatStreams)).scalars():
                    user_info_data = {
                        "platform": model_instance.user_platform,
                        "user_id": model_instance.user_id,
                        "user_nickname": model_instance.user_nickname,
                        "user_cardname": model_instance.user_cardname or "",
                    }
                    group_info_data = None
                    if model_instance and getattr(model_instance, "group_id", None):
                        group_info_data = {
                            "platform": model_instance.group_platform,
                            "group_id": model_instance.group_id,
                            "group_name": model_instance.group_name,
                        }

                    data_for_from_dict = {
                        "stream_id": model_instance.stream_id,
                        "platform": model_instance.platform,
                        "user_info": user_info_data,
                        "group_info": group_info_data,
                        "create_time": model_instance.create_time,
                        "last_active_time": model_instance.last_active_time,
                        "energy_value": model_instance.energy_value,
                        "sleep_pressure": model_instance.sleep_pressure,
                        "focus_energy": getattr(model_instance, "focus_energy", 0.5),
                        # 新增动态兴趣度系统字段 - 使用getattr提供默认值
                        "base_interest_energy": getattr(model_instance, "base_interest_energy", 0.5),
                        "message_interest_total": getattr(model_instance, "message_interest_total", 0.0),
                        "message_count": getattr(model_instance, "message_count", 0),
                        "action_count": getattr(model_instance, "action_count", 0),
                        "reply_count": getattr(model_instance, "reply_count", 0),
                        "last_interaction_time": getattr(model_instance, "last_interaction_time", time.time()),
                        "relationship_score": getattr(model_instance, "relationship_score", 0.3),
                        "consecutive_no_reply": getattr(model_instance, "consecutive_no_reply", 0),
                        "interruption_count": getattr(model_instance, "interruption_count", 0),
                    }
                    loaded_streams_data.append(data_for_from_dict)
                session.commit()
            return loaded_streams_data

        try:
            all_streams_data_list = await asyncio.to_thread(_db_load_all_streams_sync)
            self.streams.clear()
            for data in all_streams_data_list:
                stream = ChatStream.from_dict(data)
                stream.saved = True
                self.streams[stream.stream_id] = stream
                if stream.stream_id in self.last_messages:
                    stream.set_context(self.last_messages[stream.stream_id])
        except Exception as e:
            logger.error(f"从数据库加载所有聊天流失败 (Peewee): {e}", exc_info=True)


chat_manager = None


def get_chat_manager():
    global chat_manager
    if chat_manager is None:
        chat_manager = ChatManager()
    return chat_manager
