"""
智能Prompt系统 - 基于现有模板系统的增强构建器
"""
import asyncio
import time
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Literal
from contextlib import asynccontextmanager

from src.chat.utils.prompt_builder import global_prompt_manager, Prompt


@dataclass
class SmartPromptParameters:
    """智能提示词参数系统"""
    
    # === 核心对话参数 ===
    reply_to: str = ""
    extra_info: str = ""
    available_actions: Dict[str, Any] = field(default_factory=dict)
    
    # === 功能开关 ===
    enable_tool: bool = True
    enable_memory: bool = True
    enable_expression: bool = True
    enable_relation: bool = True
    enable_cross_context: bool = True
    enable_knowledge: bool = True
    
    # === 行为配置 ===
    prompt_mode: Literal["s4u", "normal", "minimal"] = "s4u"
    context_level: Literal["full", "core", "minimal"] = "full"
    response_style: Optional[str] = None
    tone_override: Optional[str] = None
    
    # === 智能过滤 ===
    max_context_messages: int = 50
    memory_depth: int = 3
    expression_count: int = 5
    knowledge_depth: int = 3
    
    # === 性能控制 ===
    max_tokens: int = 2048
    timeout_seconds: float = 30.0
    enable_cache: bool = True
    cache_ttl: int = 300
    
    # === 调试选项 ===
    debug_mode: bool = False
    include_timing: bool = False
    trace_id: Optional[str] = None
    
    def validate(self) -> List[str]:
        """参数验证"""
        errors = []
        if not isinstance(self.reply_to, str):
            errors.append("reply_to必须是字符串类型")
        if self.timeout_seconds <= 0:
            errors.append("timeout_seconds必须大于0")
        if self.max_tokens <= 0:
            errors.append("max_tokens必须大于0")
        return errors


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


class ContextData:
    """构建上下文数据容器"""
    
    def __init__(self):
        self.data: Dict[str, Any] = {}
        self.timing: Dict[str, float] = {}
        self.errors: List[str] = []
        
    def set(self, key: str, value: Any, timing: float = 0.0):
        """设置数据"""
        self.data[key] = value
        if timing > 0:
            self.timing[key] = timing
            
    def get(self, key: str, default: Any = None) -> Any:
        """获取数据"""
        return self.data.get(key, default)
        
    def merge(self, other_data: Dict[str, Any]):
        """合并数据"""
        self.data.update(other_data)
        
    def auto_compensate(self):
        """自动补偿缺失数据"""
        defaults = {
            "expression_habits_block": "",
            "memory_block": "",
            "relation_info_block": "",
            "tool_info_block": "",
            "knowledge_prompt": "",
            "cross_context_block": "",
            "time_block": f"当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "mood_state": "平静",
            "identity": "你是一个智能助手",
        }
        
        for key, default_value in defaults.items():
            if key not in self.data:
                self.data[key] = default_value
                
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return self.data.copy()


class SmartPromptCache:
    """智能缓存系统"""
    
    def __init__(self):
        self._cache: Dict[str, tuple[str, float, int]] = {}
        
    def _generate_key(self, params: SmartPromptParameters, context: ChatContext) -> str:
        """生成缓存键"""
        key_parts = [
            params.reply_to,
            context.chat_id,
            str(params.enable_tool),
            str(params.enable_memory),
            params.prompt_mode,
        ]
        return "|".join(key_parts)
        
    def get(self, params: SmartPromptParameters, context: ChatContext) -> Optional[str]:
        """获取缓存"""
        if not params.enable_cache:
            return None
            
        key = self._generate_key(params, context)
        if key in self._cache:
            text, timestamp, ttl = self._cache[key]
            if time.time() - timestamp < ttl:
                return text
            else:
                del self._cache[key]
        return None
        
    def set(self, params: SmartPromptParameters, context: ChatContext, text: str):
        """设置缓存"""
        if not params.enable_cache:
            return
            
        key = self._generate_key(params, context)
        self._cache[key] = (text, time.time(), params.cache_ttl)
        
    def clear(self):
        """清空缓存"""
        self._cache.clear()


