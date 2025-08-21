import asyncio
import time
import traceback
import random
from typing import List, Optional, Dict, Any, Tuple
from rich.traceback import install

from src.config.config import global_config
from src.common.logger import get_logger
from src.chat.message_receive.chat_stream import ChatStream, get_chat_manager
from src.chat.utils.prompt_builder import global_prompt_manager
from src.chat.utils.timer_calculator import Timer
from src.chat.planner_actions.planner import ActionPlanner
from src.chat.planner_actions.action_modifier import ActionModifier
from src.chat.planner_actions.action_manager import ActionManager
from src.chat.chat_loop.hfc_utils import CycleDetail
from src.person_info.relationship_builder_manager import relationship_builder_manager
from src.chat.express.expression_learner import expression_learner_manager
from src.person_info.person_info import get_person_info_manager
from src.plugin_system.base.component_types import ActionInfo, ChatMode, EventType
from src.plugin_system.core import events_manager
from src.plugin_system.apis import generator_api, send_api, message_api, database_api
from src.chat.willing.willing_manager import get_willing_manager
from src.mais4u.mai_think import mai_thinking_manager
from src.mais4u.constant_s4u import ENABLE_S4U
from src.chat.chat_loop.hfc_utils import send_typing, stop_typing

ERROR_LOOP_INFO = {
    "loop_plan_info": {
        "action_result": {
            "action_type": "error",
            "action_data": {},
            "reasoning": "循环处理失败",
        },
    },
    "loop_action_info": {
        "action_taken": False,
        "reply_text": "",
        "command": "",
        "taken_time": time.time(),
    },
}

NO_ACTION = {
    "action_result": {
        "action_type": "no_action",
        "action_data": {},
        "reasoning": "规划器初始化默认",
        "is_parallel": True,
    },
    "chat_context": "",
    "action_prompt": "",
}

install(extra_lines=3)

# 注释：原来的动作修改超时常量已移除，因为改为顺序执行

logger = get_logger("hfc")  # Logger Name Changed


