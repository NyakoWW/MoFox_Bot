"""
智能Prompt系统 - 完全重构版本
基于原有DefaultReplyer的完整功能集成，使用新的参数结构
"""
import asyncio
import time
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Literal, Tuple
import re

from src.chat.utils.prompt_builder import global_prompt_manager, Prompt
from src.common.logger import get_logger
from src.config.config import global_config
from src.chat.utils.chat_message_builder import (
    build_readable_messages,
    get_raw_msg_before_timestamp_with_chat,
    build_readable_messages_with_id,
    replace_user_references_sync,
)
from src.person_info.person_info import get_person_info_manager
from src.plugin_system.core.tool_use import ToolExecutor
from src.chat.utils.prompt_utils import PromptUtils
from src.chat.utils.prompt_parameters import PromptCoreParams, PromptFeatureParams, PromptContentParams

logger = get_logger("smart_prompt")

# 重新导出参数类以保持兼容性
from src.chat.utils.prompt_parameters import (
    PromptCoreParams,
    PromptFeatureParams,
    PromptContentParams
)


@dataclass
class SmartPromptParameters:
    """兼容的智能提示词参数系统 - 使用分层架构"""
    
    # 核心参数 (从PromptCoreParams继承)
    core: PromptCoreParams = field(default_factory=PromptCoreParams)
    
    # 功能参数 (从PromptFeatureParams继承)
    features: PromptFeatureParams = field(default_factory=PromptFeatureParams)
    
    # 内容参数 (从PromptContentParams继承)
    content: PromptContentParams = field(default_factory=PromptContentParams)
    
    # 配置和兼容属性
    enable_cache: bool = True
    cache_ttl: int = 300
    
    # 为了向下兼容，提供属性访问
    @property
    def chat_id(self) -> str:
        return self.core.chat_id
    
    @chat_id.setter
    def chat_id(self, value: str):
        self.core.chat_id = value
    
    @property
    def reply_to(self) -> str:
        return self.core.reply_to
    
    @reply_to.setter
    def reply_to(self, value: str):
        self.core.reply_to = value
    
    @property
    def current_prompt_mode(self) -> str:
        return self.core.prompt_mode
    
    @current_prompt_mode.setter
    def current_prompt_mode(self, value: str):
        self.core.prompt_mode = value
    
    def validate(self) -> List[str]:
        """参数验证"""
        errors = []
        if not isinstance(self.core.chat_id, str):
            errors.append("chat_id必须是字符串类型")
        if not isinstance(self.core.reply_to, str):
            errors.append("reply_to必须是字符串类型")
        return errors + self.features.validate() + self.content.validate()


@dataclass
class ChatContext:
    """聊天上下文信息"""
    chat_id: str = ""
    platform: str = ""
    is_group: bool = False
    user_id: str = ""
    user_nickname: str = ""
    group_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)


