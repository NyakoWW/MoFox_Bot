from pathlib import Path
import re

from typing import Dict, List, Optional, Any, Pattern, Tuple, Union, Type

from src.common.logger import get_logger
from src.plugin_system.base.component_types import (
    ComponentInfo,
    ActionInfo,
    ToolInfo,
    CommandInfo,
    PlusCommandInfo,
    EventHandlerInfo,
    PluginInfo,
    ComponentType,
)
from src.plugin_system.base.base_command import BaseCommand
from src.plugin_system.base.base_action import BaseAction
from src.plugin_system.base.base_tool import BaseTool
from src.plugin_system.base.base_events_handler import BaseEventHandler
from src.plugin_system.base.plus_command import PlusCommand

logger = get_logger("component_registry")


class ComponentRegistry:
    """统一的组件注册中心

    负责管理所有插件组件的注册、查询和生命周期管理
    """

    def __init__(self):
        # 命名空间式组件名构成法 f"{component_type}.{component_name}"
        self._plus_command_registry: Dict[str, Type[PlusCommand]] = {}
        self._components: Dict[str, ComponentInfo] = {}
        """组件注册表 命名空间式组件名 -> 组件信息"""
        self._components_by_type: Dict[ComponentType, Dict[str, ComponentInfo]] = {types: {} for types in ComponentType}
        """类型 -> 组件原名称 -> 组件信息"""
        self._components_classes: Dict[
            str, Type[Union[BaseCommand, BaseAction, BaseTool, BaseEventHandler, PlusCommand]]
        ] = {}
        """命名空间式组件名 -> 组件类"""

        # 插件注册表
        self._plugins: Dict[str, PluginInfo] = {}
        """插件名 -> 插件信息"""

        # Action特定注册表
        self._action_registry: Dict[str, Type[BaseAction]] = {}
        """Action注册表 action名 -> action类"""
        self._default_actions: Dict[str, ActionInfo] = {}
        """默认动作集，即启用的Action集，用于重置ActionManager状态"""

        # Command特定注册表
        self._command_registry: Dict[str, Type[BaseCommand]] = {}
        """Command类注册表 command名 -> command类"""
        self._command_patterns: Dict[Pattern, str] = {}
        """编译后的正则 -> command名"""

        # 工具特定注册表
        self._tool_registry: Dict[str, Type[BaseTool]] = {}  # 工具名 -> 工具类
        self._llm_available_tools: Dict[str, Type[BaseTool]] = {}  # llm可用的工具名 -> 工具类

        # EventHandler特定注册表
        self._event_handler_registry: Dict[str, Type[BaseEventHandler]] = {}
        """event_handler名 -> event_handler类"""
        self._enabled_event_handlers: Dict[str, Type[BaseEventHandler]] = {}
        """启用的事件处理器 event_handler名 -> event_handler类"""

        logger.info("组件注册中心初始化完成")

    # == 注册方法 ==

    def register_plugin(self, plugin_info: PluginInfo) -> bool:
        """注册插件

        Args:
            plugin_info: 插件信息

        Returns:
            bool: 是否注册成功
        """
        plugin_name = plugin_info.name

        if plugin_name in self._plugins:
            logger.warning(f"插件 {plugin_name} 已存在，跳过注册")
            return False

        self._plugins[plugin_name] = plugin_info
        logger.debug(f"已注册插件: {plugin_name} (组件数量: {len(plugin_info.components)})")
        return True

    def register_component(
        self,
        component_info: ComponentInfo,
        component_class: Type[Union[BaseCommand, BaseAction, BaseEventHandler, BaseTool]],
    ) -> bool:
        """注册组件

        Args:
            component_info (ComponentInfo): 组件信息
            component_class (Type[Union[BaseCommand, BaseAction, BaseEventHandler]]): 组件类

        Returns:
            bool: 是否注册成功
        """
        component_name = component_info.name
        component_type = component_info.component_type
        plugin_name = getattr(component_info, "plugin_name", "unknown")
        if "." in component_name:
            logger.error(f"组件名称 '{component_name}' 包含非法字符 '.'，请使用下划线替代")
            return False
        if "." in plugin_name:
            logger.error(f"插件名称 '{plugin_name}' 包含非法字符 '.'，请使用下划线替代")
            return False

        namespaced_name = f"{component_type}.{component_name}"

        if namespaced_name in self._components:
            existing_info = self._components[namespaced_name]
            existing_plugin = getattr(existing_info, "plugin_name", "unknown")

            logger.warning(
                f"组件名冲突: '{plugin_name}' 插件的 {component_type} 类型组件 '{component_name}' 已被插件 '{existing_plugin}' 注册，跳过此组件注册"
            )
            return False

        self._components[namespaced_name] = component_info  # 注册到通用注册表（使用命名空间化的名称）
        self._components_by_type[component_type][component_name] = component_info  # 类型内部仍使用原名
        self._components_classes[namespaced_name] = component_class

        # 根据组件类型进行特定注册（使用原始名称）
        match component_type:
            case ComponentType.ACTION:
                assert isinstance(component_info, ActionInfo)
                assert issubclass(component_class, BaseAction)
                ret = self._register_action_component(component_info, component_class)
            case ComponentType.COMMAND:
                assert isinstance(component_info, CommandInfo)
                assert issubclass(component_class, BaseCommand)
                ret = self._register_command_component(component_info, component_class)
            case ComponentType.PLUS_COMMAND:
                assert isinstance(component_info, PlusCommandInfo)
                assert issubclass(component_class, PlusCommand)
                ret = self._register_plus_command_component(component_info, component_class)
            case ComponentType.TOOL:
                assert isinstance(component_info, ToolInfo)
                assert issubclass(component_class, BaseTool)
                ret = self._register_tool_component(component_info, component_class)
            case ComponentType.EVENT_HANDLER:
                assert isinstance(component_info, EventHandlerInfo)
                assert issubclass(component_class, BaseEventHandler)
                ret = self._register_event_handler_component(component_info, component_class)
            case _:
                logger.warning(f"未知组件类型: {component_type}")

        if not ret:
            return False
        logger.debug(
            f"已注册{component_type}组件: '{component_name}' -> '{namespaced_name}' "
            f"({component_class.__name__}) [插件: {plugin_name}]"
        )
        return True

    def _register_action_component(self, action_info: ActionInfo, action_class: Type[BaseAction]) -> bool:
        """注册Action组件到Action特定注册表"""
        if not (action_name := action_info.name):
            logger.error(f"Action组件 {action_class.__name__} 必须指定名称")
            return False
        if not isinstance(action_info, ActionInfo) or not issubclass(action_class, BaseAction):
            logger.error(f"注册失败: {action_name} 不是有效的Action")
            return False

        action_class.plugin_name = action_info.plugin_name
        # 设置插件配置
        action_class.plugin_config = self.get_plugin_config(action_info.plugin_name) or {}
        self._action_registry[action_name] = action_class

        # 如果启用，添加到默认动作集
        if action_info.enabled:
            self._default_actions[action_name] = action_info

        return True

    def _register_command_component(self, command_info: CommandInfo, command_class: Type[BaseCommand]) -> bool:
        """注册Command组件到Command特定注册表"""
        if not (command_name := command_info.name):
            logger.error(f"Command组件 {command_class.__name__} 必须指定名称")
            return False
        if not isinstance(command_info, CommandInfo) or not issubclass(command_class, BaseCommand):
            logger.error(f"注册失败: {command_name} 不是有效的Command")
            return False

        command_class.plugin_name = command_info.plugin_name
        # 设置插件配置
        command_class.plugin_config = self.get_plugin_config(command_info.plugin_name) or {}
        self._command_registry[command_name] = command_class

        # 如果启用了且有匹配模式
        if command_info.enabled and command_info.command_pattern:
            pattern = re.compile(command_info.command_pattern, re.IGNORECASE | re.DOTALL)
            if pattern not in self._command_patterns:
                self._command_patterns[pattern] = command_name
            else:
                logger.warning(
                    f"'{command_name}' 对应的命令模式与 '{self._command_patterns[pattern]}' 重复，忽略此命令"
                )

        return True

    def _register_plus_command_component(
        self, plus_command_info: PlusCommandInfo, plus_command_class: Type[PlusCommand]
    ) -> bool:
        """注册PlusCommand组件到特定注册表"""
        plus_command_name = plus_command_info.name

        if not plus_command_name:
            logger.error(f"PlusCommand组件 {plus_command_class.__name__} 必须指定名称")
            return False
        if not isinstance(plus_command_info, PlusCommandInfo) or not issubclass(plus_command_class, PlusCommand):
            logger.error(f"注册失败: {plus_command_name} 不是有效的PlusCommand")
            return False

        # 创建专门的PlusCommand注册表（如果还没有）
        if not hasattr(self, "_plus_command_registry"):
            self._plus_command_registry: Dict[str, Type[PlusCommand]] = {}

        plus_command_class.plugin_name = plus_command_info.plugin_name
        # 设置插件配置
        plus_command_class.plugin_config = self.get_plugin_config(plus_command_info.plugin_name) or {}
        self._plus_command_registry[plus_command_name] = plus_command_class

        logger.debug(f"已注册PlusCommand组件: {plus_command_name}")
        return True

    def _register_tool_component(self, tool_info: ToolInfo, tool_class: Type[BaseTool]) -> bool:
        """注册Tool组件到Tool特定注册表"""
        tool_name = tool_info.name

        tool_class.plugin_name = tool_info.plugin_name
        # 设置插件配置
        tool_class.plugin_config = self.get_plugin_config(tool_info.plugin_name) or {}
        self._tool_registry[tool_name] = tool_class

        # 如果是llm可用的且启用的工具,添加到 llm可用工具列表
        if tool_info.enabled:
            self._llm_available_tools[tool_name] = tool_class

        return True

    def _register_event_handler_component(
        self, handler_info: EventHandlerInfo, handler_class: Type[BaseEventHandler]
    ) -> bool:
        if not (handler_name := handler_info.name):
            logger.error(f"EventHandler组件 {handler_class.__name__} 必须指定名称")
            return False
        if not isinstance(handler_info, EventHandlerInfo) or not issubclass(handler_class, BaseEventHandler):
            logger.error(f"注册失败: {handler_name} 不是有效的EventHandler")
            return False

        handler_class.plugin_name = handler_info.plugin_name
        # 设置插件配置
        handler_class.plugin_config = self.get_plugin_config(handler_info.plugin_name) or {}
        self._event_handler_registry[handler_name] = handler_class

        if not handler_info.enabled:
            logger.warning(f"EventHandler组件 {handler_name} 未启用")
            return True  # 未启用，但是也是注册成功

        handler_class.plugin_name = handler_info.plugin_name
        # 使用EventManager进行事件处理器注册
        from src.plugin_system.core.event_manager import event_manager

        return event_manager.register_event_handler(handler_class,self.get_plugin_config(handler_info.plugin_name) or {})

    # === 组件移除相关 ===

    async def remove_component(self, component_name: str, component_type: ComponentType, plugin_name: str) -> bool:
        target_component_class = self.get_component_class(component_name, component_type)
        if not target_component_class:
            logger.warning(f"组件 {component_name} 未注册，无法移除")
            return False
        try:
            # 根据组件类型进行特定的清理操作
            match component_type:
                case ComponentType.ACTION:
                    # 移除Action注册
                    self._action_registry.pop(component_name, None)
                    self._default_actions.pop(component_name, None)
                    logger.debug(f"已移除Action组件: {component_name}")

                case ComponentType.COMMAND:
                    # 移除Command注册和模式
                    self._command_registry.pop(component_name, None)
                    keys_to_remove = [k for k, v in self._command_patterns.items() if v == component_name]
                    for key in keys_to_remove:
                        self._command_patterns.pop(key, None)
                    logger.debug(f"已移除Command组件: {component_name} (清理了 {len(keys_to_remove)} 个模式)")

                case ComponentType.PLUS_COMMAND:
                    # 移除PlusCommand注册
                    if hasattr(self, "_plus_command_registry"):
                        self._plus_command_registry.pop(component_name, None)
                    logger.debug(f"已移除PlusCommand组件: {component_name}")

                case ComponentType.TOOL:
                    # 移除Tool注册
                    self._tool_registry.pop(component_name, None)
                    self._llm_available_tools.pop(component_name, None)
                    logger.debug(f"已移除Tool组件: {component_name}")

                case ComponentType.EVENT_HANDLER:
                    # 移除EventHandler注册和事件订阅
                    from .event_manager import event_manager  # 延迟导入防止循环导入问题

                    self._event_handler_registry.pop(component_name, None)
                    self._enabled_event_handlers.pop(component_name, None)
                    try:
                        handler = event_manager.get_event_handler(component_name)
                        for event in handler.subscribed_events:
                            await event_manager.unsubscribe_handler_from_event(event, component_name)
                        logger.debug(f"已移除EventHandler组件: {component_name}")
                    except Exception as e:
                        logger.warning(f"移除EventHandler事件订阅时出错: {e}")

                case _:
                    logger.warning(f"未知的组件类型: {component_type}")
                    return False

            # 移除通用注册信息
            namespaced_name = f"{component_type}.{component_name}"
            self._components.pop(namespaced_name, None)
            self._components_by_type[component_type].pop(component_name, None)
            self._components_classes.pop(namespaced_name, None)

            logger.info(f"组件 {component_name} ({component_type}) 已完全移除")
            return True

        except Exception as e:
            logger.error(f"移除组件 {component_name} ({component_type}) 时发生错误: {e}")
            return False

    def remove_plugin_registry(self, plugin_name: str) -> bool:
        """移除插件注册信息

        Args:
            plugin_name: 插件名称

        Returns:
            bool: 是否成功移除
        """
        if plugin_name not in self._plugins:
            logger.warning(f"插件 {plugin_name} 未注册，无法移除")
            return False
        del self._plugins[plugin_name]
        logger.info(f"插件 {plugin_name} 已移除")
        return True

    # === 组件全局启用/禁用方法 ===

    def enable_component(self, component_name: str, component_type: ComponentType) -> bool:
        """全局的启用某个组件
        Parameters:
            component_name: 组件名称
            component_type: 组件类型
        Returns:
            bool: 启用成功返回True，失败返回False
        """
        target_component_class = self.get_component_class(component_name, component_type)
        target_component_info = self.get_component_info(component_name, component_type)
        if not target_component_class or not target_component_info:
            logger.warning(f"组件 {component_name} 未注册，无法启用")
            return False
        target_component_info.enabled = True
        match component_type:
            case ComponentType.ACTION:
                assert isinstance(target_component_info, ActionInfo)
                self._default_actions[component_name] = target_component_info
            case ComponentType.COMMAND:
                assert isinstance(target_component_info, CommandInfo)
                pattern = target_component_info.command_pattern
                self._command_patterns[re.compile(pattern)] = component_name
            case ComponentType.TOOL:
                assert isinstance(target_component_info, ToolInfo)
                assert issubclass(target_component_class, BaseTool)
                self._llm_available_tools[component_name] = target_component_class
            case ComponentType.EVENT_HANDLER:
                assert isinstance(target_component_info, EventHandlerInfo)
                assert issubclass(target_component_class, BaseEventHandler)
                self._enabled_event_handlers[component_name] = target_component_class
                from .event_manager import event_manager  # 延迟导入防止循环导入问题

                event_manager.register_event_handler(component_name)

        namespaced_name = f"{component_type}.{component_name}"
        self._components[namespaced_name].enabled = True
        self._components_by_type[component_type][component_name].enabled = True
        logger.info(f"组件 {component_name} 已启用")
        return True

    async def disable_component(self, component_name: str, component_type: ComponentType) -> bool:
        """全局的禁用某个组件
        Parameters:
            component_name: 组件名称
            component_type: 组件类型
        Returns:
            bool: 禁用成功返回True，失败返回False
        """
        target_component_class = self.get_component_class(component_name, component_type)
        target_component_info = self.get_component_info(component_name, component_type)
        if not target_component_class or not target_component_info:
            logger.warning(f"组件 {component_name} 未注册，无法禁用")
            return False
        target_component_info.enabled = False
        try:
            match component_type:
                case ComponentType.ACTION:
                    self._default_actions.pop(component_name)
                case ComponentType.COMMAND:
                    self._command_patterns = {k: v for k, v in self._command_patterns.items() if v != component_name}
                case ComponentType.TOOL:
                    self._llm_available_tools.pop(component_name)
                case ComponentType.EVENT_HANDLER:
                    self._enabled_event_handlers.pop(component_name)
                    from .event_manager import event_manager  # 延迟导入防止循环导入问题

                    handler = event_manager.get_event_handler(component_name)
                    for event in handler.subscribed_events:
                        await event_manager.unsubscribe_handler_from_event(event, component_name)

            self._components[component_name].enabled = False
            self._components_by_type[component_type][component_name].enabled = False
            logger.info(f"组件 {component_name} 已禁用")
            return True
        except KeyError as e:
            logger.warning(f"禁用组件时未找到组件或已禁用: {component_name}, 发生错误: {e}")
            return False
        except Exception as e:
            logger.error(f"禁用组件 {component_name} 时发生错误: {e}")
            return False

    # === 组件查询方法 ===
    def get_component_info(
        self, component_name: str, component_type: Optional[ComponentType] = None
    ) -> Optional[ComponentInfo]:
        # sourcery skip: class-extract-method
        """获取组件信息，支持自动命名空间解析

        Args:
            component_name: 组件名称，可以是原始名称或命名空间化的名称
            component_type: 组件类型，如果提供则优先在该类型中查找

        Returns:
            Optional[ComponentInfo]: 组件信息或None
        """
        # 1. 如果已经是命名空间化的名称，直接查找
        if "." in component_name:
            return self._components.get(component_name)

        # 2. 如果指定了组件类型，构造命名空间化的名称查找
        if component_type:
            namespaced_name = f"{component_type}.{component_name}"
            return self._components.get(namespaced_name)

        # 3. 如果没有指定类型，尝试在所有命名空间中查找
        candidates = []
        for namespace_prefix in [types.value for types in ComponentType]:
            namespaced_name = f"{namespace_prefix}.{component_name}"
            if component_info := self._components.get(namespaced_name):
                candidates.append((namespace_prefix, namespaced_name, component_info))

        if len(candidates) == 1:
            # 只有一个匹配，直接返回
            return candidates[0][2]
        elif len(candidates) > 1:
            # 多个匹配，记录警告并返回第一个
            namespaces = [ns for ns, _, _ in candidates]
            logger.warning(
                f"组件名称 '{component_name}' 在多个命名空间中存在: {namespaces}，使用第一个匹配项: {candidates[0][1]}"
            )
            return candidates[0][2]

        # 4. 都没找到
        return None

    def get_component_class(
        self,
        component_name: str,
        component_type: Optional[ComponentType] = None,
    ) -> Optional[Union[Type[BaseCommand], Type[BaseAction], Type[BaseEventHandler], Type[BaseTool]]]:
        """获取组件类，支持自动命名空间解析

        Args:
            component_name: 组件名称，可以是原始名称或命名空间化的名称
            component_type: 组件类型，如果提供则优先在该类型中查找

        Returns:
            Optional[Union[BaseCommand, BaseAction]]: 组件类或None
        """
        # 1. 如果已经是命名空间化的名称，直接查找
        if "." in component_name:
            return self._components_classes.get(component_name)

        # 2. 如果指定了组件类型，构造命名空间化的名称查找
        if component_type:
            namespaced_name = f"{component_type.value}.{component_name}"
            return self._components_classes.get(namespaced_name)

        # 3. 如果没有指定类型，尝试在所有命名空间中查找
        candidates = []
        for namespace_prefix in [types.value for types in ComponentType]:
            namespaced_name = f"{namespace_prefix}.{component_name}"
            if component_class := self._components_classes.get(namespaced_name):
                candidates.append((namespace_prefix, namespaced_name, component_class))

        if len(candidates) == 1:
            # 只有一个匹配，直接返回
            _, full_name, cls = candidates[0]
            logger.debug(f"自动解析组件: '{component_name}' -> '{full_name}'")
            return cls
        elif len(candidates) > 1:
            # 多个匹配，记录警告并返回第一个
            namespaces = [ns for ns, _, _ in candidates]
            logger.warning(
                f"组件名称 '{component_name}' 在多个命名空间中存在: {namespaces}，使用第一个匹配项: {candidates[0][1]}"
            )
            return candidates[0][2]

        # 4. 都没找到
        return None

    def get_components_by_type(self, component_type: ComponentType) -> Dict[str, ComponentInfo]:
        """获取指定类型的所有组件"""
        return self._components_by_type.get(component_type, {}).copy()

    def get_enabled_components_by_type(self, component_type: ComponentType) -> Dict[str, ComponentInfo]:
        """获取指定类型的所有启用组件"""
        components = self.get_components_by_type(component_type)
        return {name: info for name, info in components.items() if info.enabled}

    # === Action特定查询方法 ===

    def get_action_registry(self) -> Dict[str, Type[BaseAction]]:
        """获取Action注册表"""
        return self._action_registry.copy()

    def get_registered_action_info(self, action_name: str) -> Optional[ActionInfo]:
        """获取Action信息"""
        info = self.get_component_info(action_name, ComponentType.ACTION)
        return info if isinstance(info, ActionInfo) else None

    def get_default_actions(self) -> Dict[str, ActionInfo]:
        """获取默认动作集"""
        return self._default_actions.copy()

    # === Command特定查询方法 ===

    def get_command_registry(self) -> Dict[str, Type[BaseCommand]]:
        """获取Command注册表"""
        return self._command_registry.copy()

    def get_registered_command_info(self, command_name: str) -> Optional[CommandInfo]:
        """获取Command信息"""
        info = self.get_component_info(command_name, ComponentType.COMMAND)
        return info if isinstance(info, CommandInfo) else None

    def get_command_patterns(self) -> Dict[Pattern, str]:
        """获取Command模式注册表"""
        return self._command_patterns.copy()

    def find_command_by_text(self, text: str) -> Optional[Tuple[Type[BaseCommand], dict, CommandInfo]]:
        # sourcery skip: use-named-expression, use-next
        """根据文本查找匹配的命令

        Args:
            text: 输入文本

        Returns:
            Tuple: (命令类, 匹配的命名组, 命令信息) 或 None
        """

        # 只查找传统的BaseCommand
        candidates = [pattern for pattern in self._command_patterns if pattern.match(text)]
        if candidates:
            if len(candidates) > 1:
                logger.warning(f"文本 '{text}' 匹配到多个命令模式: {candidates}，使用第一个匹配")
            command_name = self._command_patterns[candidates[0]]
            command_info: CommandInfo = self.get_registered_command_info(command_name)  # type: ignore
            return (
                self._command_registry[command_name],
                candidates[0].match(text).groupdict(),  # type: ignore
                command_info,
            )

        return None

    # === Tool 特定查询方法 ===
    def get_tool_registry(self) -> Dict[str, Type[BaseTool]]:
        """获取Tool注册表"""
        return self._tool_registry.copy()

    def get_llm_available_tools(self) -> Dict[str, Type[BaseTool]]:
        """获取LLM可用的Tool列表"""
        return self._llm_available_tools.copy()

    def get_registered_tool_info(self, tool_name: str) -> Optional[ToolInfo]:
        """获取Tool信息

        Args:
            tool_name: 工具名称

        Returns:
            ToolInfo: 工具信息对象，如果工具不存在则返回 None
        """
        info = self.get_component_info(tool_name, ComponentType.TOOL)
        return info if isinstance(info, ToolInfo) else None

    # === PlusCommand 特定查询方法 ===
    def get_plus_command_registry(self) -> Dict[str, Type[PlusCommand]]:
        """获取PlusCommand注册表"""
        if not hasattr(self, "_plus_command_registry"):
            pass
        return self._plus_command_registry.copy()

    def get_registered_plus_command_info(self, command_name: str) -> Optional[PlusCommandInfo]:
        """获取PlusCommand信息

        Args:
            command_name: 命令名称

        Returns:
            PlusCommandInfo: 命令信息对象，如果命令不存在则返回 None
        """
        info = self.get_component_info(command_name, ComponentType.PLUS_COMMAND)
        return info if isinstance(info, PlusCommandInfo) else None

    # === EventHandler 特定查询方法 ===

    def get_event_handler_registry(self) -> Dict[str, Type[BaseEventHandler]]:
        """获取事件处理器注册表"""
        return self._event_handler_registry.copy()

    def get_registered_event_handler_info(self, handler_name: str) -> Optional[EventHandlerInfo]:
        """获取事件处理器信息"""
        info = self.get_component_info(handler_name, ComponentType.EVENT_HANDLER)
        return info if isinstance(info, EventHandlerInfo) else None

    def get_enabled_event_handlers(self) -> Dict[str, Type[BaseEventHandler]]:
        """获取启用的事件处理器"""
        return self._enabled_event_handlers.copy()

    # === 插件查询方法 ===

    def get_plugin_info(self, plugin_name: str) -> Optional[PluginInfo]:
        """获取插件信息"""
        return self._plugins.get(plugin_name)

    def get_all_plugins(self) -> Dict[str, PluginInfo]:
        """获取所有插件"""
        return self._plugins.copy()

    # def get_enabled_plugins(self) -> Dict[str, PluginInfo]:
    #     """获取所有启用的插件"""
    #     return {name: info for name, info in self._plugins.items() if info.enabled}

    def get_plugin_components(self, plugin_name: str) -> List[ComponentInfo]:
        """获取插件的所有组件"""
        plugin_info = self.get_plugin_info(plugin_name)
        return plugin_info.components if plugin_info else []

    @staticmethod
    def get_plugin_config(plugin_name: str) -> dict:
        """获取插件配置

        Args:
            plugin_name: 插件名称

        Returns:
            dict: 插件配置字典，如果插件实例不存在或配置为空，返回空字典
        """
        # 从插件管理器获取插件实例的配置
        from src.plugin_system.core.plugin_manager import plugin_manager

        plugin_instance = plugin_manager.get_plugin_instance(plugin_name)
        if plugin_instance and plugin_instance.config:
            return plugin_instance.config
        
        # 如果插件实例不存在，尝试从配置文件读取
        try:
            import toml
            config_path = Path("config") / "plugins" / plugin_name / "config.toml"
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config_data = toml.load(f)
                    logger.debug(f"从配置文件读取插件 {plugin_name} 的配置")
                    return config_data
        except Exception as e:
            logger.debug(f"读取插件 {plugin_name} 配置文件失败: {e}")
        
        return {}

    def get_registry_stats(self) -> Dict[str, Any]:
        """获取注册中心统计信息"""
        action_components: int = 0
        command_components: int = 0
        tool_components: int = 0
        events_handlers: int = 0
        plus_command_components: int = 0
        for component in self._components.values():
            if component.component_type == ComponentType.ACTION:
                action_components += 1
            elif component.component_type == ComponentType.COMMAND:
                command_components += 1
            elif component.component_type == ComponentType.TOOL:
                tool_components += 1
            elif component.component_type == ComponentType.EVENT_HANDLER:
                events_handlers += 1
            elif component.component_type == ComponentType.PLUS_COMMAND:
                plus_command_components += 1
        return {
            "action_components": action_components,
            "command_components": command_components,
            "tool_components": tool_components,
            "event_handlers": events_handlers,
            "plus_command_components": plus_command_components,
            "total_components": len(self._components),
            "total_plugins": len(self._plugins),
            "components_by_type": {
                component_type.value: len(components) for component_type, components in self._components_by_type.items()
            },
            "enabled_components": len([c for c in self._components.values() if c.enabled]),
            "enabled_plugins": len([p for p in self._plugins.values() if p.enabled]),
        }

    # === 组件移除相关 ===

    async def unregister_plugin(self, plugin_name: str) -> bool:
        """卸载插件及其所有组件

        Args:
            plugin_name: 插件名称

        Returns:
            bool: 是否成功卸载
        """
        plugin_info = self.get_plugin_info(plugin_name)
        if not plugin_info:
            logger.warning(f"插件 {plugin_name} 未注册，无法卸载")
            return False

        logger.info(f"开始卸载插件: {plugin_name}")

        # 记录卸载失败的组件
        failed_components = []

        # 逐个移除插件的所有组件
        for component_info in plugin_info.components:
            try:
                success = await self.remove_component(
                    component_info.name,
                    component_info.component_type,
                    plugin_name,
                )
                if not success:
                    failed_components.append(f"{component_info.component_type}.{component_info.name}")
            except Exception as e:
                logger.error(f"移除组件 {component_info.name} 时发生异常: {e}")
                failed_components.append(f"{component_info.component_type}.{component_info.name}")

        # 移除插件注册信息
        plugin_removed = self.remove_plugin_registry(plugin_name)

        if failed_components:
            logger.warning(f"插件 {plugin_name} 部分组件卸载失败: {failed_components}")
            return False
        elif not plugin_removed:
            logger.error(f"插件 {plugin_name} 注册信息移除失败")
            return False
        else:
            logger.info(f"插件 {plugin_name} 卸载成功")
            return True


# 创建全局组件注册中心实例
component_registry = ComponentRegistry()