class SmartPromptBuilder:
    """智能提示词构建器"""
    
    def __init__(self):
        self.cache = SmartPromptCache()
        
    async def build_context_data(
        self, 
        context: ChatContext, 
        params: SmartPromptParameters
    ) -> ContextData:
        """并行构建上下文数据"""
        
        # 检查缓存
        cached_result = self.cache.get(params, context)
        if cached_result:
            context_data = ContextData()
            context_data.data["_cached_text"] = cached_result
            return context_data
            
        # 创建构建任务
        tasks = []
        context_data = ContextData()
        
        # 根据参数启用不同的构建任务
        if params.enable_expression:
            tasks.append(self._build_expression_habits(context, params))
            
        if params.enable_memory:
            tasks.append(self._build_memory_block(context, params))
            
        if params.enable_relation:
            tasks.append(self._build_relation_info(context, params))
            
        if params.enable_tool:
            tasks.append(self._build_tool_info(context, params))
            
        if params.enable_knowledge:
            tasks.append(self._build_knowledge_info(context, params))
            
        if params.enable_cross_context:
            tasks.append(self._build_cross_context(context, params))
            
        # 并行执行所有任务
        start_time = time.time()
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=params.timeout_seconds
            )
            
            # 处理结果
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    context_data.errors.append(f"任务{i}失败: {str(result)}")
                else:
                    context_data.merge(result)
                    
        except asyncio.TimeoutError:
            context_data.errors.append(f"构建超时 ({params.timeout_seconds}s)")
            
        # 自动补偿缺失数据
        context_data.auto_compensate()
        
        # 添加时间信息
        if params.include_timing:
            context_data.set("build_time", time.time() - start_time)
            
        return context_data
        
    async def _build_expression_habits(self, context: ChatContext, params: SmartPromptParameters) -> Dict[str, Any]:
        """构建表达习惯 - 集成现有DefaultReplyer的表达方式"""
        # 这里需要更复杂的集成，暂时返回空
        return {
            "expression_habits_block": ""
        }
        
    async def _build_memory_block(self, context: ChatContext, params: SmartPromptParameters) -> Dict[str, Any]:
        """构建记忆块 - 集成现有DefaultReplyer的记忆构建"""
        # 这里需要集成真正的记忆构建逻辑
        return {
            "memory_block": ""
        }
        
    async def _build_relation_info(self, context: ChatContext, params: SmartPromptParameters) -> Dict[str, Any]:
        """构建关系信息 - 集成现有DefaultReplyer的关系构建"""
        # 这里需要集成真正的关系构建逻辑
        return {
            "relation_info_block": ""
        }
        
    async def _build_tool_info(self, context: ChatContext, params: SmartPromptParameters) -> Dict[str, Any]:
        """构建工具信息 - 集成现有DefaultReplyer的工具构建"""
        # 这里需要集成真正的工具构建逻辑
        return {
            "tool_info_block": ""
        }
        
    async def _build_knowledge_info(self, context: ChatContext, params: SmartPromptParameters) -> Dict[str, Any]:
        """构建知识信息 - 集成现有DefaultReplyer的知识构建"""
        # 这里需要集成真正的知识构建逻辑
        return {
            "knowledge_prompt": ""
        }
        
    async def _build_cross_context(self, context: ChatContext, params: SmartPromptParameters) -> Dict[str, Any]:
        """构建跨群上下文 - 集成现有DefaultReplyer的跨群构建"""
        # 这里需要集成真正的跨群构建逻辑
        return {
            "cross_context_block": ""
        }