class SmartPromptBuilder:
    """重构的智能提示词构建器 - 完全继承DefaultReplyer功能"""
    
    def __init__(self):
        # 使用共享缓存
        from src.chat.utils.prompt_utils import PromptUtils
        
    async def build_context_data(self, params: SmartPromptParameters) -> Dict[str, Any]:
        """并行构建完整的上下文数据 - 使用共享缓存和优化后的参数结构"""
        
        # 使用共享缓存
        from src.chat.utils.prompt_utils import PromptUtils
        cache_key = PromptUtils.get_cache_key(
            params.core.chat_id,
            params.core.prompt_mode,
            params.core.reply_to
        )
        
        cached = PromptUtils.get_from_cache(cache_key, params.cache_ttl if hasattr(params, 'cache_ttl') else 300)
        if cached is not None:
            logger.debug(f"使用缓存结果: {cache_key}")
            return cached
        
        # 并行执行所有构建任务
        start_time = time.time()
        timing_logs = {}
        
        try:
            # 准备构建任务
            tasks = []
            task_names = []
            
            # 初始化预构建参数，使用新的结构
            pre_built_params = {}
            if params.content:
                pre_built_params.update({
                    'expression_habits_block': params.content.expression_habits or "",
                    'relation_info': params.content.relation_info or "",
                    'memory_block': params.content.memory_block or "",
                    'tool_info': params.content.tool_info or "",
                    'knowledge_prompt': params.content.knowledge_info or "",
                    'cross_context_block': params.content.cross_context or "",
                })
            
            # 根据新的参数结构确定要构建的项
            if params.features.enable_expression and not pre_built_params.get('expression_habits_block'):
                tasks.append(self._timed_build(self._build_expression_habits, params, "expression_habits"))
                task_names.append("expression_habits")
            
            if params.features.enable_memory and not pre_built_params.get('memory_block'):
                tasks.append(self._timed_build(self._build_memory_block, params, "memory_block"))
                task_names.append("memory_block")
            
            if params.features.enable_relation and not pre_built_params.get('relation_info'):
                tasks.append(self._timed_build(self._build_relation_info, params, "relation_info"))
                task_names.append("relation_info")
            
            if params.features.enable_tool and not pre_built_params.get('tool_info'):
                tasks.append(self._timed_build(self._build_tool_info, params, "tool_info"))
                task_names.append("tool_info")
            
            if params.features.enable_knowledge and not pre_built_params.get('knowledge_prompt'):
                tasks.append(self._timed_build(self._build_knowledge_info, params, "knowledge_info"))
                task_names.append("knowledge_info")
            
            if params.features.enable_cross_context and not pre_built_params.get('cross_context_block'):
                tasks.append(self._timed_build(self._build_cross_context, params, "cross_context"))
                task_names.append("cross_context")
            
            # 并行执行所有任务，设置更合理的超时
            timeout_seconds = max(10.0, params.max_context_messages * 0.3)  # 最少10秒超时
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=timeout_seconds
            )
            
            # 处理结果并收集性能数据
            context_data = {}
            for i, result in enumerate(results):
                task_name = task_names[i] if i < len(task_names) else f"task_{i}"
                
                if isinstance(result, Exception):
                    logger.error(f"构建任务{task_name}失败: {str(result)}")
                elif isinstance(result, tuple) and len(result) == 2:
                    # 结果格式: (data, timing)
                    data, timing = result
                    context_data.update(data)
                    timing_logs[task_name] = timing
                    
                    # 记录耗时过长的任务
                    if timing > 8.0:
                        logger.warning(f"构建任务{task_name}耗时过长: {timing:.2f}s")
                else:
                    # 直接数据结果
                    context_data.update(result)
            
            # 添加预构建的参数
            for key, value in pre_built_params.items():
                if value:
                    context_data[key] = value
            
        except asyncio.TimeoutError:
            logger.error(f"构建超时 ({timeout_seconds}s)")
            context_data = {}
            
            # 添加预构建的参数，即使在超时情况下
            for key, value in pre_built_params.items():
                if value:
                    context_data[key] = value
        
        # 构建聊天历史 - 根据模式不同
        if params.current_prompt_mode == "s4u":
            await self._build_s4u_chat_context(context_data, params)
        else:
            await self._build_normal_chat_context(context_data, params)
        
        # 补充基础信息
        context_data.update({
            'keywords_reaction_prompt': params.keywords_reaction_prompt,
            'extra_info_block': params.extra_info_block,
            'time_block': params.time_block or f"当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            'identity': params.identity_block,
            'schedule_block': params.schedule_block,
            'moderation_prompt': params.moderation_prompt_block,
            'reply_target_block': params.reply_target_block,
            'mood_state': params.mood_prompt,
            'action_descriptions': params.action_descriptions,
        })
        
        # 缓存数据
        if params.enable_cache:
            self._cache[cache_key] = {
                'data': context_data,
                'timestamp': time.time()
            }
        
        total_time = time.time() - start_time
        if timing_logs:
            timing_str = "; ".join([f"{name}: {time:.2f}s" for name, time in timing_logs.items()])
            logger.info(f"构建任务耗时: {timing_str}")
        logger.debug(f"构建完成，总耗时: {total_time:.2f}s")
        
        return context_data
    
    async def _timed_build(self, build_func, params: SmartPromptParameters, task_name: str) -> Tuple[Dict[str, Any], float]:
        """带计时的构建函数"""
        start_time = time.time()
        try:
            result = await build_func(params)
            end_time = time.time()
            return result, end_time - start_time
        except Exception as e:
            logger.error(f"构建任务{task_name}异常: {e}")
            end_time = time.time()
            return {}, end_time - start_time
    
    async def _build_s4u_chat_context(self, context_data: Dict[str, Any], params: SmartPromptParameters) -> None:
        """构建S4U模式的聊天上下文 - 使用新参数结构"""
        if not params.core.message_list:
            return
            
        # 使用共享工具构建分离历史
        from src.chat.utils.prompt_utils import PromptUtils
        core_dialogue, background_dialogue = PromptUtils.build_s4u_separated_history(
            params.core.message_list,
            params.core.target_user_info,
            params.core.target_chat
        )
        
        context_data['core_dialogue_prompt'] = core_dialogue
        context_data['background_dialogue_prompt'] = background_dialogue
        
    async def _build_normal_chat_context(self, context_data: Dict[str, Any], params: SmartPromptParameters) -> None:
        """构建normal模式的聊天上下文 - 使用新参数结构"""
        if not params.core.chat_context:
            return
            
        context_data['chat_info'] = f"""群里的聊天内容：
{params.core.chat_context}"""
    
    def _build_s4u_separated_history(self, *args, **kwargs):
        """已废弃 - 使用PromptUtils中的实现"""
        logger.warning("_build_s4u_separated_history已废弃，使用PromptUtils.build_s4u_separated_history")
        return "", ""
    
    def _parse_reply_target_id(self, reply_to: str) -> str:
        """解析回复目标中的用户ID"""
        if not reply_to:
            return ""
        
        # 复用_parse_reply_target方法的逻辑
        sender, _ = self._parse_reply_target(reply_to)
        if not sender:
            return ""
        
        # 获取用户ID
        person_info_manager = get_person_info_manager()
        person_id = person_info_manager.get_person_id_by_person_name(sender)
        if person_id:
            user_id = person_info_manager.get_value_sync(person_id, "user_id")
            return str(user_id) if user_id else ""
    
    @property
    def _cached_data(self) -> dict:
        """缓存存储"""
        if not hasattr(self, '_cache_store'):
            self._cache_store = {}
        return self._cache_store
    
    async def _build_expression_habits(self, params: SmartPromptParameters) -> Dict[str, Any]:
        """构建表达习惯 - 使用共享工具类"""
        try:
            from src.chat.utils.prompt_utils import PromptUtils
            return await PromptUtils.build_expression_habits(
                params.core.chat_id,
                params.core.chat_context,
                params.core.target
            )
        except Exception as e:
            logger.error(f"构建表达习惯失败: {e}")
            return {"expression_habits_block": ""}
        
    async def _build_memory_block(self, params: SmartPromptParameters) -> Dict[str, Any]:
        """构建记忆块 - 使用共享工具类"""
        try:
            from src.chat.utils.prompt_utils import PromptUtils
            return await PromptUtils.build_memory_block(
                params.core.chat_id,
                params.core.target,
                params.core.chat_context,
                params.features.enable_memory  # 传入功能开关
            )
            
            if global_config.memory.enable_instant_memory:
                # 使用异步记忆包装器（最优化的非阻塞模式）
                try:
                    from src.chat.memory_system.async_instant_memory_wrapper import get_async_instant_memory
                    
                    # 获取异步记忆包装器
                    async_memory = get_async_instant_memory(params.chat_id)
                    
                    # 后台存储聊天历史（完全非阻塞）
                    async_memory.store_memory_background(params.chat_talking_prompt_short)
                    
                    # 快速检索记忆，最大超时2秒
                    instant_memory = await async_memory.get_memory_with_fallback(params.target, max_timeout=2.0)
                    
                    logger.info(f"异步瞬时记忆：{instant_memory}")
                    
                except ImportError:
                    # 如果异步包装器不可用，尝试使用异步记忆管理器
                    try:
                        from src.chat.memory_system.async_memory_optimizer import (
                            retrieve_memory_nonblocking,
                            store_memory_nonblocking,
                        )
                        
                        # 异步存储聊天历史（非阻塞）
                        asyncio.create_task(
                            store_memory_nonblocking(chat_id=params.chat_id, content=params.chat_talking_prompt_short)
                        )
                        
                        # 尝试从缓存获取瞬时记忆
                        instant_memory = await retrieve_memory_nonblocking(chat_id=params.chat_id, query=params.target)
                        
                        # 如果没有缓存结果，快速检索一次
                        if instant_memory is None:
                            try:
                                instant_memory = await asyncio.wait_for(
                                    instant_memory_system.get_memory_for_context(params.target), timeout=1.5
                                )
                            except asyncio.TimeoutError:
                                logger.warning("瞬时记忆检索超时，使用空结果")
                                instant_memory = ""
                        
                        logger.info(f"向量瞬时记忆：{instant_memory}")
                        
                    except ImportError:
                        # 最后的fallback：使用原有逻辑但加上超时控制
                        logger.warning("异步记忆系统不可用，使用带超时的同步方式")
                        
                        # 异步存储聊天历史
                        asyncio.create_task(instant_memory_system.store_message(params.chat_talking_prompt_short))
                        
                        # 带超时的记忆检索
                        try:
                            instant_memory = await asyncio.wait_for(
                                instant_memory_system.get_memory_for_context(params.target),
                                timeout=1.0,  # 最保守的1秒超时
                            )
                        except asyncio.TimeoutError:
                            logger.warning("瞬时记忆检索超时，跳过记忆获取")
                            instant_memory = ""
                        except Exception as e:
                            logger.error(f"瞬时记忆检索失败: {e}")
                            instant_memory = ""
                        
                        logger.info(f"同步瞬时记忆：{instant_memory}")
                        
                except Exception as e:
                    logger.error(f"瞬时记忆系统异常: {e}")
                    instant_memory = ""
            
            # 构建记忆字符串，即使某种记忆为空也要继续
            memory_str = ""
            has_any_memory = False
            
            # 添加长期记忆
            if running_memories:
                if not memory_str:
                    memory_str = "以下是当前在聊天中，你回忆起的记忆：\n"
                for running_memory in running_memories:
                    memory_str += f"- {running_memory['content']}\n"
                has_any_memory = True
            
            # 添加瞬时记忆
            if instant_memory:
                if not memory_str:
                    memory_str = "以下是当前在聊天中，你回忆起的记忆：\n"
                memory_str += f"- {instant_memory}\n"
                has_any_memory = True
            
            # 只有当完全没有任何记忆时才返回空字符串
            return {"memory_block": memory_str if has_any_memory else ""}
            
        except Exception as e:
            logger.error(f"构建记忆块失败: {e}")
            return {"memory_block": ""}
    
    async def _build_relation_info(self, params: SmartPromptParameters) -> Dict[str, Any]:
        """构建关系信息 - 使用共享工具类"""
        try:
            from src.chat.utils.prompt_utils import PromptUtils
            return await PromptUtils.build_relation_info(
                params.core.chat_id,
                params.core.reply_to
            )
        except Exception as e:
            logger.error(f"构建关系信息失败: {e}")
            return {"relation_info_block": ""}
    
    async def _build_tool_info(self, params: SmartPromptParameters) -> Dict[str, Any]:
        """构建工具信息 - 使用共享工具类"""
        try:
            from src.chat.utils.prompt_utils import PromptUtils
            return await PromptUtils.build_tool_info(
                params.core.chat_id,
                params.core.reply_to,
                params.core.chat_context
            )
        except Exception as e:
            logger.error(f"工具信息获取失败: {e}")
            return {"tool_info_block": ""}
    
    async def _build_knowledge_info(self, params: SmartPromptParameters) -> Dict[str, Any]:
        """构建知识信息 - 使用共享工具类"""
        try:
            from src.chat.utils.prompt_utils import PromptUtils
            return await PromptUtils.build_knowledge_info(
                params.core.reply_to,
                params.core.chat_context
            )
        except Exception as e:
            logger.error(f"获取知识库内容时发生异常: {str(e)}")
            return {"knowledge_prompt": ""}
    
    async def _build_cross_context(self, params: SmartPromptParameters) -> Dict[str, Any]:
        """构建跨群上下文 - 使用共享工具类"""
        try:
            from src.chat.utils.prompt_utils import PromptUtils
            return await PromptUtils.build_cross_context(
                params.core.chat_id,
                params.core.prompt_mode,
                params.core.target_user_info
            )
        except Exception as e:
            logger.error(f"构建跨群上下文失败: {e}")
            return {"cross_context_block": ""}
    
    def _parse_reply_target(self, target_message: str) -> Tuple[str, str]:
        """解析回复目标消息 - 使用共享工具类"""
        return PromptUtils.parse_reply_target(target_message)


