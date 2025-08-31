"""
智能提示词参数模块 - 优化参数结构
将SmartPromptParameters拆分为多个专用参数类
"""
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Literal


@dataclass
class PromptCoreParams:
    """核心参数类 - 包含构建提示词的基本参数"""
    chat_id: str = ""
    is_group_chat: bool = False
    sender: str = ""
    target: str = ""
    reply_to: str = ""
    extra_info: str = ""
    current_prompt_mode: Literal["s4u", "normal", "minimal"] = "s4u"
    
    def validate(self) -> List[str]:
        """验证核心参数"""
        errors = []
        if not isinstance(self.chat_id, str):
            errors.append("chat_id必须是字符串类型")
        if not isinstance(self.reply_to, str):
            errors.append("reply_to必须是字符串类型")
        if self.current_prompt_mode not in ["s4u", "normal", "minimal"]:
            errors.append("current_prompt_mode必须是's4u'、'normal'或'minimal'")
        return errors


@dataclass
class PromptFeatureParams:
    """功能参数类 - 控制各种功能的开关"""
    enable_tool: bool = True
    enable_memory: bool = True
    enable_expression: bool = True
    enable_relation: bool = True
    enable_cross_context: bool = True
    enable_knowledge: bool = True
    enable_cache: bool = True
    
    # 性能和缓存控制
    cache_ttl: int = 300
    max_context_messages: int = 50
    
    # 调试选项
    debug_mode: bool = False


@dataclass
class PromptContentParams:
    """内容参数类 - 包含已构建的内容块"""
    # 聊天历史和上下文
    chat_target_info: Optional[Dict[str, Any]] = None
    message_list_before_now_long: List[Dict[str, Any]] = field(default_factory=list)
    message_list_before_short: List[Dict[str, Any]] = field(default_factory=list)
    chat_talking_prompt_short: str = ""
    target_user_info: Optional[Dict[str, Any]] = None
    
    # 已构建的内容块
    expression_habits_block: str = ""
    relation_info: str = ""
    memory_block: str = ""
    tool_info: str = ""
    prompt_info: str = ""
    cross_context_block: str = ""
    
    # 其他内容块
    keywords_reaction_prompt: str = ""
    extra_info_block: str = ""
    time_block: str = ""
    identity_block: str = ""
    schedule_block: str = ""
    moderation_prompt_block: str = ""
    reply_target_block: str = ""
    mood_prompt: str = ""
    action_descriptions: str = ""
    
    def has_prebuilt_content(self) -> bool:
        """检查是否有预构建的内容"""
        return any([
            self.expression_habits_block,
            self.relation_info,
            self.memory_block,
            self.tool_info,
            self.prompt_info,
            self.cross_context_block
        ])


