import time
from typing import List, Optional, TYPE_CHECKING

from src.chat.chat_loop.hfc_utils import CycleDetail
from src.chat.express.expression_learner import ExpressionLearner
from src.chat.message_receive.chat_stream import ChatStream, get_chat_manager
from src.chat.planner_actions.action_manager import ActionManager
from src.config.config import global_config
from src.person_info.relationship_builder_manager import RelationshipBuilder

if TYPE_CHECKING:
    pass


class HfcContext:
    def __init__(self, chat_id: str):
        """
        初始化HFC聊天上下文

        Args:
            chat_id: 聊天ID标识符

        功能说明:
        - 存储和管理单个聊天会话的所有状态信息
        - 包含聊天流、关系构建器、表达学习器等核心组件
        - 管理聊天模式、能量值、时间戳等关键状态
        - 提供循环历史记录和当前循环详情的存储
        - 集成唤醒度管理器，处理休眠状态下的唤醒机制

        Raises:
            ValueError: 如果找不到对应的聊天流
        """
        self.stream_id: str = chat_id
        self.chat_stream: Optional[ChatStream] = get_chat_manager().get_stream(self.stream_id)
        if not self.chat_stream:
            raise ValueError(f"无法找到聊天流: {self.stream_id}")

        self.log_prefix = f"[{get_chat_manager().get_stream_name(self.stream_id) or self.stream_id}]"

        self.relationship_builder: Optional[RelationshipBuilder] = None
        self.expression_learner: Optional[ExpressionLearner] = None

        self.energy_value = self.chat_stream.energy_value
        self.sleep_pressure = self.chat_stream.sleep_pressure
        self.was_sleeping = False  # 用于检测睡眠状态的切换

        self.last_message_time = time.time()
        self.last_read_time = time.time() - 10

        # 从聊天流恢复breaking累积兴趣值
        self.breaking_accumulated_interest = getattr(self.chat_stream, "breaking_accumulated_interest", 0.0)

        self.action_manager = ActionManager()

        self.running: bool = False

        self.history_loop: List[CycleDetail] = []
        self.cycle_counter = 0
        self.current_cycle_detail: Optional[CycleDetail] = None

        # 唤醒度管理器 - 延迟初始化以避免循环导入
        self.wakeup_manager: Optional["WakeUpManager"] = None
        self.energy_manager: Optional["EnergyManager"] = None
        self.sleep_manager: Optional["SleepManager"] = None

        # 从聊天流获取focus_energy，如果没有则使用配置文件中的值
        self.focus_energy = getattr(self.chat_stream, "focus_energy", global_config.chat.focus_value)
        self.no_reply_consecutive = 0
        self.total_interest = 0.0
        # breaking形式下的累积兴趣值
        self.breaking_accumulated_interest = 0.0
        # 引用HeartFChatting实例，以便其他组件可以调用其方法
        self.chat_instance: "HeartFChatting"

    def save_context_state(self):
        """将当前状态保存到聊天流"""
        if self.chat_stream:
            self.chat_stream.energy_value = self.energy_value
            self.chat_stream.sleep_pressure = self.sleep_pressure
            self.chat_stream.focus_energy = self.focus_energy
            self.chat_stream.no_reply_consecutive = self.no_reply_consecutive
            self.chat_stream.breaking_accumulated_interest = self.breaking_accumulated_interest
