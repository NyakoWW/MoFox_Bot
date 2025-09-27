"""
兴趣度系统模块
提供机器人兴趣标签和智能匹配功能
"""

from .bot_interest_manager import BotInterestManager, bot_interest_manager
from src.common.data_models.bot_interest_data_model import BotInterestTag, BotPersonalityInterests, InterestMatchResult

__all__ = [
    "BotInterestManager",
    "bot_interest_manager",
    "BotInterestTag",
    "BotPersonalityInterests",
    "InterestMatchResult",
]
