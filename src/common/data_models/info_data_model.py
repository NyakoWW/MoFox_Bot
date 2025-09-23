from dataclasses import dataclass, field
from typing import Optional, Dict, List, TYPE_CHECKING

from . import BaseDataModel

if TYPE_CHECKING:
    pass


@dataclass
class TargetPersonInfo(BaseDataModel):
    platform: str = field(default_factory=str)
    user_id: str = field(default_factory=str)
    user_nickname: str = field(default_factory=str)
    person_id: Optional[str] = None
    person_name: Optional[str] = None


@dataclass
class ActionPlannerInfo(BaseDataModel):
    action_type: str = field(default_factory=str)
    reasoning: Optional[str] = None
    action_data: Optional[Dict] = None
    action_message: Optional[Dict] = None
    available_actions: Optional[Dict[str, "ActionInfo"]] = None


@dataclass
class Plan(BaseDataModel):
    """
    统一规划数据模型
    """
    chat_id: str
    mode: "ChatMode"
    
    # Generator 填充
    available_actions: Dict[str, "ActionInfo"] = field(default_factory=dict)
    chat_history: List["DatabaseMessages"] = field(default_factory=list)
    target_info: Optional[TargetPersonInfo] = None
    
    # Filter 填充
    llm_prompt: Optional[str] = None
    decided_actions: Optional[List[ActionPlannerInfo]] = None
