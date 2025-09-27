import re
import traceback
import orjson
from typing import Union

from src.common.database.sqlalchemy_models import Messages, Images
from src.common.logger import get_logger
from .chat_stream import ChatStream
from .message import MessageSending, MessageRecv
from src.common.database.sqlalchemy_database_api import get_db_session
from sqlalchemy import select, update, desc

logger = get_logger("message_storage")


class MessageStorage:
    @staticmethod
    def _serialize_keywords(keywords) -> str:
        """将关键词列表序列化为JSON字符串"""
        if isinstance(keywords, list):
            return orjson.dumps(keywords).decode("utf-8")
        return "[]"

    @staticmethod
    def _deserialize_keywords(keywords_str: str) -> list:
        """将JSON字符串反序列化为关键词列表"""
        if not keywords_str:
            return []
        try:
            return orjson.loads(keywords_str)
        except (orjson.JSONDecodeError, TypeError):
            return []

    @staticmethod
    async def store_message(message: Union[MessageSending, MessageRecv], chat_stream: ChatStream) -> None:
        """存储消息到数据库"""
        try:
            # 过滤敏感信息的正则模式
            pattern = r"<MainRule>.*?</MainRule>|<schedule>.*?</schedule>|<UserMessage>.*?</UserMessage>"

            processed_plain_text = message.processed_plain_text

            if processed_plain_text:
                processed_plain_text = MessageStorage.replace_image_descriptions(processed_plain_text)
                filtered_processed_plain_text = re.sub(pattern, "", processed_plain_text, flags=re.DOTALL)
            else:
                filtered_processed_plain_text = ""

            if isinstance(message, MessageSending):
                display_message = message.display_message
                if display_message:
                    filtered_display_message = re.sub(pattern, "", display_message, flags=re.DOTALL)
                else:
                    # 如果没有设置display_message，使用processed_plain_text作为显示消息
                    filtered_display_message = re.sub(pattern, "", message.processed_plain_text, flags=re.DOTALL) if message.processed_plain_text else ""
                interest_value = 0
                is_mentioned = False
                reply_to = message.reply_to
                priority_mode = ""
                priority_info = {}
                is_emoji = False
                is_picid = False
                is_notify = False
                is_command = False
                key_words = ""
                key_words_lite = ""
            else:
                filtered_display_message = ""
                interest_value = message.interest_value
                is_mentioned = message.is_mentioned
                reply_to = ""
                priority_mode = message.priority_mode
                priority_info = message.priority_info
                is_emoji = message.is_emoji
                is_picid = message.is_picid
                is_notify = message.is_notify
                is_command = message.is_command
                # 序列化关键词列表为JSON字符串
                key_words = MessageStorage._serialize_keywords(message.key_words)
                key_words_lite = MessageStorage._serialize_keywords(message.key_words_lite)

            chat_info_dict = chat_stream.to_dict()
            user_info_dict = message.message_info.user_info.to_dict()  # type: ignore

            # message_id 现在是 TextField，直接使用字符串值
            msg_id = message.message_info.message_id

            # 安全地获取 group_info, 如果为 None 则视为空字典
            group_info_from_chat = chat_info_dict.get("group_info") or {}
            # 安全地获取 user_info, 如果为 None 则视为空字典 (以防万一)
            user_info_from_chat = chat_info_dict.get("user_info") or {}

            # 将priority_info字典序列化为JSON字符串，以便存储到数据库的Text字段
            priority_info_json = orjson.dumps(priority_info).decode("utf-8") if priority_info else None

            # 获取数据库会话

            new_message = Messages(
                message_id=msg_id,
                time=float(message.message_info.time),
                chat_id=chat_stream.stream_id,
                reply_to=reply_to,
                is_mentioned=is_mentioned,
                chat_info_stream_id=chat_info_dict.get("stream_id"),
                chat_info_platform=chat_info_dict.get("platform"),
                chat_info_user_platform=user_info_from_chat.get("platform"),
                chat_info_user_id=user_info_from_chat.get("user_id"),
                chat_info_user_nickname=user_info_from_chat.get("user_nickname"),
                chat_info_user_cardname=user_info_from_chat.get("user_cardname"),
                chat_info_group_platform=group_info_from_chat.get("platform"),
                chat_info_group_id=group_info_from_chat.get("group_id"),
                chat_info_group_name=group_info_from_chat.get("group_name"),
                chat_info_create_time=float(chat_info_dict.get("create_time", 0.0)),
                chat_info_last_active_time=float(chat_info_dict.get("last_active_time", 0.0)),
                user_platform=user_info_dict.get("platform"),
                user_id=user_info_dict.get("user_id"),
                user_nickname=user_info_dict.get("user_nickname"),
                user_cardname=user_info_dict.get("user_cardname"),
                processed_plain_text=filtered_processed_plain_text,
                display_message=filtered_display_message,
                memorized_times=message.memorized_times,
                interest_value=interest_value,
                priority_mode=priority_mode,
                priority_info=priority_info_json,
                is_emoji=is_emoji,
                is_picid=is_picid,
                is_notify=is_notify,
                is_command=is_command,
                key_words=key_words,
                key_words_lite=key_words_lite,
            )
            with get_db_session() as session:
                session.add(new_message)
                session.commit()

        except Exception:
            logger.exception("存储消息失败")
            logger.error(f"消息：{message}")
            traceback.print_exc()

    @staticmethod
    async def update_message(message):
        """更新消息ID"""
        try:
            mmc_message_id = message.message_info.message_id
            qq_message_id = None

            logger.debug(f"尝试更新消息ID: {mmc_message_id}, 消息段类型: {message.message_segment.type}")

            # 根据消息段类型提取message_id
            if message.message_segment.type == "notify":
                qq_message_id = message.message_segment.data.get("id")
            elif message.message_segment.type == "text":
                qq_message_id = message.message_segment.data.get("id")
            elif message.message_segment.type == "reply":
                qq_message_id = message.message_segment.data.get("id")
                if qq_message_id:
                    logger.debug(f"从reply消息段获取到消息ID: {qq_message_id}")
            elif message.message_segment.type == "adapter_response":
                logger.debug("适配器响应消息，不需要更新ID")
                return
            elif message.message_segment.type == "adapter_command":
                logger.debug("适配器命令消息，不需要更新ID")
                return
            else:
                logger.debug(f"未知的消息段类型: {message.message_segment.type}，跳过ID更新")
                return

            if not qq_message_id:
                logger.debug(f"消息段类型 {message.message_segment.type} 中未找到有效的message_id，跳过更新")
                logger.debug(f"消息段数据: {message.message_segment.data}")
                return

            # 使用上下文管理器确保session正确管理
            from src.common.database.sqlalchemy_models import get_db_session

            with get_db_session() as session:
                matched_message = session.execute(
                    select(Messages).where(Messages.message_id == mmc_message_id).order_by(desc(Messages.time))
                ).scalar()

                if matched_message:
                    session.execute(
                        update(Messages).where(Messages.id == matched_message.id).values(message_id=qq_message_id)
                    )
                    logger.debug(f"更新消息ID成功: {matched_message.message_id} -> {qq_message_id}")
                else:
                    logger.warning(f"未找到匹配的消息记录: {mmc_message_id}")

        except Exception as e:
            logger.error(f"更新消息ID失败: {e}")
            logger.error(
                f"消息信息: message_id={getattr(message.message_info, 'message_id', 'N/A')}, "
                f"segment_type={getattr(message.message_segment, 'type', 'N/A')}"
            )

    @staticmethod
    def replace_image_descriptions(text: str) -> str:
        """将[图片：描述]替换为[picid:image_id]"""
        # 先检查文本中是否有图片标记
        pattern = r"\[图片：([^\]]+)\]"
        matches = re.findall(pattern, text)

        if not matches:
            logger.debug("文本中没有图片标记，直接返回原文本")
            return text

        def replace_match(match):
            description = match.group(1).strip()
            try:
                from src.common.database.sqlalchemy_models import get_db_session

                with get_db_session() as session:
                    image_record = session.execute(
                        select(Images).where(Images.description == description).order_by(desc(Images.timestamp))
                    ).scalar()
                    return f"[picid:{image_record.image_id}]" if image_record else match.group(0)
            except Exception:
                return match.group(0)

    @staticmethod
    def update_message_interest_value(message_id: str, interest_value: float) -> None:
        """
        更新数据库中消息的interest_value字段

        Args:
            message_id: 消息ID
            interest_value: 兴趣度值
        """
        try:
            with get_db_session() as session:
                # 更新消息的interest_value字段
                stmt = update(Messages).where(Messages.message_id == message_id).values(interest_value=interest_value)
                result = session.execute(stmt)
                session.commit()

                if result.rowcount > 0:
                    logger.debug(f"成功更新消息 {message_id} 的interest_value为 {interest_value}")
                else:
                    logger.warning(f"未找到消息 {message_id}，无法更新interest_value")

        except Exception as e:
            logger.error(f"更新消息 {message_id} 的interest_value失败: {e}")
            raise

    @staticmethod
    def fix_zero_interest_values(chat_id: str, since_time: float) -> int:
        """
        修复指定聊天中interest_value为0或null的历史消息记录

        Args:
            chat_id: 聊天ID
            since_time: 从指定时间开始修复（时间戳）

        Returns:
            修复的记录数量
        """
        try:
            with get_db_session() as session:
                from sqlalchemy import select, update
                from src.common.database.sqlalchemy_models import Messages

                # 查找需要修复的记录：interest_value为0、null或很小的值
                query = select(Messages).where(
                    (Messages.chat_id == chat_id) &
                    (Messages.time >= since_time) &
                    (
                        (Messages.interest_value == 0) |
                        (Messages.interest_value.is_(None)) |
                        (Messages.interest_value < 0.1)
                    )
                ).limit(50)  # 限制每次修复的数量，避免性能问题

                messages_to_fix = session.execute(query).scalars().all()
                fixed_count = 0

                for msg in messages_to_fix:
                    # 为这些消息设置一个合理的默认兴趣度
                    # 可以基于消息长度、内容或其他因素计算
                    default_interest = 0.3  # 默认中等兴趣度

                    # 如果消息内容较长，可能是重要消息，兴趣度稍高
                    if hasattr(msg, 'processed_plain_text') and msg.processed_plain_text:
                        text_length = len(msg.processed_plain_text)
                        if text_length > 50:  # 长消息
                            default_interest = 0.4
                        elif text_length > 20:  # 中等长度消息
                            default_interest = 0.35

                    # 如果是被@的消息，兴趣度更高
                    if getattr(msg, 'is_mentioned', False):
                        default_interest = min(default_interest + 0.2, 0.8)

                    # 执行更新
                    update_stmt = update(Messages).where(
                        Messages.message_id == msg.message_id
                    ).values(interest_value=default_interest)

                    result = session.execute(update_stmt)
                    if result.rowcount > 0:
                        fixed_count += 1
                        logger.debug(f"修复消息 {msg.message_id} 的interest_value为 {default_interest}")

                session.commit()
                logger.info(f"共修复了 {fixed_count} 条历史消息的interest_value值")
                return fixed_count

        except Exception as e:
            logger.error(f"修复历史消息interest_value失败: {e}")
            return 0
