"""
PlanGenerator: 负责搜集和汇总所有决策所需的信息，生成一个未经筛选的"原始计划" (Plan)。
"""

import time
from typing import Dict

from src.chat.utils.chat_message_builder import get_raw_msg_before_timestamp_with_chat
from src.chat.utils.utils import get_chat_type_and_target_info
from src.common.data_models.database_data_model import DatabaseMessages
from src.common.data_models.info_data_model import Plan, TargetPersonInfo
from src.config.config import global_config
from src.plugin_system.base.component_types import ActionInfo, ChatMode, ChatType
from src.plugin_system.core.component_registry import component_registry


class ChatterPlanGenerator:
    """
    ChatterPlanGenerator 负责在规划流程的初始阶段收集所有必要信息。

    它会汇总以下信息来构建一个"原始"的 Plan 对象，该对象后续会由 PlanFilter 进行筛选：
    -   当前聊天信息 (ID, 目标用户)
    -   当前可用的动作列表
    -   最近的聊天历史记录

    Attributes:
        chat_id (str): 当前聊天的唯一标识符。
        action_manager (ActionManager): 用于获取可用动作列表的管理器。
    """

    def __init__(self, chat_id: str):
        """
        初始化 ChatterPlanGenerator。

        Args:
            chat_id (str): 当前聊天的 ID。
        """
        from src.chat.planner_actions.action_manager import ChatterActionManager

        self.chat_id = chat_id
        # 注意：ChatterActionManager 可能需要根据实际情况初始化
        self.action_manager = ChatterActionManager()

    async def generate(self, mode: ChatMode) -> Plan:
        """
        收集所有信息，生成并返回一个初始的 Plan 对象。

        这个 Plan 对象包含了决策所需的所有上下文信息。

        Args:
            mode (ChatMode): 当前的聊天模式。

        Returns:
            Plan: 包含所有上下文信息的初始计划对象。
        """
        try:
            # 获取聊天类型和目标信息
            chat_type, target_info = get_chat_type_and_target_info(self.chat_id)

            # 获取可用动作列表
            available_actions = await self._get_available_actions(chat_type, mode)

            # 获取聊天历史记录
            recent_messages = await self._get_recent_messages()

            # 构建计划对象
            plan = Plan(
                chat_id=self.chat_id,
                chat_type=chat_type,
                mode=mode,
                target_info=target_info,
                available_actions=available_actions,
                chat_history=recent_messages,
            )

            return plan

        except Exception:
            # 如果生成失败，返回一个基本的空计划
            return Plan(
                chat_id=self.chat_id,
                mode=mode,
                target_info=TargetPersonInfo(),
                available_actions={},
                chat_history=[],
            )

    async def _get_available_actions(self, chat_type: ChatType, mode: ChatMode) -> Dict[str, ActionInfo]:
        """
        获取当前可用的动作列表。

        Args:
            chat_type (ChatType): 聊天类型。
            mode (ChatMode): 聊天模式。

        Returns:
            Dict[str, ActionInfo]: 可用动作的字典。
        """
        try:
            # 从组件注册表获取可用动作
            available_actions = component_registry.get_enabled_actions()

            # 根据聊天类型和模式筛选动作
            filtered_actions = {}
            for action_name, action_info in available_actions.items():
                # 检查动作是否支持当前聊天类型
                if chat_type in action_info.chat_types:
                    # 检查动作是否支持当前模式
                    if mode in action_info.chat_modes:
                        filtered_actions[action_name] = action_info

            return filtered_actions

        except Exception:
            # 如果获取失败，返回空字典
            return {}

    async def _get_recent_messages(self) -> list[DatabaseMessages]:
        """
        获取最近的聊天历史记录。

        Returns:
            list[DatabaseMessages]: 最近的聊天消息列表。
        """
        try:
            # 获取最近的消息记录
            raw_messages = get_raw_msg_before_timestamp_with_chat(
                chat_id=self.chat_id, timestamp=time.time(), limit=global_config.memory.short_memory_length
            )

            # 转换为 DatabaseMessages 对象
            recent_messages = []
            for msg in raw_messages:
                try:
                    db_msg = DatabaseMessages(
                        message_id=msg.get("message_id", ""),
                        time=float(msg.get("time", 0)),
                        chat_id=msg.get("chat_id", ""),
                        processed_plain_text=msg.get("processed_plain_text", ""),
                        user_id=msg.get("user_id", ""),
                        user_nickname=msg.get("user_nickname", ""),
                        user_platform=msg.get("user_platform", ""),
                    )
                    recent_messages.append(db_msg)
                except Exception:
                    # 跳过格式错误的消息
                    continue

            return recent_messages

        except Exception:
            # 如果获取失败，返回空列表
            return []

    def get_generator_stats(self) -> Dict:
        """
        获取生成器统计信息。

        Returns:
            Dict: 统计信息字典。
        """
        return {
            "chat_id": self.chat_id,
            "action_count": len(self.action_manager._using_actions)
            if hasattr(self.action_manager, "_using_actions")
            else 0,
            "generation_time": time.time(),
        }
