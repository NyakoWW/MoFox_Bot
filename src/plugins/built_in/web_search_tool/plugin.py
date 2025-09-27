"""
Web Search Tool Plugin

一个功能强大的网络搜索和URL解析插件，支持多种搜索引擎和解析策略。
"""

from typing import List, Tuple, Type

from src.plugin_system import BasePlugin, register_plugin, ComponentInfo, ConfigField, PythonDependency
from src.plugin_system.apis import config_api
from src.common.logger import get_logger

from .tools.web_search import WebSurfingTool
from .tools.url_parser import URLParserTool

logger = get_logger("web_search_plugin")


@register_plugin
class WEBSEARCHPLUGIN(BasePlugin):
    """
    网络搜索工具插件

    提供网络搜索和URL解析功能，支持多种搜索引擎：
    - Exa (需要API密钥)
    - Tavily (需要API密钥)
    - DuckDuckGo (免费)
    - Bing (免费)
    """

    # 插件基本信息
    plugin_name: str = "web_search_tool"  # 内部标识符
    enable_plugin: bool = True
    dependencies: List[str] = []  # 插件依赖列表

    def __init__(self, *args, **kwargs):
        """初始化插件，立即加载所有搜索引擎"""
        super().__init__(*args, **kwargs)

        # 立即初始化所有搜索引擎，触发API密钥管理器的日志输出
        logger.info("🚀 正在初始化所有搜索引擎...")
        try:
            from .engines.exa_engine import ExaSearchEngine
            from .engines.tavily_engine import TavilySearchEngine
            from .engines.ddg_engine import DDGSearchEngine
            from .engines.bing_engine import BingSearchEngine

            # 实例化所有搜索引擎，这会触发API密钥管理器的初始化
            exa_engine = ExaSearchEngine()
            tavily_engine = TavilySearchEngine()
            ddg_engine = DDGSearchEngine()
            bing_engine = BingSearchEngine()

            # 报告每个引擎的状态
            engines_status = {
                "Exa": exa_engine.is_available(),
                "Tavily": tavily_engine.is_available(),
                "DuckDuckGo": ddg_engine.is_available(),
                "Bing": bing_engine.is_available(),
            }

            available_engines = [name for name, available in engines_status.items() if available]
            unavailable_engines = [name for name, available in engines_status.items() if not available]

            if available_engines:
                logger.info(f"✅ 可用搜索引擎: {', '.join(available_engines)}")
            if unavailable_engines:
                logger.info(f"❌ 不可用搜索引擎: {', '.join(unavailable_engines)}")

        except Exception as e:
            logger.error(f"❌ 搜索引擎初始化失败: {e}", exc_info=True)

    # Python包依赖列表
    python_dependencies: List[PythonDependency] = [
        PythonDependency(package_name="asyncddgs", description="异步DuckDuckGo搜索库", optional=False),
        PythonDependency(
            package_name="exa_py",
            description="Exa搜索API客户端库",
            optional=True,  # 如果没有API密钥，这个是可选的
        ),
        PythonDependency(
            package_name="tavily",
            install_name="tavily-python",  # 安装时使用这个名称
            description="Tavily搜索API客户端库",
            optional=True,  # 如果没有API密钥，这个是可选的
        ),
        PythonDependency(
            package_name="httpx",
            version=">=0.20.0",
            install_name="httpx[socks]",  # 安装时使用这个名称（包含可选依赖）
            description="支持SOCKS代理的HTTP客户端库",
            optional=False,
        ),
    ]
    config_file_name: str = "config.toml"  # 配置文件名

    # 配置节描述
    config_section_descriptions = {"plugin": "插件基本信息", "proxy": "链接本地解析代理配置"}

    # 配置Schema定义
    # 注意：EXA配置和组件设置已迁移到主配置文件(bot_config.toml)的[exa]和[web_search]部分
    config_schema: dict = {
        "plugin": {
            "name": ConfigField(type=str, default="WEB_SEARCH_PLUGIN", description="插件名称"),
            "version": ConfigField(type=str, default="1.0.0", description="插件版本"),
            "enabled": ConfigField(type=bool, default=False, description="是否启用插件"),
        },
        "proxy": {
            "http_proxy": ConfigField(
                type=str, default=None, description="HTTP代理地址，格式如: http://proxy.example.com:8080"
            ),
            "https_proxy": ConfigField(
                type=str, default=None, description="HTTPS代理地址，格式如: http://proxy.example.com:8080"
            ),
            "socks5_proxy": ConfigField(
                type=str, default=None, description="SOCKS5代理地址，格式如: socks5://proxy.example.com:1080"
            ),
            "enable_proxy": ConfigField(type=bool, default=False, description="是否启用代理"),
        },
    }

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        """
        获取插件组件列表

        Returns:
                组件信息和类型的元组列表
        """
        enable_tool = []

        # 从主配置文件读取组件启用配置
        if config_api.get_global_config("web_search.enable_web_search_tool", True):
            enable_tool.append((WebSurfingTool.get_tool_info(), WebSurfingTool))

        if config_api.get_global_config("web_search.enable_url_tool", True):
            enable_tool.append((URLParserTool.get_tool_info(), URLParserTool))

        return enable_tool
