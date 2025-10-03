from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from src.chat.planner_actions.action_manager import ChatterActionManager
from src.common.data_models.message_manager_data_model import StreamContext
from src.plugin_system.base.component_types import ChatterInfo, ComponentType

from .component_types import ChatType


@dataclass
class BaseChatter(ABC):
    """聊天处理器抽象类"""

    stream_id: str
    """聊天流ID"""
    action_manager: ChatterActionManager
    """动作管理器"""
    chatter_name: str = field(default="")
    """Chatter组件的名称"""
    chatter_description: str = field(default="")
    """Chatter组件的描述"""
    chat_types: list[ChatType] = field(default_factory=lambda: [ChatType.PRIVATE, ChatType.GROUP])
    """Chatter组件支持的聊天类型"""

    @abstractmethod
    async def execute(self, context: StreamContext) -> dict:
        """
        执行聊天处理流程

        Args:
            context: StreamContext对象，包含聊天流的所有消息信息

        Returns:
            处理结果字典
        """
        pass

    @classmethod
    def get_chatter_info(cls) -> "ChatterInfo":
        """从类属性生成ChatterInfo
        Returns:
            ChatterInfo对象
        """

        return ChatterInfo(
            name=cls.chatter_name,
            description=cls.chatter_description or "No description provided.",
            chat_type_allow=cls.chat_types[0],
            component_type=ComponentType.CHATTER,
        )