class SmartPrompt:
    """重构的智能提示词核心类 - 使用新参数结构"""
    
    def __init__(
        self,
        template_name: Optional[str] = None,
        parameters: Optional[SmartPromptParameters] = None,
    ):
        self.parameters = parameters or SmartPromptParameters()
        self.template_name = template_name or self._get_default_template()
        self.builder = SmartPromptBuilder()
        
    def _get_default_template(self) -> str:
        """根据模式选择默认模板"""
        if self.parameters.core.prompt_mode == "s4u":
            return "s4u_style_prompt"
        elif self.parameters.core.prompt_mode == "normal":
            return "normal_style_prompt"
        else:
            return "default_expressor_prompt"
    
    async def build_prompt(self) -> str:
        """构建最终的Prompt文本 - 使用新参数结构"""
        # 参数验证
        errors = self.parameters.validate()
        if errors:
            raise ValueError(f"参数验证失败: {', '.join(errors)}")
        
        start_time = time.time()
        try:
            # 构建基础上下文的完整映射
            context_data = await self.builder.build_context_data(self.parameters)
            
            # 获取模板
            template = await global_prompt_manager.get_prompt_async(self.template_name)
            
            # 根据模式传递不同的参数
            if self.parameters.core.prompt_mode == "s4u":
                result = await self._build_s4u_prompt(template, context_data)
            elif self.parameters.core.prompt_mode == "normal":
                result = await self._build_normal_prompt(template, context_data)
            else:
                result = await self._build_default_prompt(template, context_data)
            
            # 记录性能数据
            total_time = time.time() - start_time
            logger.debug(f"SmartPrompt构建完成，模式: {self.parameters.core.prompt_mode}, 耗时: {total_time:.2f}s")
            
            return result
                
        except Exception as e:
            logger.error(f"构建Prompt失败: {e}")
            # 返回一个基础Prompt作为fallback
            fallback_prompt = f"用户说：{self.parameters.core.reply_to}。请回复。"
            logger.warning(f"使用fallback prompt: {fallback_prompt}")
            return fallback_prompt
    
    async def _build_s4u_prompt(self, template: Prompt, context_data: Dict[str, Any]) -> str:
        """构建S4U模式的完整Prompt - 使用新参数结构"""
        params = {
            **context_data,
            'expression_habits_block': context_data.get('expression_habits_block', ''),
            'tool_info_block': context_data.get('tool_info_block', ''),
            'knowledge_prompt': context_data.get('knowledge_prompt', ''),
            'memory_block': context_data.get('memory_block', ''),
            'relation_info_block': context_data.get('relation_info_block', ''),
            'extra_info_block': self.parameters.content.extra_info or context_data.get('extra_info_block', ''),
            'cross_context_block': context_data.get('cross_context_block', ''),
            'identity': self.parameters.content.identity or context_data.get('identity', ''),
            'action_descriptions': self.parameters.content.actions or context_data.get('action_descriptions', ''),
            'sender_name': self.parameters.core.sender_name,
            'mood_state': self.parameters.content.mood_prompt or context_data.get('mood_state', ''),
            'background_dialogue_prompt': context_data.get('background_dialogue_prompt', ''),
            'time_block': context_data.get('time_block', ''),
            'core_dialogue_prompt': context_data.get('core_dialogue_prompt', ''),
            'reply_target_block': context_data.get('reply_target_block', ''),
            'reply_style': global_config.personality.reply_style,
            'keywords_reaction_prompt': self.parameters.content.keywords_reaction or context_data.get('keywords_reaction_prompt', ''),
            'moderation_prompt': self.parameters.content.moderation_prompt or context_data.get('moderation_prompt', ''),
        }
        return await global_prompt_manager.format_prompt(self.template_name, **params)
    
    async def _build_normal_prompt(self, template: Prompt, context_data: Dict[str, Any]) -> str:
        """构建Normal模式的完整Prompt - 使用新参数结构"""
        params = {
            **context_data,
            'expression_habits_block': context_data.get('expression_habits_block', ''),
            'tool_info_block': context_data.get('tool_info_block', ''),
            'knowledge_prompt': context_data.get('knowledge_prompt', ''),
            'memory_block': context_data.get('memory_block', ''),
            'relation_info_block': context_data.get('relation_info_block', ''),
            'extra_info_block': self.parameters.content.extra_info or context_data.get('extra_info_block', ''),
            'cross_context_block': context_data.get('cross_context_block', ''),
            'identity': self.parameters.content.identity or context_data.get('identity', ''),
            'action_descriptions': self.parameters.content.actions or context_data.get('action_descriptions', ''),
            'schedule_block': self.parameters.content.schedule_prompt or context_data.get('schedule_block', ''),
            'time_block': context_data.get('time_block', ''),
            'chat_info': context_data.get('chat_info', ''),
            'reply_target_block': context_data.get('reply_target_block', ''),
            'config_expression_style': global_config.personality.reply_style,
            'mood_state': self.parameters.content.mood_prompt or context_data.get('mood_state', ''),
            'keywords_reaction_prompt': self.parameters.content.keywords_reaction or context_data.get('keywords_reaction_prompt', ''),
            'moderation_prompt': self.parameters.content.moderation_prompt or context_data.get('moderation_prompt', ''),
        }
        return await global_prompt_manager.format_prompt(self.template_name, **params)
    
    async def _build_default_prompt(self, template: Prompt, context_data: Dict[str, Any]) -> str:
        """构建默认模式的Prompt - 使用新参数结构"""
        params = {
            'expression_habits_block': context_data.get('expression_habits_block', ''),
            'relation_info_block': context_data.get('relation_info_block', ''),
            'chat_target': "",
            'time_block': context_data.get('time_block', ''),
            'chat_info': context_data.get('chat_info', ''),
            'identity': self.parameters.content.identity or context_data.get('identity', ''),
            'chat_target_2': "",
            'reply_target_block': context_data.get('reply_target_block', ''),
            'raw_reply': self.parameters.core.target_message,
            'reason': "",
            'mood_state': self.parameters.content.mood_prompt or context_data.get('mood_state', ''),
            'reply_style': global_config.personality.reply_style,
            'keywords_reaction_prompt': self.parameters.content.keywords_reaction or context_data.get('keywords_reaction_prompt', ''),
            'moderation_prompt': self.parameters.content.moderation_prompt or context_data.get('moderation_prompt', ''),
        }
        return await global_prompt_manager.format_prompt(self.template_name, **params)