@dataclass
class SmartPromptParameters:
    """
    智能提示词参数系统 - 重构版本
    组合多个专用参数类，提供统一的接口
    """
    # 核心参数
    core: PromptCoreParams = field(default_factory=PromptCoreParams)
    
    # 功能参数
    features: PromptFeatureParams = field(default_factory=PromptFeatureParams)
    
    # 内容参数
    content: PromptContentParams = field(default_factory=PromptContentParams)
    
    # 兼容性属性 - 提供与旧代码的兼容性
    @property
    def chat_id(self) -> str:
        return self.core.chat_id
    
    @chat_id.setter
    def chat_id(self, value: str):
        self.core.chat_id = value
    
    @property
    def is_group_chat(self) -> bool:
        return self.core.is_group_chat
    
    @is_group_chat.setter
    def is_group_chat(self, value: bool):
        self.core.is_group_chat = value
    
    @property
    def sender(self) -> str:
        return self.core.sender
    
    @sender.setter
    def sender(self, value: str):
        self.core.sender = value
    
    @property
    def target(self) -> str:
        return self.core.target
    
    @target.setter
    def target(self, value: str):
        self.core.target = value
    
    @property
    def reply_to(self) -> str:
        return self.core.reply_to
    
    @reply_to.setter
    def reply_to(self, value: str):
        self.core.reply_to = value
    
    @property
    def extra_info(self) -> str:
        return self.core.extra_info
    
    @extra_info.setter
    def extra_info(self, value: str):
        self.core.extra_info = value
    
    @property
    def current_prompt_mode(self) -> str:
        return self.core.current_prompt_mode
    
    @current_prompt_mode.setter
    def current_prompt_mode(self, value: str):
        self.core.current_prompt_mode = value
    
    @property
    def enable_tool(self) -> bool:
        return self.features.enable_tool
    
    @enable_tool.setter
    def enable_tool(self, value: bool):
        self.features.enable_tool = value
    
    @property
    def enable_memory(self) -> bool:
        return self.features.enable_memory
    
    @enable_memory.setter
    def enable_memory(self, value: bool):
        self.features.enable_memory = value
    
    @property
    def enable_cache(self) -> bool:
        return self.features.enable_cache
    
    @enable_cache.setter
    def enable_cache(self, value: bool):
        self.features.enable_cache = value
    
    @property
    def cache_ttl(self) -> int:
        return self.features.cache_ttl
    
    @cache_ttl.setter
    def cache_ttl(self, value: int):
        self.features.cache_ttl = value
    
    @property
    def expression_habits_block(self) -> str:
        return self.content.expression_habits_block
    
    @expression_habits_block.setter
    def expression_habits_block(self, value: str):
        self.content.expression_habits_block = value
    
    @property
    def relation_info(self) -> str:
        return self.content.relation_info
    
    @relation_info.setter
    def relation_info(self, value: str):
        self.content.relation_info = value
    
    @property
    def memory_block(self) -> str:
        return self.content.memory_block
    
    @memory_block.setter
    def memory_block(self, value: str):
        self.content.memory_block = value
    
    @property
    def tool_info(self) -> str:
        return self.content.tool_info
    
    @tool_info.setter
    def tool_info(self, value: str):
        self.content.tool_info = value
    
    @property
    def prompt_info(self) -> str:
        return self.content.prompt_info
    
    @prompt_info.setter
    def prompt_info(self, value: str):
        self.content.prompt_info = value
    
    @property
    def cross_context_block(self) -> str:
        return self.content.cross_context_block
    
    @cross_context_block.setter
    def cross_context_block(self, value: str):
        self.content.cross_context_block = value
    
    # 兼容性方法 - 支持旧代码的直接访问
    def validate(self) -> List[str]:
        """参数验证"""
        errors = self.core.validate()
        
        # 验证功能参数
        if self.features.cache_ttl <= 0:
            errors.append("cache_ttl必须大于0")
        if self.features.max_context_messages <= 0:
            errors.append("max_context_messages必须大于0")
            
        return errors
    
    def get_needed_build_tasks(self) -> List[str]:
        """获取需要执行的任务列表"""
        tasks = []
        
        if self.features.enable_expression and not self.content.expression_habits_block:
            tasks.append("expression_habits")
        
        if self.features.enable_memory and not self.content.memory_block:
            tasks.append("memory_block")
        
        if self.features.enable_relation and not self.content.relation_info:
            tasks.append("relation_info")
        
        if self.features.enable_tool and not self.content.tool_info:
            tasks.append("tool_info")
        
        if self.features.enable_knowledge and not self.content.prompt_info:
            tasks.append("knowledge_info")
        
        if self.features.enable_cross_context and not self.content.cross_context_block:
            tasks.append("cross_context")
        
        return tasks
    
    @classmethod
    def from_legacy_params(cls, **kwargs) -> 'SmartPromptParameters':
        """
        从旧版参数创建新参数对象
        
        Args:
            **kwargs: 旧版参数
            
        Returns:
            SmartPromptParameters: 新参数对象
        """
        # 创建核心参数
        core_params = PromptCoreParams(
            chat_id=kwargs.get("chat_id", ""),
            is_group_chat=kwargs.get("is_group_chat", False),
            sender=kwargs.get("sender", ""),
            target=kwargs.get("target", ""),
            reply_to=kwargs.get("reply_to", ""),
            extra_info=kwargs.get("extra_info", ""),
            current_prompt_mode=kwargs.get("current_prompt_mode", "s4u"),
        )
        
        # 创建功能参数
        feature_params = PromptFeatureParams(
            enable_tool=kwargs.get("enable_tool", True),
            enable_memory=kwargs.get("enable_memory", True),
            enable_expression=kwargs.get("enable_expression", True),
            enable_relation=kwargs.get("enable_relation", True),
            enable_cross_context=kwargs.get("enable_cross_context", True),
            enable_knowledge=kwargs.get("enable_knowledge", True),
            enable_cache=kwargs.get("enable_cache", True),
            cache_ttl=kwargs.get("cache_ttl", 300),
            max_context_messages=kwargs.get("max_context_messages", 50),
            debug_mode=kwargs.get("debug_mode", False),
        )
        
        # 创建内容参数
        content_params = PromptContentParams(
            chat_target_info=kwargs.get("chat_target_info"),
            message_list_before_now_long=kwargs.get("message_list_before_now_long", []),
            message_list_before_short=kwargs.get("message_list_before_short", []),
            chat_talking_prompt_short=kwargs.get("chat_talking_prompt_short", ""),
            target_user_info=kwargs.get("target_user_info"),
            expression_habits_block=kwargs.get("expression_habits_block", ""),
            relation_info=kwargs.get("relation_info", ""),
            memory_block=kwargs.get("memory_block", ""),
            tool_info=kwargs.get("tool_info", ""),
            prompt_info=kwargs.get("prompt_info", ""),
            cross_context_block=kwargs.get("cross_context_block", ""),
            keywords_reaction_prompt=kwargs.get("keywords_reaction_prompt", ""),
            extra_info_block=kwargs.get("extra_info_block", ""),
            time_block=kwargs.get("time_block", ""),
            identity_block=kwargs.get("identity_block", ""),
            schedule_block=kwargs.get("schedule_block", ""),
            moderation_prompt_block=kwargs.get("moderation_prompt_block", ""),
            reply_target_block=kwargs.get("reply_target_block", ""),
            mood_prompt=kwargs.get("mood_prompt", ""),
            action_descriptions=kwargs.get("action_descriptions", ""),
        )
        
        return cls(
            core=core_params,
            features=feature_params,
            content=content_params
        )