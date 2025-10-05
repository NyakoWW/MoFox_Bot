import asyncio
import importlib
import os
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any, Optional

from src.common.logger import get_logger
from src.plugin_system.base.component_types import ComponentType
from src.plugin_system.base.plugin_base import PluginBase
from src.plugin_system.base.plugin_metadata import PluginMetadata

from .component_registry import component_registry

logger = get_logger("plugin_manager")


class PluginManager:
    """
    插件管理器类

    负责加载，重载和卸载插件，同时管理插件的所有组件
    """

    def __init__(self):
        self.plugin_directories: list[str] = []  # 插件根目录列表
        self.plugin_classes: dict[str, type[PluginBase]] = {}  # 全局插件类注册表，插件名 -> 插件类
        self.plugin_paths: dict[str, str] = {}  # 记录插件名到目录路径的映射，插件名 -> 目录路径
        self.plugin_modules: dict[str, Any] = {}  # 记录插件名到模块的映射

        self.loaded_plugins: dict[str, PluginBase] = {}  # 已加载的插件类实例注册表，插件名 -> 插件类实例
        self.failed_plugins: dict[str, str] = {}  # 记录加载失败的插件文件及其错误信息，插件名 -> 错误信息

        # 确保插件目录存在
        self._ensure_plugin_directories()
        logger.info("插件管理器初始化完成")

    # === 插件目录管理 ===

    def add_plugin_directory(self, directory: str) -> bool:
        """添加插件目录"""
        if os.path.exists(directory):
            if directory not in self.plugin_directories:
                self.plugin_directories.append(directory)
                logger.debug(f"已添加插件目录: {directory}")
                return True
            else:
                logger.warning(f"插件不可重复加载: {directory}")
        else:
            logger.warning(f"插件目录不存在: {directory}")
        return False

    # === 插件加载管理 ===

    def load_all_plugins(self) -> tuple[int, int]:
        """加载所有插件

        Returns:
            tuple[int, int]: (插件数量, 组件数量)
        """
        logger.debug("开始加载所有插件...")

        # 第一阶段：加载所有插件模块（注册插件类）
        total_loaded_modules = 0
        total_failed_modules = 0

        for directory in self.plugin_directories:
            loaded, failed = self._load_plugin_modules_from_directory(directory)
            total_loaded_modules += loaded
            total_failed_modules += failed

        logger.debug(f"插件模块加载完成 - 成功: {total_loaded_modules}, 失败: {total_failed_modules}")

        total_registered = 0
        total_failed_registration = 0

        for plugin_name in self.plugin_classes.keys():
            load_status, count = self.load_registered_plugin_classes(plugin_name)
            if load_status:
                total_registered += 1
            else:
                total_failed_registration += count

        self._show_stats(total_registered, total_failed_registration)

        return total_registered, total_failed_registration

    def load_registered_plugin_classes(self, plugin_name: str) -> tuple[bool, int]:
        # sourcery skip: extract-duplicate-method, extract-method
        """
        加载已经注册的插件类
        """
        plugin_class = self.plugin_classes.get(plugin_name)
        if not plugin_class:
            logger.error(f"插件 {plugin_name} 的插件类未注册或不存在")
            return False, 1
        try:
            # 使用记录的插件目录路径
            plugin_dir = self.plugin_paths.get(plugin_name)

            # 如果没有记录，直接返回失败
            if not plugin_dir:
                return False, 1

            module = self.plugin_modules.get(plugin_name)

            if not module or not hasattr(module, "__plugin_meta__"):
                self.failed_plugins[plugin_name] = "插件模块中缺少 __plugin_meta__"
                logger.error(f"❌ 插件加载失败: {plugin_name} - 缺少 __plugin_meta__")
                return False, 1

            metadata: PluginMetadata = getattr(module, "__plugin_meta__")

            plugin_instance = plugin_class(plugin_dir=plugin_dir, metadata=metadata)
            if not plugin_instance:
                logger.error(f"插件 {plugin_name} 实例化失败")
                return False, 1

            # 检查插件是否启用
            if not plugin_instance.enable_plugin:
                logger.info(f"插件 {plugin_name} 已禁用，跳过加载")
                return False, 0

            if plugin_instance.register_plugin():
                self.loaded_plugins[plugin_name] = plugin_instance
                self._show_plugin_components(plugin_name)

                # 检查并调用 on_plugin_loaded 钩子（如果存在）
                if hasattr(plugin_instance, "on_plugin_loaded") and callable(plugin_instance.on_plugin_loaded):
                    logger.debug(f"为插件 '{plugin_name}' 调用 on_plugin_loaded 钩子")
                    try:
                        # 使用 asyncio.create_task 确保它不会阻塞加载流程
                        asyncio.create_task(plugin_instance.on_plugin_loaded())
                    except Exception as e:
                        logger.error(f"调用插件 '{plugin_name}' 的 on_plugin_loaded 钩子时出错: {e}")

                return True, 1
            else:
                self.failed_plugins[plugin_name] = "插件注册失败"
                logger.error(f"❌ 插件注册失败: {plugin_name}")
                return False, 1

        except Exception as e:
            # 其他错误
            error_msg = f"未知错误: {e!s}"
            self.failed_plugins[plugin_name] = error_msg
            logger.error(f"❌ 插件加载失败: {plugin_name} - {error_msg}")
            logger.debug("详细错误信息: ", exc_info=True)
            return False, 1

    async def remove_registered_plugin(self, plugin_name: str) -> bool:
        """
        禁用插件模块
        """
        if not plugin_name:
            raise ValueError("插件名称不能为空")
        if plugin_name not in self.loaded_plugins:
            logger.warning(f"插件 {plugin_name} 未加载")
            return False
        plugin_instance = self.loaded_plugins[plugin_name]
        plugin_info = plugin_instance.plugin_info
        success = True
        for component in plugin_info.components:
            success &= await component_registry.remove_component(component.name, component.component_type, plugin_name)
        success &= component_registry.remove_plugin_registry(plugin_name)
        del self.loaded_plugins[plugin_name]
        return success

    async def reload_registered_plugin(self, plugin_name: str) -> bool:
        """
        重载插件模块
        """
        if not await self.remove_registered_plugin(plugin_name):
            return False
        if not self.load_registered_plugin_classes(plugin_name)[0]:
            return False
        logger.debug(f"插件 {plugin_name} 重载成功")
        return True

    def rescan_plugin_directory(self) -> tuple[int, int]:
        """
        重新扫描插件根目录
        """
        total_success = 0
        total_fail = 0
        for directory in self.plugin_directories:
            if os.path.exists(directory):
                logger.debug(f"重新扫描插件根目录: {directory}")
                success, fail = self._load_plugin_modules_from_directory(directory)
                total_success += success
                total_fail += fail
            else:
                logger.warning(f"插件根目录不存在: {directory}")
        return total_success, total_fail

    def get_plugin_instance(self, plugin_name: str) -> Optional["PluginBase"]:
        """获取插件实例

        Args:
            plugin_name: 插件名称

        Returns:
            Optional[BasePlugin]: 插件实例或None
        """
        return self.loaded_plugins.get(plugin_name)

    # === 查询方法 ===
    def list_loaded_plugins(self) -> list[str]:
        """
        列出所有当前加载的插件。

        Returns:
            list: 当前加载的插件名称列表。
        """
        return list(self.loaded_plugins.keys())

    def list_registered_plugins(self) -> list[str]:
        """
        列出所有已注册的插件类。

        Returns:
            list: 已注册的插件类名称列表。
        """
        return list(self.plugin_classes.keys())

    def get_plugin_path(self, plugin_name: str) -> str | None:
        """
        获取指定插件的路径。

        Args:
            plugin_name: 插件名称

        Returns:
            Optional[str]: 插件目录的绝对路径，如果插件不存在则返回None。
        """
        return self.plugin_paths.get(plugin_name)

    # === 私有方法 ===
    # == 目录管理 ==
    def _ensure_plugin_directories(self) -> None:
        """确保所有插件根目录存在，如果不存在则创建"""
        default_directories = ["src/plugins/built_in", "plugins"]

        for directory in default_directories:
            if not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)
                logger.info(f"创建插件根目录: {directory}")
            if directory not in self.plugin_directories:
                self.plugin_directories.append(directory)
                logger.debug(f"已添加插件根目录: {directory}")
            else:
                logger.warning(f"根目录不可重复加载: {directory}")

    # == 插件加载 ==

    def _load_plugin_modules_from_directory(self, directory: str) -> tuple[int, int]:
        """从指定目录加载插件模块"""
        loaded_count = 0
        failed_count = 0

        if not os.path.exists(directory):
            logger.warning(f"插件根目录不存在: {directory}")
            return 0, 1

        logger.debug(f"正在扫描插件根目录: {directory}")

        # 遍历目录中的所有包
        for item in os.listdir(directory):
            item_path = os.path.join(directory, item)

            if os.path.isdir(item_path) and not item.startswith(".") and not item.startswith("__"):
                plugin_file = os.path.join(item_path, "plugin.py")
                if os.path.exists(plugin_file):
                    module = self._load_plugin_module_file(plugin_file)
                    if module:
                        # 动态查找插件类并获取真实的 plugin_name
                        for attr_name in dir(module):
                            attr = getattr(module, attr_name)
                            if isinstance(attr, type) and issubclass(attr, PluginBase) and attr is not PluginBase:
                                plugin_name = getattr(attr, "plugin_name", None)
                                if plugin_name:
                                    self.plugin_modules[plugin_name] = module
                                    break
                        loaded_count += 1
                    else:
                        failed_count += 1

        return loaded_count, failed_count

    def _load_plugin_module_file(self, plugin_file: str) -> Any | None:
        # sourcery skip: extract-method
        """加载单个插件模块文件

        Args:
            plugin_file: 插件文件路径
        """
        # 生成模块名和插件信息
        plugin_path = Path(plugin_file)
        plugin_dir = plugin_path.parent  # 插件目录
        plugin_name = plugin_dir.name  # 插件名称
        module_name = ".".join(plugin_path.parent.parts)

        try:
            # 首先加载 __init__.py 来获取元数据
            init_file = os.path.join(plugin_dir, "__init__.py")
            if os.path.exists(init_file):
                init_spec = spec_from_file_location(f"{module_name}.__init__", init_file)
                if init_spec and init_spec.loader:
                    init_module = module_from_spec(init_spec)
                    init_spec.loader.exec_module(init_module)

            # 然后加载 plugin.py
            spec = spec_from_file_location(module_name, plugin_file)
            if spec is None or spec.loader is None:
                logger.error(f"无法创建模块规范: {plugin_file}")
                return None

            module = module_from_spec(spec)
            module.__package__ = module_name
            spec.loader.exec_module(module)

            # 将 __plugin_meta__ 从 init_module 附加到主模块
            if init_module and hasattr(init_module, "__plugin_meta__"):
                setattr(module, "__plugin_meta__", getattr(init_module, "__plugin_meta__"))

            logger.debug(f"插件模块加载成功: {plugin_file} -> {plugin_name} ({plugin_dir})")
            return module

        except Exception as e:
            error_msg = f"加载插件模块 {plugin_file} 失败: {e}"
            logger.error(error_msg)
            self.failed_plugins[plugin_name if "plugin_name" in locals() else module_name] = error_msg
            return None

    # == 显示统计与插件信息 ==

    def _show_stats(self, total_registered: int, total_failed_registration: int):
        # sourcery skip: low-code-quality
        # 获取组件统计信息
        stats = component_registry.get_registry_stats()
        action_count = stats.get("action_components", 0)
        command_count = stats.get("command_components", 0)
        tool_count = stats.get("tool_components", 0)
        event_handler_count = stats.get("event_handlers", 0)
        plus_command_count = stats.get("plus_command_components", 0)
        chatter_count = stats.get("chatter_components", 0)
        total_components = stats.get("total_components", 0)

        # 📋 显示插件加载总览
        if total_registered > 0:
            logger.info("🎉 插件系统加载完成!")
            logger.info(
                f"📊 总览: {total_registered}个插件, {total_components}个组件 (Action: {action_count}, Command: {command_count}, Tool: {tool_count}, PlusCommand: {plus_command_count}, EventHandler: {event_handler_count}, Chatter: {chatter_count})"
            )

            # 显示详细的插件列表
            logger.info("📋 已加载插件详情:")
            for plugin_name in self.loaded_plugins.keys():
                if plugin_info := component_registry.get_plugin_info(plugin_name):
                    # 插件基本信息
                    version_info = f"v{plugin_info.version}" if plugin_info.version else ""
                    author_info = f"by {plugin_info.author}" if plugin_info.author else "unknown"
                    license_info = f"[{plugin_info.license}]" if plugin_info.license else ""
                    info_parts = [part for part in [version_info, author_info, license_info] if part]
                    extra_info = f" ({', '.join(info_parts)})" if info_parts else ""

                    logger.info(f"  📦 {plugin_info.display_name}{extra_info}")

                    # 组件列表
                    if plugin_info.components:
                        action_components = [
                            c for c in plugin_info.components if c.component_type == ComponentType.ACTION
                        ]
                        command_components = [
                            c for c in plugin_info.components if c.component_type == ComponentType.COMMAND
                        ]
                        tool_components = [c for c in plugin_info.components if c.component_type == ComponentType.TOOL]
                        event_handler_components = [
                            c for c in plugin_info.components if c.component_type == ComponentType.EVENT_HANDLER
                        ]
                        plus_command_components = [
                            c for c in plugin_info.components if c.component_type == ComponentType.PLUS_COMMAND
                        ]

                        if action_components:
                            action_names = [c.name for c in action_components]
                            logger.info(f"    🎯 Action组件: {', '.join(action_names)}")

                        if command_components:
                            command_names = [c.name for c in command_components]
                            logger.info(f"    ⚡ Command组件: {', '.join(command_names)}")
                        if tool_components:
                            tool_names = [c.name for c in tool_components]
                            logger.info(f"    🛠️ Tool组件: {', '.join(tool_names)}")
                        if plus_command_components:
                            plus_command_names = [c.name for c in plus_command_components]
                            logger.info(f"    ⚡ PlusCommand组件: {', '.join(plus_command_names)}")
                        chatter_components = [
                            c for c in plugin_info.components if c.component_type == ComponentType.CHATTER
                        ]
                        if chatter_components:
                            chatter_names = [c.name for c in chatter_components]
                            logger.info(f"    🗣️ Chatter组件: {', '.join(chatter_names)}")
                        if event_handler_components:
                            event_handler_names = [c.name for c in event_handler_components]
                            logger.info(f"    📢 EventHandler组件: {', '.join(event_handler_names)}")

                    # 依赖信息
                    if plugin_info.dependencies:
                        logger.info(f"    🔗 依赖: {', '.join(plugin_info.dependencies)}")

                    # 配置文件信息
                    if plugin_info.config_file:
                        config_status = "✅" if self.plugin_paths.get(plugin_name) else "❌"
                        logger.info(f"    ⚙️ 配置: {plugin_info.config_file} {config_status}")

            root_path = Path(__file__)

            # 查找项目根目录
            while not (root_path / "pyproject.toml").exists() and root_path.parent != root_path:
                root_path = root_path.parent

            # 显示目录统计
            logger.info("📂 加载目录统计:")
            for directory in self.plugin_directories:
                if os.path.exists(directory):
                    plugins_in_dir = []
                    for plugin_name in self.loaded_plugins.keys():
                        plugin_path = self.plugin_paths.get(plugin_name, "")
                        if (
                            Path(plugin_path)
                            .resolve()
                            .is_relative_to(Path(os.path.join(str(root_path), directory)).resolve())
                        ):
                            plugins_in_dir.append(plugin_name)

                    if plugins_in_dir:
                        logger.info(f" 📁 {directory}: {len(plugins_in_dir)}个插件 ({', '.join(plugins_in_dir)})")
                    else:
                        logger.info(f" 📁 {directory}: 0个插件")

            # 失败信息
            if total_failed_registration > 0:
                logger.info(f"⚠️  失败统计: {total_failed_registration}个插件加载失败")
                for failed_plugin, error in self.failed_plugins.items():
                    logger.info(f"  ❌ {failed_plugin}: {error}")
        else:
            logger.warning("😕 没有成功加载任何插件")

    @staticmethod
    def _show_plugin_components(plugin_name: str) -> None:
        if plugin_info := component_registry.get_plugin_info(plugin_name):
            component_types = {}
            for comp in plugin_info.components:
                comp_type = comp.component_type.name
                component_types[comp_type] = component_types.get(comp_type, 0) + 1

            components_str = ", ".join([f"{count}个{ctype}" for ctype, count in component_types.items()])

            # 显示manifest信息
            manifest_info = ""
            if plugin_info.license:
                manifest_info += f" [{plugin_info.license}]"
            if plugin_info.keywords:
                manifest_info += f" 关键词: {', '.join(plugin_info.keywords[:3])}"  # 只显示前3个关键词
                if len(plugin_info.keywords) > 3:
                    manifest_info += "..."

            logger.info(
                f"✅ 插件加载成功: {plugin_name} v{plugin_info.version} ({components_str}){manifest_info} - {plugin_info.description}"
            )
        else:
            logger.info(f"✅ 插件加载成功: {plugin_name}")

    # === 插件卸载和重载管理 ===

    def unload_plugin(self, plugin_name: str) -> bool:
        """卸载指定插件

        Args:
            plugin_name: 插件名称

        Returns:
            bool: 卸载是否成功
        """
        if plugin_name not in self.loaded_plugins:
            logger.warning(f"插件 {plugin_name} 未加载，无需卸载")
            return False

        try:
            # 获取插件实例
            plugin_instance = self.loaded_plugins[plugin_name]

            # 调用插件的清理方法（如果有的话）
            if hasattr(plugin_instance, "on_unload"):
                plugin_instance.on_unload()

            # 从组件注册表中移除插件的所有组件
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    fut = asyncio.run_coroutine_threadsafe(component_registry.unregister_plugin(plugin_name), loop)
                    fut.result(timeout=5)
                else:
                    asyncio.run(component_registry.unregister_plugin(plugin_name))
            except Exception:
                # 最后兜底：直接同步调用（如果 unregister_plugin 为非协程）或忽略错误
                try:
                    # 如果 unregister_plugin 是普通函数
                    component_registry.unregister_plugin(plugin_name)
                except Exception as e:
                    logger.debug(f"卸载插件时调用 component_registry.unregister_plugin 失败: {e}")

            # 从已加载插件中移除
            del self.loaded_plugins[plugin_name]

            # 从插件类注册表中移除
            if plugin_name in self.plugin_classes:
                del self.plugin_classes[plugin_name]

            # 从失败列表中移除（如果存在）
            if plugin_name in self.failed_plugins:
                del self.failed_plugins[plugin_name]

            logger.info(f"✅ 插件卸载成功: {plugin_name}")
            return True

        except Exception as e:
            logger.error(f"❌ 插件卸载失败: {plugin_name} - {e!s}", exc_info=True)
            return False

    def reload_plugin(self, plugin_name: str) -> bool:
        """重载指定插件

        Args:
            plugin_name: 插件名称

        Returns:
            bool: 重载是否成功
        """
        try:
            logger.info(f"🔄 开始重载插件: {plugin_name}")

            # 卸载插件
            if plugin_name in self.loaded_plugins:
                if not self.unload_plugin(plugin_name):
                    logger.warning(f"⚠️ 插件卸载失败，继续重载: {plugin_name}")

            # 重新扫描插件目录
            self.rescan_plugin_directory()

            # 重新加载插件实例
            if plugin_name in self.plugin_classes:
                success, _ = self.load_registered_plugin_classes(plugin_name)
                if success:
                    logger.info(f"✅ 插件重载成功: {plugin_name}")
                    return True
                else:
                    logger.error(f"❌ 插件重载失败: {plugin_name} - 实例化失败")
                    return False
            else:
                logger.error(f"❌ 插件重载失败: {plugin_name} - 插件类未找到")
                return False

        except Exception as e:
            logger.error(f"❌ 插件重载失败: {plugin_name} - {e!s}", exc_info=True)
            return False

    def force_reload_plugin(self, plugin_name: str) -> bool:
        """强制重载插件（使用简化的方法）

        Args:
            plugin_name: 插件名称

        Returns:
            bool: 重载是否成功
        """
        return self.reload_plugin(plugin_name)

    @staticmethod
    def clear_all_plugin_caches():
        """清理所有插件相关的模块缓存（简化版）"""
        try:
            logger.info("🧹 清理模块缓存...")
            # 清理importlib缓存
            importlib.invalidate_caches()
            logger.info("🧹 模块缓存清理完成")
        except Exception as e:
            logger.error(f"❌ 清理模块缓存时发生错误: {e}", exc_info=True)


# 全局插件管理器实例
plugin_manager = PluginManager()