# 工厂函数 - 简化创建 - 更新参数结构
def create_smart_prompt(
    chat_id: str = "",
    sender_name: str = "",
    target_message: str = "",
    reply_to: str = "",
    **kwargs
) -> SmartPrompt:
    """快速创建智能Prompt实例的工厂函数 - 使用新参数结构"""
    
    # 使用新的参数结构
    from src.chat.utils.prompt_parameters import PromptCoreParams
    
    core_params = PromptCoreParams(
        chat_id=chat_id,
        sender_name=sender_name,
        target_message=target_message,
        reply_to=reply_to
    )
    
    # 更新features和content参数
    feature_params = kwargs.pop('features', None) or PromptFeatureParams()
    content_params = kwargs.pop('content', None) or PromptContentParams()
    
    parameters = SmartPromptParameters(
        core=core_params,
        features=feature_params,
        content=content_params,
        **kwargs
    )
    
    return SmartPrompt(parameters=parameters)


class SmartPromptHealthChecker:
    """SmartPrompt健康检查器"""
    
    @staticmethod
    async def check_system_health() -> Dict[str, Any]:
        """检查系统健康状态"""
        health_status = {
            "status": "healthy",
            "components": {},
            "issues": []
        }
        
        try:
            # 检查关键模块导入
            try:
                from src.chat.express.expression_selector import expression_selector
                health_status["components"]["expression_selector"] = "ok"
            except ImportError as e:
                health_status["components"]["expression_selector"] = f"failed: {str(e)}"
                health_status["issues"].append("expression_selector导入失败")
                health_status["status"] = "degraded"
            
            try:
                from src.chat.memory_system.memory_activator import MemoryActivator
                health_status["components"]["memory_activator"] = "ok"
            except ImportError as e:
                health_status["components"]["memory_activator"] = f"failed: {str(e)}"
                health_status["issues"].append("memory_activator导入失败")
                health_status["status"] = "degraded"
            
            try:
                from src.plugin_system.core.tool_use import ToolExecutor
                health_status["components"]["tool_executor"] = "ok"
            except ImportError as e:
                health_status["components"]["tool_executor"] = f"failed: {str(e)}"
                health_status["issues"].append("tool_executor导入失败")
                health_status["status"] = "degraded"
            
            try:
                from src.plugins.built_in.knowledge.lpmm_get_knowledge import SearchKnowledgeFromLPMMTool
                health_status["components"]["knowledge_tool"] = "ok"
            except ImportError as e:
                health_status["components"]["knowledge_tool"] = f"failed: {str(e)}"
                health_status["issues"].append("knowledge_tool导入失败")
                # 知识工具不是必需的，所以不降低整体状态
            
            # 检查配置
            try:
                from src.config.config import global_config
                health_status["components"]["config"] = "ok"
                
                # 检查关键配置项
                if not hasattr(global_config, 'personality') or not hasattr(global_config.personality, 'prompt_mode'):
                    health_status["issues"].append("缺少personality.prompt_mode配置")
                    health_status["status"] = "degraded"
                
                if not hasattr(global_config, 'memory') or not hasattr(global_config.memory, 'enable_memory'):
                    health_status["issues"].append("缺少memory.enable_memory配置")
                
            except Exception as e:
                health_status["components"]["config"] = f"failed: {str(e)}"
                health_status["issues"].append("配置加载失败")
                health_status["status"] = "unhealthy"
            
            # 检查Prompt模板
            try:
                required_templates = ["s4u_style_prompt", "normal_style_prompt", "default_expressor_prompt"]
                for template_name in required_templates:
                    try:
                        await global_prompt_manager.get_prompt_async(template_name)
                        health_status["components"][f"template_{template_name}"] = "ok"
                    except Exception as e:
                        health_status["components"][f"template_{template_name}"] = f"failed: {str(e)}"
                        health_status["issues"].append(f"模板{template_name}加载失败")
                        health_status["status"] = "degraded"
                        
            except Exception as e:
                health_status["components"]["prompt_templates"] = f"failed: {str(e)}"
                health_status["issues"].append("Prompt模板检查失败")
                health_status["status"] = "unhealthy"
            
            return health_status
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "components": {},
                "issues": [f"健康检查异常: {str(e)}"]
            }
    
    @staticmethod
    async def run_performance_test() -> Dict[str, Any]:
        """运行性能测试"""
        test_results = {
            "status": "completed",
            "tests": {},
            "summary": {}
        }
        
        try:
            # 创建测试参数
            test_params = SmartPromptParameters(
                chat_id="test_chat",
                sender="test_user",
                target="test_message",
                reply_to="test_user:test_message",
                current_prompt_mode="s4u",
                enable_cache=False  # 禁用缓存以测试真实性能
            )
            
            # 测试不同模式下的构建性能
            modes = ["s4u", "normal", "minimal"]
            for mode in modes:
                test_params.current_prompt_mode = mode
                smart_prompt = SmartPrompt(parameters=test_params)
                
                # 运行多次测试取平均值
                times = []
                for _ in range(3):
                    start_time = time.time()
                    try:
                        await smart_prompt.build_prompt()
                        end_time = time.time()
                        times.append(end_time - start_time)
                    except Exception as e:
                        times.append(float('inf'))
                        logger.error(f"性能测试失败 (模式: {mode}): {e}")
                
                # 计算统计信息
                valid_times = [t for t in times if t != float('inf')]
                if valid_times:
                    avg_time = sum(valid_times) / len(valid_times)
                    min_time = min(valid_times)
                    max_time = max(valid_times)
                    
                    test_results["tests"][mode] = {
                        "avg_time": avg_time,
                        "min_time": min_time,
                        "max_time": max_time,
                        "success_rate": len(valid_times) / len(times)
                    }
                else:
                    test_results["tests"][mode] = {
                        "avg_time": float('inf'),
                        "min_time": float('inf'),
                        "max_time": float('inf'),
                        "success_rate": 0
                    }
            
            # 计算总体统计
            all_avg_times = [test["avg_time"] for test in test_results["tests"].values() if test["avg_time"] != float('inf')]
            if all_avg_times:
                test_results["summary"] = {
                    "overall_avg_time": sum(all_avg_times) / len(all_avg_times),
                    "fastest_mode": min(test_results["tests"].items(), key=lambda x: x[1]["avg_time"])[0],
                    "slowest_mode": max(test_results["tests"].items(), key=lambda x: x[1]["avg_time"])[0]
                }
            
            return test_results
            
        except Exception as e:
            return {
                "status": "failed",
                "tests": {},
                "summary": {},
                "error": str(e)
            }