from abc import ABC, abstractmethod
from typing import Tuple, Optional, List, Union

from src.common.logger import get_logger
from .component_types import EventType, EventHandlerInfo, ComponentType

logger = get_logger("base_event_handler")


class BaseEventHandler(ABC):
    """事件处理器基类

    所有事件处理器都应该继承这个基类，提供事件处理的基本接口
    """

    handler_name: str = ""
    """处理器名称"""
    handler_description: str = ""
    """处理器描述"""
    weight: int = 0
    """处理器权重，越大权重越高"""
    intercept_message: bool = False
    """是否拦截消息，默认为否"""
    init_subscribe: List[Union[EventType, str]] = [EventType.UNKNOWN]
    """初始化时订阅的事件名称"""
    plugin_name = None

    def __init__(self):
        self.log_prefix = "[EventHandler]"
        """对应插件名"""

        self.subscribed_events = []
        """订阅的事件列表"""
        if EventType.UNKNOWN in self.init_subscribe:
            raise NotImplementedError("事件处理器必须指定 event_type")

        # 优先使用实例级别的 plugin_config，如果没有则使用类级别的配置
        # 事件管理器会在注册时通过 set_plugin_config 设置实例级别的配置
        instance_config = getattr(self, "plugin_config", None)
        if instance_config is not None:
            self.plugin_config = instance_config
        else:
            # 如果实例级别没有配置，则使用类级别的配置（向后兼容）
            self.plugin_config = getattr(self.__class__, "plugin_config", {})

    @abstractmethod
    async def execute(self, kwargs: dict | None) -> Tuple[bool, bool, Optional[str]]:
        """执行事件处理的抽象方法，子类必须实现
        Args:
            kwargs (dict | None): 事件消息对象，当你注册的事件为ON_START和ON_STOP时message为None
        Returns:
            Tuple[bool, bool, Optional[str]]: (是否执行成功, 是否需要继续处理, 可选的返回消息)
        """
        raise NotImplementedError("子类必须实现 execute 方法")

    def subscribe(self, event_name: str) -> None:
        """订阅一个事件

        Args:
            event_name (str): 要订阅的事件名称
        """
        from src.plugin_system.core.event_manager import event_manager

        if not event_manager.subscribe_handler_to_event(self.handler_name, event_name):
            logger.error(f"事件处理器 {self.handler_name} 订阅事件 {event_name} 失败")
            return

        logger.debug(f"{self.log_prefix} 订阅事件 {event_name}")
        self.subscribed_events.append(event_name)

    def unsubscribe(self, event_name: str) -> None:
        """取消订阅一个事件

        Args:
            event_name (str): 要取消订阅的事件名称
        """
        from src.plugin_system.core.event_manager import event_manager

        if event_manager.unsubscribe_handler_from_event(self.handler_name, event_name):
            logger.debug(f"{self.log_prefix} 取消订阅事件 {event_name}")
            if event_name in self.subscribed_events:
                self.subscribed_events.remove(event_name)
        else:
            logger.warning(f"{self.log_prefix} 未订阅事件 {event_name}，无法取消订阅")

    @classmethod
    def get_handler_info(cls) -> "EventHandlerInfo":
        """获取事件处理器的信息"""
        # 从类属性读取名称，如果没有定义则使用类名自动生成
        name: str = getattr(cls, "handler_name", cls.__name__.lower().replace("handler", ""))
        if "." in name:
            logger.error(f"事件处理器名称 '{name}' 包含非法字符 '.'，请使用下划线替代")
            raise ValueError(f"事件处理器名称 '{name}' 包含非法字符 '.'，请使用下划线替代")
        return EventHandlerInfo(
            name=name,
            component_type=ComponentType.EVENT_HANDLER,
            description=getattr(cls, "handler_description", "events处理器"),
            weight=cls.weight,
            intercept_message=cls.intercept_message,
        )

    def set_plugin_name(self, plugin_name: str) -> None:
        """设置插件名称

        Args:
            plugin_name (str): 插件名称
        """
        self.plugin_name = plugin_name

    def set_plugin_config(self, plugin_config) -> None:
        self.plugin_config = plugin_config

    def get_config(self, key: str, default=None):
        """获取插件配置值，支持嵌套键访问

        Args:
            key: 配置键名，支持嵌套访问如 "section.subsection.key"
            default: 默认值

        Returns:
            Any: 配置值或默认值
        """
        if not self.plugin_config:
            return default

        # 支持嵌套键访问
        keys = key.split(".")
        current = self.plugin_config

        for k in keys:
            if isinstance(current, dict) and k in current:
                current = current[k]
            else:
                return default

        return current
