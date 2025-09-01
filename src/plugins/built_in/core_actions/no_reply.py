from typing import Tuple

# 导入新插件系统
from src.plugin_system import BaseAction, ActionActivationType, ChatMode

# 导入依赖的系统组件
from src.common.logger import get_logger


logger = get_logger("no_reply_action")


class NoReplyAction(BaseAction):
    """不回复动作，支持waiting和breaking两种形式."""

    focus_activation_type = ActionActivationType.ALWAYS  # 修复：在focus模式下应该始终可用
    normal_activation_type = ActionActivationType.ALWAYS  # 修复：在normal模式下应该始终可用
    mode_enable = ChatMode.FOCUS  # 修复：只在专注模式下有用
    parallel_action = False

    # 动作基本信息
    action_name = "no_reply"
    action_description = "暂时不回复消息"

    # 动作参数定义
    action_parameters = {
        "reason": "不回复的原因",
    }

    # 动作使用场景
    action_require = [""]

    # 关联类型
    associated_types = []

    async def execute(self) -> Tuple[bool, str]:
        """执行不回复动作"""

        try:
            reason = self.action_data.get("reason", "")

            logger.info(f"{self.log_prefix} 选择不回复，原因: {reason}")

            await self.store_action_info(
                action_build_into_prompt=False,
                action_prompt_display=reason,
                action_done=True,
            )
            return True, reason

        except Exception as e:
            logger.error(f"{self.log_prefix} 不回复动作执行失败: {e}")
            exit_reason = f"执行异常: {str(e)}"
            full_prompt = f"no_reply执行异常: {exit_reason}，你思考是否要进行回复"
            await self.store_action_info(
                action_build_into_prompt=True,
                action_prompt_display=full_prompt,
                action_done=True,
            )
            return False, f"不回复动作执行失败: {e}"