class SmartPrompt:
    """智能提示词核心类 - 完全基于现有模板系统"""
    
    def __init__(
        self,
        template_name: str = "default",
        parameters: Optional[SmartPromptParameters] = None,
        context: Optional[ChatContext] = None,
    ):
        self.template_name = template_name
        self.parameters = parameters or SmartPromptParameters()
        self.context = context or ChatContext()
        self.builder = SmartPromptBuilder()
        self._cached_text: Optional[str] = None
        self._cache_time: float = 0
        
    async def to_text(self) -> str:
        """异步渲染为文本 - 完全使用现有模板系统"""
        return await self.build_prompt()
        
    def to_text_sync(self) -> str:
        """同步渲染为文本"""
        return asyncio.run(self.build_prompt())
        
    async def build_prompt(self) -> str:
        """构建Prompt - 替代to_text方法以兼容调用方式"""
        # 参数验证
        errors = self.parameters.validate()
        if errors:
            raise ValueError(f"参数验证失败: {', '.join(errors)}")
            
        # 检查缓存
        if self._cached_text and self.parameters.enable_cache:
            if time.time() - self._cache_time < self.parameters.cache_ttl:
                return self._cached_text
                
        # 构建上下文数据
        context_data = await self.builder.build_context_data(self.context, self.parameters)
        
        # 检查是否有缓存的文本
        if "_cached_text" in context_data.data:
            return context_data.data["_cached_text"]
            
        # 获取模板 - 完全使用现有系统
        template = await self._get_template()
        
        # 渲染最终文本 - 完全使用现有系统
        text = await self._render_template(template, context_data)
        
        # 缓存结果
        if self.parameters.enable_cache:
            self._cached_text = text
            self._cache_time = time.time()
            self.builder.cache.set(self.parameters, self.context, text)
            
        return text
        
    async def _get_template(self) -> Prompt:
        """获取模板 - 完全使用现有系统"""
        try:
            return await global_prompt_manager.get_prompt_async(self.template_name)
        except KeyError:
            # 使用默认模板
            return Prompt("你是一个智能助手。用户说：{reply_target_block}", name="default")
            
    async def _render_template(self, template: Prompt, context_data: ContextData) -> str:
        """渲染模板 - 完全使用现有系统"""
        # 准备渲染参数
        render_params = {
            **context_data.to_dict(),
            "reply_target_block": self._build_reply_target_block(),
            "extra_info_block": self.parameters.extra_info,
            "action_descriptions": self._build_action_descriptions(),
        }
        
        # 根据模式选择不同的渲染策略
        if self.parameters.prompt_mode == "minimal":
            # 最小化模式，只包含核心信息
            minimal_params = {
                "reply_target_block": render_params["reply_target_block"],
                "identity": render_params.get("identity", ""),
                "time_block": render_params.get("time_block", ""),
            }
            # 使用现有模板的format方法
            return template.format(**minimal_params)
        else:
            # 完整模式 - 使用现有系统的格式化方法
            return template.format(**render_params)
            
    def _build_reply_target_block(self) -> str:
        """构建回复目标块"""
        if not self.parameters.reply_to:
            return "现在，请进行回复。"
            
        sender, content = self._parse_reply_to(self.parameters.reply_to)
        if sender and content:
            return f"现在{sender}说：{content}。请对此进行回复。"
        else:
            return f"现在有消息：{self.parameters.reply_to}。请对此进行回复。"
            
    def _build_action_descriptions(self) -> str:
        """构建动作描述"""
        if not self.parameters.available_actions:
            return ""
            
        descriptions = []
        for action_name, action_info in self.parameters.available_actions.items():
            if isinstance(action_info, dict) and "description" in action_info:
                descriptions.append(f"- {action_name}: {action_info['description']}")
            else:
                descriptions.append(f"- {action_name}")
                
        if descriptions:
            return "你有以下动作能力：\n" + "\n".join(descriptions) + "\n"
        return ""
        
    def _parse_reply_to(self, reply_to: str) -> tuple[str, str]:
        """解析回复目标"""
        if ":" in reply_to or "：" in reply_to:
            import re
            parts = re.split(r"[:：]", reply_to, maxsplit=1)
            if len(parts) == 2:
                return parts[0].strip(), parts[1].strip()
        return "", reply_to.strip()
        
    def __str__(self) -> str:
        """字符串表示"""
        return f"SmartPrompt(template={self.template_name}, mode={self.parameters.prompt_mode})"
        
    def __repr__(self) -> str:
        """详细表示"""
        return f"SmartPrompt(template='{self.template_name}', parameters={self.parameters}, context={self.context})"


# 工厂函数
def create_smart_prompt(
    template_name: str = "default",
    reply_to: str = "",
    extra_info: str = "",
    enable_tool: bool = True,
    prompt_mode: str = "s4u",
    chat_id: str = "",
    **kwargs
) -> SmartPrompt:
    """快速创建智能Prompt实例的工厂函数"""
    
    parameters = SmartPromptParameters(
        reply_to=reply_to,
        extra_info=extra_info,
        enable_tool=enable_tool,
        prompt_mode=prompt_mode,
        **kwargs
    )
    
    context = ChatContext(chat_id=chat_id)
    
    return SmartPrompt(
        template_name=template_name,
        parameters=parameters,
        context=context
    )


# 便捷装饰器
def prompt_template(name: str):
    """模板注册装饰器 - 与现有系统保持一致"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            template_content = func(*args, **kwargs)
            Prompt(template_content, name=name)
            return template_content
        return wrapper
    return decorator