class HeartFChatting:
    """
    管理一个连续的Focus Chat循环
    用于在特定聊天流中生成回复。
    其生命周期现在由其关联的 SubHeartflow 的 FOCUSED 状态控制。
    """
    VALID_PROACTIVE_SCOPES = {"private", "group", "all"}

    def __init__(
        self,
        chat_id: str,
    ):
        """
        HeartFChatting 初始化函数

        参数:
            chat_id: 聊天流唯一标识符(如stream_id)
            on_stop_focus_chat: 当收到stop_focus_chat命令时调用的回调函数
            performance_version: 性能记录版本号，用于区分不同启动版本
        """
        # 基础属性
        self.stream_id: str = chat_id  # 聊天流ID
        self.chat_stream: ChatStream = get_chat_manager().get_stream(self.stream_id)  # type: ignore
        if not self.chat_stream:
            raise ValueError(f"无法找到聊天流: {self.stream_id}")
        self.log_prefix = f"[{get_chat_manager().get_stream_name(self.stream_id) or self.stream_id}]"

        self.relationship_builder = relationship_builder_manager.get_or_create_builder(self.stream_id)
        self.expression_learner = expression_learner_manager.get_expression_learner(self.stream_id)

        self.loop_mode = ChatMode.NORMAL  # 初始循环模式为普通模式

        self.last_action = "no_action"

        self.action_manager = ActionManager()
        self.action_planner = ActionPlanner(chat_id=self.stream_id, action_manager=self.action_manager)
        self.action_modifier = ActionModifier(action_manager=self.action_manager, chat_id=self.stream_id)

        # 循环控制内部状态
        self.running: bool = False
        self._loop_task: Optional[asyncio.Task] = None  # 主循环任务
        self._energy_task: Optional[asyncio.Task] = None

        # 添加循环信息管理相关的属性
        self.history_loop: List[CycleDetail] = []
        self._cycle_counter = 0
        self._current_cycle_detail: CycleDetail = None  # type: ignore

        self.reply_timeout_count = 0
        self.plan_timeout_count = 0

        self.last_read_time = time.time() - 1

        self.willing_manager = get_willing_manager()

        logger.info(f"{self.log_prefix} HeartFChatting 初始化完成")

        self.energy_value = 5

        # 根据配置初始化聊天模式和能量值
        is_group_chat = self.chat_stream.group_info is not None
        if is_group_chat and global_config.chat.group_chat_mode != "auto":
            if global_config.chat.group_chat_mode == "focus":
                self.loop_mode = ChatMode.FOCUS
                self.energy_value = 35
                logger.info(f"{self.log_prefix} 群聊强制专注模式已启用，能量值设置为35")
            elif global_config.chat.group_chat_mode == "normal":
                self.loop_mode = ChatMode.NORMAL
                self.energy_value = 15
                logger.info(f"{self.log_prefix} 群聊强制普通模式已启用，能量值设置为15")

        self.focus_energy = 1

        # 能量值日志时间控制
        self.last_energy_log_time = 0  # 上次记录能量值日志的时间
        self.energy_log_interval = 90  # 能量值日志间隔（秒）

        # 主动思考功能相关属性
        self.last_message_time = time.time()  # 最后一条消息的时间
        self._proactive_thinking_task: Optional[asyncio.Task] = None  # 主动思考任务

        self.proactive_thinking_prompts = {
            "private": """现在你和你朋友的私聊里面已经隔了{time}没有发送消息了，请你结合上下文以及你和你朋友之前聊过的话题和你的人设来决定要不要主动发送消息，你可以选择：

            1. 继续保持沉默（当{time}以前已经结束了一个话题并且你不想挑起新话题时）
            2. 选择回复（当{time}以前你发送了一条消息且没有人回复你时、你想主动挑起一个话题时）

            请根据当前情况做出选择。如果选择回复，请直接发送你想说的内容；如果选择保持沉默，请只回复"沉默"（注意：这个词不会被发送到群聊中）。""",
            "group": """现在群里面已经隔了{time}没有人发送消息了，请你结合上下文以及群聊里面之前聊过的话题和你的人设来决定要不要主动发送消息，你可以选择：

            1. 继续保持沉默（当{time}以前已经结束了一个话题并且你不想挑起新话题时）
            2. 选择回复（当{time}以前你发送了一条消息且没有人回复你时、你想主动挑起一个话题时）

            请根据当前情况做出选择。如果选择回复，请直接发送你想说的内容；如果选择保持沉默，请只回复"沉默"（注意：这个词不会被发送到群聊中）。""",
        }
        
        # 主动思考配置 - 支持新旧配置格式
        self.proactive_thinking_chat_scope = global_config.chat.The_scope_that_proactive_thinking_can_trigger
        if self.proactive_thinking_chat_scope not in self.VALID_PROACTIVE_SCOPES:
            logger.error(f"无效的主动思考范围: '{self.proactive_thinking_chat_scope}'。有效值为: {self.VALID_PROACTIVE_SCOPES}")
            raise ValueError(f"配置错误：无效的主动思考范围 '{self.proactive_thinking_chat_scope}'") #乱填参数是吧,我跟你爆了
        
        # 新的配置项 - 分离的私聊/群聊控制
        self.proactive_thinking_in_private = global_config.chat.proactive_thinking_in_private
        self.proactive_thinking_in_group = global_config.chat.proactive_thinking_in_group
        
        # ID列表控制（支持新旧两个字段）
        self.proactive_thinking_ids = []
        if hasattr(global_config.chat, 'enable_ids') and global_config.chat.enable_ids:
            self.proactive_thinking_ids = global_config.chat.enable_ids
        elif hasattr(global_config.chat, 'proactive_thinking_enable_ids') and global_config.chat.proactive_thinking_enable_ids:
            self.proactive_thinking_ids = global_config.chat.proactive_thinking_enable_ids
        
        # 正态分布时间间隔配置
        self.delta_sigma = getattr(global_config.chat, 'delta_sigma', 120)
        
        # 打印主动思考配置信息
        logger.info(f"{self.log_prefix} 主动思考配置: 启用={global_config.chat.enable_proactive_thinking}, "
                   f"旧范围={self.proactive_thinking_chat_scope}, 私聊={self.proactive_thinking_in_private}, "
                   f"群聊={self.proactive_thinking_in_group}, ID列表={self.proactive_thinking_ids}, "
                   f"基础间隔={global_config.chat.proactive_thinking_interval}s, Delta={self.delta_sigma}")

    async def start(self):
        """检查是否需要启动主循环，如果未激活则启动。"""

        # 如果循环已经激活，直接返回
        if self.running:
            logger.debug(f"{self.log_prefix} HeartFChatting 已激活，无需重复启动")
            return

        try:
            # 标记为活动状态，防止重复启动
            self.running = True

            self._energy_task = asyncio.create_task(self._energy_loop())
            self._energy_task.add_done_callback(self._handle_energy_completion)

            # 启动主动思考任务
            if global_config.chat.enable_proactive_thinking:
                self._proactive_thinking_task = asyncio.create_task(self._proactive_thinking_loop())
                self._proactive_thinking_task.add_done_callback(self._handle_proactive_thinking_completion)

            self._loop_task = asyncio.create_task(self._main_chat_loop())
            self._loop_task.add_done_callback(self._handle_loop_completion)
            logger.info(f"{self.log_prefix} HeartFChatting 启动完成")

        except Exception as e:
            # 启动失败时重置状态
            self.running = False
            self._loop_task = None
            logger.error(f"{self.log_prefix} HeartFChatting 启动失败: {e}")
            raise

    def _handle_loop_completion(self, task: asyncio.Task):
        """当 _hfc_loop 任务完成时执行的回调。"""
        try:
            if exception := task.exception():
                logger.error(f"{self.log_prefix} HeartFChatting: 脱离了聊天(异常): {exception}")
                logger.error(traceback.format_exc())  # Log full traceback for exceptions
            else:
                logger.info(f"{self.log_prefix} HeartFChatting: 脱离了聊天 (外部停止)")
        except asyncio.CancelledError:
            logger.info(f"{self.log_prefix} HeartFChatting: 结束了聊天")

    def start_cycle(self):
        self._cycle_counter += 1
        self._current_cycle_detail = CycleDetail(self._cycle_counter)
        self._current_cycle_detail.thinking_id = f"tid{str(round(time.time(), 2))}"
        cycle_timers = {}
        return cycle_timers, self._current_cycle_detail.thinking_id

    def end_cycle(self, loop_info, cycle_timers):
        self._current_cycle_detail.set_loop_info(loop_info)
        self.history_loop.append(self._current_cycle_detail)
        self._current_cycle_detail.timers = cycle_timers
        self._current_cycle_detail.end_time = time.time()

    def _handle_energy_completion(self, task: asyncio.Task):
        """当 energy_loop 任务完成时执行的回调。"""
        try:
            if exception := task.exception():
                logger.error(f"{self.log_prefix} 能量循环异常: {exception}")
            else:
                logger.info(f"{self.log_prefix} 能量循环正常结束")
        except asyncio.CancelledError:
            logger.info(f"{self.log_prefix} 能量循环被取消")

    def _handle_proactive_thinking_completion(self, task: asyncio.Task):
        """当 proactive_thinking_loop 任务完成时执行的回调。"""
        try:
            if exception := task.exception():
                logger.error(f"{self.log_prefix} 主动思考循环异常: {exception}")
            else:
                logger.info(f"{self.log_prefix} 主动思考循环正常结束")
        except asyncio.CancelledError:
            logger.info(f"{self.log_prefix} 主动思考循环被取消")
        """处理能量循环任务的完成"""
        if task.cancelled():
            logger.info(f"{self.log_prefix} 能量循环任务被取消")
        elif task.exception():
            logger.error(f"{self.log_prefix} 能量循环任务发生异常: {task.exception()}")

    def _should_log_energy(self) -> bool:
        """判断是否应该记录能量值日志（基于时间间隔控制）"""
        current_time = time.time()
        if current_time - self.last_energy_log_time >= self.energy_log_interval:
            self.last_energy_log_time = current_time
            return True
        return False

    def _log_energy_change(self, action: str, reason: str = ""):
        """记录能量值变化日志（受时间间隔控制）"""
        if self._should_log_energy():
            if reason:
                logger.info(f"{self.log_prefix} {action}，{reason}，当前能量值：{self.energy_value:.1f}")
            else:
                logger.info(f"{self.log_prefix} {action}，当前能量值：{self.energy_value:.1f}")
        else:
            # 仍然以debug级别记录，便于调试
            if reason:
                logger.debug(f"{self.log_prefix} {action}，{reason}，当前能量值：{self.energy_value:.1f}")
            else:
                logger.debug(f"{self.log_prefix} {action}，当前能量值：{self.energy_value:.1f}")

    async def _energy_loop(self):
        while self.running:
            await asyncio.sleep(10)

            # 检查是否为群聊且配置了强制模式
            is_group_chat = self.chat_stream.group_info is not None
            if is_group_chat and global_config.chat.group_chat_mode != "auto":
                # 强制模式下固定能量值和聊天模式
                if global_config.chat.group_chat_mode == "focus":
                    self.loop_mode = ChatMode.FOCUS
                    self.energy_value = 35  # 强制设置为35
                elif global_config.chat.group_chat_mode == "normal":
                    self.loop_mode = ChatMode.NORMAL
                    self.energy_value = 15  # 强制设置为15
                continue  # 跳过正常的能量值衰减逻辑

            # 原有的自动模式逻辑
            if self.loop_mode == ChatMode.NORMAL:
                self.energy_value -= 0.3
                self.energy_value = max(self.energy_value, 0.3)
            if self.loop_mode == ChatMode.FOCUS:
                self.energy_value -= 0.6
                self.energy_value = max(self.energy_value, 0.3)

    async def _proactive_thinking_loop(self):
        """主动思考循环，仅在focus模式下生效"""
        while self.running:
            await asyncio.sleep(15)  # 每15秒检查一次

            # 只在focus模式下进行主动思考
            if self.loop_mode != ChatMode.FOCUS:
                continue
            
            # 检查是否应该在当前聊天类型中启用主动思考
            if not self._should_enable_proactive_thinking():
                continue

            current_time = time.time()
            silence_duration = current_time - self.last_message_time

            # 使用正态分布计算动态间隔时间
            target_interval = self._get_dynamic_thinking_interval()
            
            # 检查是否达到主动思考的时间间隔
            if silence_duration >= target_interval:
                try:
                    await self._execute_proactive_thinking(silence_duration)
                    # 重置计时器，避免频繁触发
                    self.last_message_time = current_time
                except Exception as e:
                    logger.error(f"{self.log_prefix} 主动思考执行出错: {e}")
                    logger.error(traceback.format_exc())
    
    def _should_enable_proactive_thinking(self) -> bool:
        """检查是否应该在当前聊天中启用主动思考"""
        # 获取当前聊天ID
        chat_id = None
        if hasattr(self.chat_stream, 'chat_id'):
            chat_id = int(self.chat_stream.chat_id)
        
        # 如果指定了ID列表，只在列表中的聊天启用
        if self.proactive_thinking_ids:
            if chat_id is None or chat_id not in self.proactive_thinking_ids:
                return False
        
        # 检查聊天类型（私聊/群聊）控制
        is_group_chat = self.chat_stream.group_info is not None
        
        if is_group_chat:
            # 群聊：检查群聊启用开关
            if not self.proactive_thinking_in_group:
                return False
        else:
            # 私聊：检查私聊启用开关  
            if not self.proactive_thinking_in_private:
                return False
        
        # 兼容旧的范围配置
        if self.proactive_thinking_chat_scope == "group" and not is_group_chat:
            return False
        if self.proactive_thinking_chat_scope == "private" and is_group_chat:
            return False
            
        return True
    
    def _get_dynamic_thinking_interval(self) -> float:
        """获取动态的主动思考间隔时间（使用正态分布和3-sigma规则）"""
        try:
            from src.utils.timing_utils import get_normal_distributed_interval
            
            base_interval = global_config.chat.proactive_thinking_interval
            
            # 🚨 保险机制：处理负数配置
            if base_interval < 0:
                logger.warning(f"{self.log_prefix} proactive_thinking_interval设置为{base_interval}为负数，使用绝对值{abs(base_interval)}")
                base_interval = abs(base_interval)
            
            if self.delta_sigma < 0:
                logger.warning(f"{self.log_prefix} delta_sigma设置为{self.delta_sigma}为负数，使用绝对值{abs(self.delta_sigma)}")
                delta_sigma = abs(self.delta_sigma)
            else:
                delta_sigma = self.delta_sigma
            
            # 🚨 特殊情况处理
            if base_interval == 0 and delta_sigma == 0:
                logger.warning(f"{self.log_prefix} 基础间隔和Delta都为0，强制使用300秒安全间隔")
                return 300
            elif base_interval == 0:
                # 基础间隔为0，但有delta_sigma，基于delta_sigma生成随机间隔
                logger.info(f"{self.log_prefix} 基础间隔为0，使用纯随机模式，基于delta_sigma={delta_sigma}")
                sigma_percentage = delta_sigma / 1000  # 假设1000秒作为虚拟基准
                result = get_normal_distributed_interval(0, sigma_percentage, 1, 86400, use_3sigma_rule=True)
                logger.debug(f"{self.log_prefix} 纯随机模式生成间隔: {result}秒")
                return result
            elif delta_sigma == 0:
                # 禁用正态分布，使用固定间隔
                logger.debug(f"{self.log_prefix} delta_sigma=0，禁用正态分布，使用固定间隔{base_interval}秒")
                return base_interval
            
            # 正常情况：使用3-sigma规则的正态分布
            sigma_percentage = delta_sigma / base_interval
            
            # 3-sigma边界计算
            sigma = delta_sigma
            three_sigma_range = 3 * sigma
            theoretical_min = max(1, base_interval - three_sigma_range)
            theoretical_max = base_interval + three_sigma_range
            
            logger.debug(f"{self.log_prefix} 3-sigma分布: 基础={base_interval}s, σ={sigma}s, "
                        f"理论范围=[{theoretical_min:.0f}, {theoretical_max:.0f}]s")
            
            # 给用户最大自由度：使用3-sigma规则但不强制限制范围
            result = get_normal_distributed_interval(
                base_interval, 
                sigma_percentage, 
                1,  # 最小1秒
                86400,  # 最大24小时
                use_3sigma_rule=True
            )
            
            return result
            
        except ImportError:
            # 如果timing_utils不可用，回退到固定间隔
            logger.warning(f"{self.log_prefix} timing_utils不可用，使用固定间隔")
            return max(300, abs(global_config.chat.proactive_thinking_interval))
        except Exception as e:
            # 如果计算出错，回退到固定间隔
            logger.error(f"{self.log_prefix} 动态间隔计算出错: {e}，使用固定间隔")
            return max(300, abs(global_config.chat.proactive_thinking_interval))
    
    def _generate_random_interval_from_sigma(self, sigma: float) -> float:
        """基于sigma值生成纯随机间隔（当基础间隔为0时使用）"""
        try:
            import numpy as np
            
            # 使用sigma作为标准差，0作为均值生成正态分布
            interval = abs(np.random.normal(loc=0, scale=sigma))
            
            # 确保最小值
            interval = max(interval, 30)  # 最小30秒
            
            # 限制最大值防止过度极端
            interval = min(interval, 86400)  # 最大24小时
            
            logger.debug(f"{self.log_prefix} 纯随机模式生成间隔: {int(interval)}秒")
            return int(interval)
            
        except Exception as e:
            logger.error(f"{self.log_prefix} 纯随机间隔生成失败: {e}")
            return 300  # 回退到5分钟

    def _format_duration(self, seconds: float) -> str:
        """格式化时间间隔为易读格式"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)

        parts = []
        if hours > 0:
            parts.append(f"{hours}小时")
        if minutes > 0:
            parts.append(f"{minutes}分")
        if secs > 0 or not parts:  # 如果没有小时和分钟，显示秒
            parts.append(f"{secs}秒")

        return "".join(parts)

    async def _execute_proactive_thinking(self, silence_duration: float):
        """执行主动思考"""
        formatted_time = self._format_duration(silence_duration)
        logger.info(f"{self.log_prefix} 触发主动思考，已沉默{formatted_time}")

        try:
            # 优先使用配置文件中的prompt模板，如果没有则使用内置模板
            if hasattr(global_config.chat, 'proactive_thinking_prompt_template') and global_config.chat.proactive_thinking_prompt_template.strip():
                proactive_prompt = global_config.chat.proactive_thinking_prompt_template.format(time=formatted_time)
            else:
                # 回退到内置的prompt模板
                chat_type = "group" if self.chat_stream.group_info else "private"
                prompt_template = self.proactive_thinking_prompts.get(chat_type, self.proactive_thinking_prompts["group"])
                proactive_prompt = prompt_template.format(time=formatted_time)

            # 创建一个虚拟的消息数据用于主动思考
            thinking_message = {
                "processed_plain_text": proactive_prompt,
                "user_id": "system_proactive_thinking",
                "user_platform": "system",
                "timestamp": time.time(),
                "message_type": "proactive_thinking",
                "user_nickname": "系统主动思考",
                "chat_info_platform": "system",
                "message_id": f"proactive_{int(time.time())}",
            }

            # 使用现有的_observe方法来处理主动思考
            logger.info(f"{self.log_prefix} 开始主动思考...")
            await self._observe(message_data=thinking_message)
            logger.info(f"{self.log_prefix} 主动思考完成")

        except Exception as e:
            logger.error(f"{self.log_prefix} 主动思考执行异常: {e}")
            logger.error(traceback.format_exc())

    def print_cycle_info(self, cycle_timers):
        # 记录循环信息和计时器结果
        timer_strings = []
        for name, elapsed in cycle_timers.items():
            formatted_time = f"{elapsed * 1000:.2f}毫秒" if elapsed < 1 else f"{elapsed:.2f}秒"
            timer_strings.append(f"{name}: {formatted_time}")

        logger.info(
            f"{self.log_prefix} 第{self._current_cycle_detail.cycle_id}次思考,"
            f"耗时: {self._current_cycle_detail.end_time - self._current_cycle_detail.start_time:.1f}秒, "  # type: ignore
            f"选择动作: {self._current_cycle_detail.loop_plan_info.get('action_result', {}).get('action_type', '未知动作')}"
            + (f"\n详情: {'; '.join(timer_strings)}" if timer_strings else "")
        )

    async def _loopbody(self):
        recent_messages_dict = message_api.get_messages_by_time_in_chat(
            chat_id=self.stream_id,
            start_time=self.last_read_time,
            end_time=time.time(),
            limit=10,
            limit_mode="latest",
            filter_mai=True,
            filter_command=True,
        )
        new_message_count = len(recent_messages_dict)

        # 如果有新消息，更新最后消息时间（用于主动思考计时）
        if new_message_count > 0:
            current_time = time.time()
            self.last_message_time = current_time

        if self.loop_mode == ChatMode.FOCUS:
            # focus模式下，在有新消息时进行观察思考
            # 主动思考由独立的 _proactive_thinking_loop 处理
            if new_message_count > 0:
                self.last_read_time = time.time()

                if await self._observe():
                    # 在强制模式下，能量值不会因观察而增加
                    is_group_chat = self.chat_stream.group_info is not None
                    if not (is_group_chat and global_config.chat.group_chat_mode != "auto"):
                        self.energy_value += 1 / global_config.chat.focus_value
                        self._log_energy_change("能量值增加")

            # 检查是否应该退出专注模式
            # 如果开启了强制私聊专注模式且当前为私聊，则不允许退出专注状态
            is_private_chat = self.chat_stream.group_info is None
            is_group_chat = self.chat_stream.group_info is not None

            if global_config.chat.force_focus_private and is_private_chat:
                # 强制私聊专注模式下，保持专注状态，但重置能量值防止过低
                if self.energy_value <= 1:
                    self.energy_value = 5  # 重置为较低但足够的能量值
                return True

            # 群聊强制专注模式下，不允许退出专注状态
            if is_group_chat and global_config.chat.group_chat_mode == "focus":
                return True

            if self.energy_value <= 1:
                self.energy_value = 1
                self.loop_mode = ChatMode.NORMAL
                return True

            return True
        elif self.loop_mode == ChatMode.NORMAL:
            # 检查是否应该强制进入专注模式（私聊且开启强制专注）
            is_private_chat = self.chat_stream.group_info is None
            is_group_chat = self.chat_stream.group_info is not None

            if global_config.chat.force_focus_private and is_private_chat:
                self.loop_mode = ChatMode.FOCUS
                self.energy_value = 10  # 设置初始能量值
                return True

            # 群聊强制普通模式下，不允许进入专注状态
            if is_group_chat and global_config.chat.group_chat_mode == "normal":
                # 在强制普通模式下，即使满足条件也不进入专注模式
                pass
            elif global_config.chat.focus_value != 0:
                if new_message_count > 3 / pow(global_config.chat.focus_value, 0.5):
                    self.loop_mode = ChatMode.FOCUS
                    self.energy_value = 10 + (new_message_count / (3 / pow(global_config.chat.focus_value, 0.5))) * 10
                    return True

                if self.energy_value >= 30:
                    self.loop_mode = ChatMode.FOCUS
                    return True

            if new_message_count >= self.focus_energy:
                earliest_messages_data = recent_messages_dict[0]
                self.last_read_time = earliest_messages_data.get("time")

                if_think = await self.normal_response(earliest_messages_data)

                # 在强制模式下，能量值变化逻辑需要特殊处理
                is_group_chat = self.chat_stream.group_info is not None
                if is_group_chat and global_config.chat.group_chat_mode != "auto":
                    # 强制模式下不改变能量值
                    pass
                elif if_think:
                    factor = max(global_config.chat.focus_value, 0.1)
                    self.energy_value *= 1.1 * factor
                    self._log_energy_change("进行了思考，能量值按倍数增加")
                else:
                    self.energy_value += 0.1 * global_config.chat.focus_value
                    self._log_energy_change("没有进行思考，能量值线性增加")

                # 这个可以保持debug级别，因为它是总结性信息
                logger.debug(f"{self.log_prefix} 当前能量值：{self.energy_value:.1f}")
                return True

            await asyncio.sleep(0.5)

            return True

    async def build_reply_to_str(self, message_data: dict):
        person_info_manager = get_person_info_manager()

        # 获取平台信息，优先使用chat_info_platform，如果为None则使用user_platform
        platform = (
            message_data.get("chat_info_platform") or message_data.get("user_platform") or self.chat_stream.platform
        )
        user_id = message_data.get("user_id")
        if user_id is None:
            user_id = ""
        person_id = person_info_manager.get_person_id(platform, user_id)
        person_name = await person_info_manager.get_value(person_id, "person_name")
        return f"{person_name}:{message_data.get('processed_plain_text')}"

    async def _send_and_store_reply(
        self,
        response_set,
        reply_to_str,
        loop_start_time,
        action_message,
        cycle_timers: Dict[str, float],
        thinking_id,
        plan_result,
    ) -> Tuple[Dict[str, Any], str, Dict[str, float]]:
        with Timer("回复发送", cycle_timers):
            reply_text = await self._send_response(response_set, reply_to_str, loop_start_time, action_message)

            # 存储reply action信息
        person_info_manager = get_person_info_manager()

        # 获取平台信息，优先使用chat_info_platform，如果为空则使用user_platform
        platform = (
            action_message.get("chat_info_platform") or action_message.get("user_platform") or self.chat_stream.platform
        )
        user_id = action_message.get("user_id", "")

        person_id = person_info_manager.get_person_id(platform, user_id)
        person_name = await person_info_manager.get_value(person_id, "person_name")
        action_prompt_display = f"你对{person_name}进行了回复：{reply_text}"

        await database_api.store_action_info(
            chat_stream=self.chat_stream,
            action_build_into_prompt=False,
            action_prompt_display=action_prompt_display,
            action_done=True,
            thinking_id=thinking_id,
            action_data={"reply_text": reply_text, "reply_to": reply_to_str},
            action_name="reply",
        )

        # 构建循环信息
        loop_info: Dict[str, Any] = {
            "loop_plan_info": {
                "action_result": plan_result.get("action_result", {}),
            },
            "loop_action_info": {
                "action_taken": True,
                "reply_text": reply_text,
                "command": "",
                "taken_time": time.time(),
            },
        }

        return loop_info, reply_text, cycle_timers

    async def _observe(self, message_data: Optional[Dict[str, Any]] = None) -> bool:
        if not message_data:
            message_data = {}
        action_type = "no_action"
        reply_text = ""  # 初始化reply_text变量，避免UnboundLocalError
        gen_task = None  # 初始化gen_task变量，避免UnboundLocalError
        reply_to_str = ""  # 初始化reply_to_str变量

        # 创建新的循环信息
        cycle_timers, thinking_id = self.start_cycle()

        logger.info(f"{self.log_prefix} 开始第{self._cycle_counter}次思考[模式：{self.loop_mode}]")

        if ENABLE_S4U:
            await send_typing()

        async with global_prompt_manager.async_message_scope(self.chat_stream.context.get_template_name()):
            loop_start_time = time.time()
            await self.relationship_builder.build_relation()
            await self.expression_learner.trigger_learning_for_chat()

            available_actions = {}

            # 第一步：动作修改
            with Timer("动作修改", cycle_timers):
                try:
                    await self.action_modifier.modify_actions()
                    available_actions = self.action_manager.get_using_actions()
                except Exception as e:
                    logger.error(f"{self.log_prefix} 动作修改失败: {e}")

            # 在focus模式下如果你的bot被@/提到了，那么就移除no_reply动作
            is_mentioned_bot = message_data.get("is_mentioned", False)
            at_bot_mentioned = (global_config.chat.mentioned_bot_inevitable_reply and is_mentioned_bot) or (
                global_config.chat.at_bot_inevitable_reply and is_mentioned_bot
            )

            if self.loop_mode == ChatMode.FOCUS and at_bot_mentioned and "no_reply" in available_actions:
                logger.info(f"{self.log_prefix} Focus模式下检测到@或提及bot，移除no_reply动作以确保回复")
                available_actions = {
                    k: v for k, v in available_actions.items() if k != "no_reply"
                }  # 用一个循环来移除no_reply

            # 检查是否在normal模式下没有可用动作（除了reply相关动作）
            skip_planner = False
            if self.loop_mode == ChatMode.NORMAL:
                # 过滤掉reply相关的动作，检查是否还有其他动作
                non_reply_actions = {
                    k: v for k, v in available_actions.items() if k not in ["reply", "no_reply", "no_action"]
                }

                if not non_reply_actions:
                    skip_planner = True
                    logger.info(f"{self.log_prefix} Normal模式下没有可用动作，直接回复")

                    # 直接设置为reply动作
                    action_type = "reply"
                    reasoning = ""
                    action_data = {"loop_start_time": loop_start_time}
                    is_parallel = False

                    # 构建plan_result用于后续处理
                    plan_result = {
                        "action_result": {
                            "action_type": action_type,
                            "action_data": action_data,
                            "reasoning": reasoning,
                            "timestamp": time.time(),
                            "is_parallel": is_parallel,
                        },
                        "action_prompt": "",
                    }
                    target_message = message_data

                # 如果normal模式且不跳过规划器，开始一个回复生成进程，先准备好回复（其实是和planer同时进行的）
                if not skip_planner:
                    reply_to_str = await self.build_reply_to_str(message_data)
                    gen_task = asyncio.create_task(
                        self._generate_response(
                            message_data=message_data,
                            available_actions=available_actions,
                            reply_to=reply_to_str,
                            request_type="chat.replyer.normal",
                        )
                    )

            if not skip_planner:
                planner_info = self.action_planner.get_necessary_info()
                prompt_info = await self.action_planner.build_planner_prompt(
                    is_group_chat=planner_info[0],
                    chat_target_info=planner_info[1],
                    current_available_actions=planner_info[2],
                )
                if not await events_manager.handle_mai_events(
                    EventType.ON_PLAN, None, prompt_info[0], None, self.chat_stream.stream_id
                ):
                    return False
                with Timer("规划器", cycle_timers):
                    plan_result, target_message = await self.action_planner.plan(mode=self.loop_mode)

                action_result: Dict[str, Any] = plan_result.get("action_result", {})  # type: ignore
                action_type, action_data, reasoning, is_parallel = (
                    action_result.get("action_type", "error"),
                    action_result.get("action_data", {}),
                    action_result.get("reasoning", "未提供理由"),
                    action_result.get("is_parallel", True),
                )

                action_data["loop_start_time"] = loop_start_time

            # 在私聊的专注模式下，如果规划动作为no_reply，则强制改为reply
            is_private_chat = self.chat_stream.group_info is None
            if self.loop_mode == ChatMode.FOCUS and is_private_chat and action_type == "no_reply":
                action_type = "reply"
                logger.info(f"{self.log_prefix} 私聊专注模式下强制回复")

            if action_type == "reply":
                logger.info(f"{self.log_prefix}{global_config.bot.nickname} 决定进行回复")
            elif is_parallel:
                logger.info(f"{self.log_prefix}{global_config.bot.nickname} 决定进行回复, 同时执行{action_type}动作")
            else:
                # 只有在gen_task存在时才进行相关操作
                if gen_task:
                    if not gen_task.done():
                        gen_task.cancel()
                        logger.debug(f"{self.log_prefix} 已取消预生成的回复任务")
                        logger.info(
                            f"{self.log_prefix}{global_config.bot.nickname} 原本想要回复，但选择执行{action_type}，不发表回复"
                        )
                    elif generation_result := gen_task.result():
                        content = " ".join([item[1] for item in generation_result if item[0] == "text"])
                        logger.debug(f"{self.log_prefix} 预生成的回复任务已完成")
                        logger.info(
                            f"{self.log_prefix}{global_config.bot.nickname} 原本想要回复：{content}，但选择执行{action_type}，不发表回复"
                        )
                    else:
                        logger.warning(f"{self.log_prefix} 预生成的回复任务未生成有效内容")

            action_message = target_message or message_data
            if action_type == "reply":
                # 等待回复生成完毕
                if self.loop_mode == ChatMode.NORMAL:
                    # 只有在gen_task存在时才等待
                    if not gen_task:
                        reply_to_str = await self.build_reply_to_str(message_data)
                        gen_task = asyncio.create_task(
                            self._generate_response(
                                message_data=message_data,
                                available_actions=available_actions,
                                reply_to=reply_to_str,
                                request_type="chat.replyer.normal",
                            )
                        )

                    gather_timeout = global_config.chat.thinking_timeout
                    try:
                        response_set = await asyncio.wait_for(gen_task, timeout=gather_timeout)
                    except asyncio.TimeoutError:
                        logger.warning(f"{self.log_prefix} 回复生成超时>{global_config.chat.thinking_timeout}s，已跳过")
                        response_set = None

                    # 模型炸了或超时，没有回复内容生成
                    if not response_set:
                        logger.warning(f"{self.log_prefix}模型未生成回复内容")
                        return False
                else:
                    logger.info(f"{self.log_prefix}{global_config.bot.nickname} 决定进行回复 (focus模式)")

                    # 构建reply_to字符串
                    reply_to_str = await self.build_reply_to_str(action_message)

                    # 生成回复
                    with Timer("回复生成", cycle_timers):
                        response_set = await self._generate_response(
                            message_data=action_message,
                            available_actions=available_actions,
                            reply_to=reply_to_str,
                            request_type="chat.replyer.focus",
                        )

                    if not response_set:
                        logger.warning(f"{self.log_prefix}模型未生成回复内容")
                        return False

                loop_info, reply_text, cycle_timers = await self._send_and_store_reply(
                    response_set, reply_to_str, loop_start_time, action_message, cycle_timers, thinking_id, plan_result
                )

                return True

            else:
                # 并行执行：同时进行回复发送和动作执行
                # 先置空防止未定义错误
                background_reply_task = None
                background_action_task = None
                # 如果是并行执行且在normal模式下，需要等待预生成的回复任务完成并发送回复
                if self.loop_mode == ChatMode.NORMAL and is_parallel and gen_task:

                    async def handle_reply_task() -> Tuple[Optional[Dict[str, Any]], str, Dict[str, float]]:
                        # 等待预生成的回复任务完成
                        gather_timeout = global_config.chat.thinking_timeout
                        try:
                            response_set = await asyncio.wait_for(gen_task, timeout=gather_timeout)

                        except asyncio.TimeoutError:
                            logger.warning(
                                f"{self.log_prefix} 并行执行：回复生成超时>{global_config.chat.thinking_timeout}s，已跳过"
                            )
                            return None, "", {}
                        except asyncio.CancelledError:
                            logger.debug(f"{self.log_prefix} 并行执行：回复生成任务已被取消")
                            return None, "", {}

                        if not response_set:
                            logger.warning(f"{self.log_prefix} 模型超时或生成回复内容为空")
                            return None, "", {}

                        reply_to_str = await self.build_reply_to_str(action_message)
                        loop_info, reply_text, cycle_timers_reply = await self._send_and_store_reply(
                            response_set,
                            reply_to_str,
                            loop_start_time,
                            action_message,
                            cycle_timers,
                            thinking_id,
                            plan_result,
                        )
                        return loop_info, reply_text, cycle_timers_reply

                    # 执行回复任务并赋值到变量
                    background_reply_task = asyncio.create_task(handle_reply_task())

                # 动作执行任务
                async def handle_action_task():
                    with Timer("动作执行", cycle_timers):
                        success, reply_text, command = await self._handle_action(
                            action_type, reasoning, action_data, cycle_timers, thinking_id, action_message
                        )
                    return success, reply_text, command

                # 执行动作任务并赋值到变量
                background_action_task = asyncio.create_task(handle_action_task())

                reply_loop_info = None
                reply_text_from_reply = ""
                action_success = False
                action_reply_text = ""
                action_command = ""

                # 并行执行所有任务
                if background_reply_task:
                    results = await asyncio.gather(
                        background_reply_task, background_action_task, return_exceptions=True
                    )
                    # 处理回复任务结果
                    reply_result = results[0]
                    if isinstance(reply_result, BaseException):
                        logger.error(f"{self.log_prefix} 回复任务执行异常: {reply_result}")
                    elif reply_result and reply_result[0] is not None:
                        reply_loop_info, reply_text_from_reply, _ = reply_result

                    # 处理动作任务结果
                    action_task_result = results[1]
                    if isinstance(action_task_result, BaseException):
                        logger.error(f"{self.log_prefix} 动作任务执行异常: {action_task_result}")
                    else:
                        action_success, action_reply_text, action_command = action_task_result
                else:
                    results = await asyncio.gather(background_action_task, return_exceptions=True)
                    # 只有动作任务
                    action_task_result = results[0]
                    if isinstance(action_task_result, BaseException):
                        logger.error(f"{self.log_prefix} 动作任务执行异常: {action_task_result}")
                    else:
                        action_success, action_reply_text, action_command = action_task_result

                # 构建最终的循环信息
                if reply_loop_info:
                    # 如果有回复信息，使用回复的loop_info作为基础
                    loop_info = reply_loop_info
                    # 更新动作执行信息
                    loop_info["loop_action_info"].update(
                        {
                            "action_taken": action_success,
                            "command": action_command,
                            "taken_time": time.time(),
                        }
                    )
                    reply_text = reply_text_from_reply
                else:
                    # 没有回复信息，构建纯动作的loop_info
                    loop_info = {
                        "loop_plan_info": {
                            "action_result": plan_result.get("action_result", {}),
                        },
                        "loop_action_info": {
                            "action_taken": action_success,
                            "reply_text": action_reply_text,
                            "command": action_command,
                            "taken_time": time.time(),
                        },
                    }
                    reply_text = action_reply_text

        self.last_action = action_type

        if ENABLE_S4U:
            await stop_typing()
            await mai_thinking_manager.get_mai_think(self.stream_id).do_think_after_response(reply_text)

        self.end_cycle(loop_info, cycle_timers)
        self.print_cycle_info(cycle_timers)

        if self.loop_mode == ChatMode.NORMAL:
            await self.willing_manager.after_generate_reply_handle(message_data.get("message_id", ""))

        # 管理动作状态：当执行了非no_reply动作时进行记录
        if action_type != "no_reply" and action_type != "no_action":
            logger.info(f"{self.log_prefix} 执行了{action_type}动作")
            return True
        elif action_type == "no_action":
            logger.info(f"{self.log_prefix} 执行了回复动作")

        return True

    async def _main_chat_loop(self):
        """主循环，持续进行计划并可能回复消息，直到被外部取消。"""
        try:
            while self.running:
                # 主循环
                success = await self._loopbody()
                await asyncio.sleep(0.1)
                if not success:
                    break
        except asyncio.CancelledError:
            # 设置了关闭标志位后被取消是正常流程
            logger.info(f"{self.log_prefix} 麦麦已关闭聊天")
        except Exception:
            logger.error(f"{self.log_prefix} 麦麦聊天意外错误，将于3s后尝试重新启动")
            print(traceback.format_exc())
            await asyncio.sleep(3)
            self._loop_task = asyncio.create_task(self._main_chat_loop())
        logger.error(f"{self.log_prefix} 结束了当前聊天循环")

    async def _handle_action(
        self,
        action: str,
        reasoning: str,
        action_data: dict,
        cycle_timers: Dict[str, float],
        thinking_id: str,
        action_message: dict,
    ) -> tuple[bool, str, str]:
        """
        处理规划动作，使用动作工厂创建相应的动作处理器

        参数:
            action: 动作类型
            reasoning: 决策理由
            action_data: 动作数据，包含不同动作需要的参数
            cycle_timers: 计时器字典
            thinking_id: 思考ID

        返回:
            tuple[bool, str, str]: (是否执行了动作, 思考消息ID, 命令)
        """
        try:
            # 使用工厂创建动作处理器实例
            try:
                action_handler = self.action_manager.create_action(
                    action_name=action,
                    action_data=action_data,
                    reasoning=reasoning,
                    cycle_timers=cycle_timers,
                    thinking_id=thinking_id,
                    chat_stream=self.chat_stream,
                    log_prefix=self.log_prefix,
                    action_message=action_message,
                )
            except Exception as e:
                logger.error(f"{self.log_prefix} 创建动作处理器时出错: {e}")
                traceback.print_exc()
                return False, "", ""

            if not action_handler:
                logger.warning(f"{self.log_prefix} 未能创建动作处理器: {action}")
                return False, "", ""

            # 处理动作并获取结果
            result = await action_handler.handle_action()
            success, reply_text = result
            command = ""

            if reply_text == "timeout":
                self.reply_timeout_count += 1
                if self.reply_timeout_count > 5:
                    logger.warning(
                        f"[{self.log_prefix} ] 连续回复超时次数过多，{global_config.chat.thinking_timeout}秒 内大模型没有返回有效内容，请检查你的api是否速度过慢或配置错误。建议不要使用推理模型，推理模型生成速度过慢。或者尝试拉高thinking_timeout参数，这可能导致回复时间过长。"
                    )
                logger.warning(f"{self.log_prefix} 回复生成超时{global_config.chat.thinking_timeout}s，已跳过")
                return False, "", ""

            return success, reply_text, command

        except Exception as e:
            logger.error(f"{self.log_prefix} 处理{action}时出错: {e}")
            traceback.print_exc()
            return False, "", ""

    async def normal_response(self, message_data: dict) -> bool:
        """
        处理接收到的消息。
        在"兴趣"模式下，判断是否回复并生成内容。
        """

        interested_rate = message_data.get("interest_value") or 0.0

        self.willing_manager.setup(message_data, self.chat_stream)

        reply_probability = await self.willing_manager.get_reply_probability(message_data.get("message_id", ""))

        talk_frequency = -1.00

        if reply_probability < 1:  # 简化逻辑，如果未提及 (reply_probability 为 0)，则获取意愿概率
            additional_config = message_data.get("additional_config", {})
            if additional_config and "maimcore_reply_probability_gain" in additional_config:
                reply_probability += additional_config["maimcore_reply_probability_gain"]
                reply_probability = min(max(reply_probability, 0), 1)  # 确保概率在 0-1 之间

        talk_frequency = global_config.chat.get_current_talk_frequency(self.stream_id)
        reply_probability = talk_frequency * reply_probability

        # 处理表情包
        if message_data.get("is_emoji") or message_data.get("is_picid"):
            reply_probability = 0

        # 打印消息信息
        mes_name = self.chat_stream.group_info.group_name if self.chat_stream.group_info else "私聊"

        # logger.info(f"[{mes_name}] 当前聊天频率: {talk_frequency:.2f},兴趣值: {interested_rate:.2f},回复概率: {reply_probability * 100:.1f}%")

        if reply_probability > 0.05:
            logger.info(
                f"[{mes_name}]"
                f"{message_data.get('user_nickname')}:"
                f"{message_data.get('processed_plain_text')}[兴趣:{interested_rate:.2f}][回复概率:{reply_probability * 100:.1f}%]"
            )

        if random.random() < reply_probability:
            await self.willing_manager.before_generate_reply_handle(message_data.get("message_id", ""))
            await self._observe(message_data=message_data)
            return True

        # 意愿管理器：注销当前message信息 (无论是否回复，只要处理过就删除)
        self.willing_manager.delete(message_data.get("message_id", ""))
        return False

    async def _generate_response(
        self,
        message_data: dict,
        available_actions: Optional[Dict[str, ActionInfo]],
        reply_to: str,
        request_type: str = "chat.replyer.normal",
    ) -> Optional[list]:
        """生成普通回复"""
        try:
            success, reply_set, _ = await generator_api.generate_reply(
                chat_stream=self.chat_stream,
                reply_to=reply_to,
                available_actions=available_actions,
                enable_tool=global_config.tool.enable_tool,
                request_type=request_type,
                from_plugin=False,
            )

            if not success or not reply_set:
                logger.info(f"对 {message_data.get('processed_plain_text')} 的回复生成失败")
                return None

            return reply_set

        except Exception as e:
            logger.error(f"{self.log_prefix}回复生成出现错误：{str(e)} {traceback.format_exc()}")
            return None

    async def _send_response(self, reply_set, reply_to, thinking_start_time, message_data) -> str:
        current_time = time.time()
        new_message_count = message_api.count_new_messages(
            chat_id=self.chat_stream.stream_id, start_time=thinking_start_time, end_time=current_time
        )
        platform = message_data.get("user_platform", "")
        user_id = message_data.get("user_id", "")
        reply_to_platform_id = f"{platform}:{user_id}"

        need_reply = new_message_count >= random.randint(2, 4)

        if need_reply:
            logger.info(f"{self.log_prefix} 从思考到回复，共有{new_message_count}条新消息，使用引用回复")
        else:
            logger.info(f"{self.log_prefix} 从思考到回复，共有{new_message_count}条新消息，不使用引用回复")

        reply_text = ""

        # 检查是否为主动思考且决定沉默
        is_proactive_thinking = message_data.get("message_type") == "proactive_thinking"

        first_replied = False
        for reply_seg in reply_set:
            data = reply_seg[1]
            reply_text += data

            # 如果是主动思考且回复内容是"沉默"，则不发送消息
            if is_proactive_thinking and data.strip() == "沉默":
                logger.info(f"{self.log_prefix} 主动思考决定保持沉默，不发送消息")
                continue

            if not first_replied:
                if need_reply:
                    await send_api.text_to_stream(
                        text=data,
                        stream_id=self.chat_stream.stream_id,
                        reply_to=reply_to,
                        reply_to_platform_id=reply_to_platform_id,
                        typing=False,
                    )
                else:
                    await send_api.text_to_stream(
                        text=data,
                        stream_id=self.chat_stream.stream_id,
                        reply_to_platform_id=reply_to_platform_id,
                        typing=False,
                    )
                first_replied = True
            else:
                await send_api.text_to_stream(
                    text=data,
                    stream_id=self.chat_stream.stream_id,
                    reply_to_platform_id=reply_to_platform_id,
                    typing=True,
                )

        return reply_text
