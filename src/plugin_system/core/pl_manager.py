from pathlib import Path

from src.common.logger import get_logger
from src.plugin_system.base.plugin_base import PluginBase

logger = get_logger("plugin_manager")


class PluginManager:
    """
    插件管理器类

    负责加载，重载和卸载插件，同时管理插件的所有组件
    """

    plugin_classes: dict[str, type[PluginBase]]
    plugin_directories: list[str]
    plugin_paths: dict[str, str]
    loaded_plugins: dict[str, PluginBase]
    failed_plugins: dict[str, str]
    _instance = None

    def __init__(self):
        # 确保插件目录存在
        self._ensure_plugin_directories()
        logger.info("插件管理器初始化完成")

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        self = cls._instance
        self.plugin_directories = []  # 插件根目录列表
        self.plugin_classes = {}  # 全局插件类注册表，插件名 -> 插件类
        self.plugin_paths = {}  # 记录插件名到目录路径的映射，插件名 -> 目录路径
        self.loaded_plugins = {}  # 已加载的插件类实例注册表，插件名 -> 插件类实例
        self.failed_plugins = {}  # 记录加载失败的插件文件及其错误信息，插件名 -> 错误信息
        return cls._instance

    # === 插件目录管理 ===
    def add_plugin_directory(self, directory: str) -> bool:
        """添加插件目录"""
        if Path(directory).exists():
            if directory not in self.plugin_directories:
                self.plugin_directories.append(directory)
                logger.debug(f"已添加插件目录: {directory}")
                return True
            else:
                logger.warning(f"插件目录: `{directory}` 已存在")
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
