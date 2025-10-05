from maim_message import Router, RouteConfig, TargetConfig
from src.common.logger import get_logger
import os
from .send_handler import send_handler
from src.plugin_system.apis import config_api

logger = get_logger("napcat_adapter")

router = None


def create_router(plugin_config: dict):
    """创建路由器实例"""
    global router
    platform_name = config_api.get_plugin_config(plugin_config, "maibot_server.platform_name", "qq")
    host = os.getenv("HOST","127.0.0.1")
    port = os.getenv("PORT","8000")
    logger.debug(f"初始化MaiBot连接，使用地址：{host}:{port}")
    route_config = RouteConfig(
        route_config={
            platform_name: TargetConfig(
                url=f"ws://{host}:{port}/ws",
                token=None,
            )
        }
    )
    router = Router(route_config)
    return router


async def mmc_start_com(plugin_config: dict = None):
    """启动MaiBot连接"""
    logger.debug("正在连接MaiBot")
    if plugin_config:
        create_router(plugin_config)

    if router:
        router.register_class_handler(send_handler.handle_message)
        await router.run()


async def mmc_stop_com():
    """停止MaiBot连接"""
    if router:
        await router.stop()
