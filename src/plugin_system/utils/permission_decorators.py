"""
权限装饰器

提供方便的权限检查装饰器，用于插件命令和其他需要权限验证的地方。
"""

from collections.abc import Callable
from functools import wraps
from inspect import iscoroutinefunction

from src.chat.message_receive.chat_stream import ChatStream
from src.plugin_system.apis.logging_api import get_logger
from src.plugin_system.apis.permission_api import permission_api
from src.plugin_system.apis.send_api import text_to_stream

logger = get_logger(__name__)


def require_permission(permission_node: str, deny_message: str | None = None):
    """
    权限检查装饰器

    用于装饰需要特定权限才能执行的函数。如果用户没有权限，会发送拒绝消息并阻止函数执行。

    Args:
        permission_node: 所需的权限节点名称
        deny_message: 权限不足时的提示消息，如果为None则使用默认消息

    Example:
        @require_permission("plugin.example.admin")
        async def admin_command(message: Message, chat_stream: ChatStream):
            # 只有拥有 plugin.example.admin 权限的用户才能执行
            pass
    """

    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # 尝试从参数中提取 ChatStream 对象
            chat_stream = None

            # 首先检查位置参数中的 ChatStream
            for arg in args:
                if isinstance(arg, ChatStream):
                    chat_stream = arg
                    break

            # 如果在位置参数中没找到，尝试从关键字参数中查找
            if chat_stream is None:
                chat_stream = kwargs.get("chat_stream")

            # 如果还没找到，检查是否是 PlusCommand 方法调用
            if chat_stream is None and args:
                # 检查第一个参数是否有 message.chat_stream 属性（PlusCommand 实例）
                instance = args[0]
                if hasattr(instance, "message") and hasattr(instance.message, "chat_stream"):
                    chat_stream = instance.message.chat_stream

            if chat_stream is None:
                logger.error(f"权限装饰器无法找到 ChatStream 对象，函数: {func.__name__}")
                return None

            # 检查权限
            has_permission = await permission_api.check_permission(
                chat_stream.platform, chat_stream.user_info.user_id, permission_node
            )

            if not has_permission:
                # 权限不足，发送拒绝消息
                message = deny_message or f"❌ 你没有执行此操作的权限\n需要权限: {permission_node}"
                await text_to_stream(message, chat_stream.stream_id)
                # 对于PlusCommand的execute方法，需要返回适当的元组
                if func.__name__ == "execute" and hasattr(args[0], "send_text"):
                    return False, "权限不足", True
                return None

            # 权限检查通过，执行原函数
            return await func(*args, **kwargs)

        if not iscoroutinefunction(func):
            logger.warning(f"函数 {func.__name__} 使用 require_permission 但非异步，已强制阻止执行")

            async def blocked(*_a, **_k):
                logger.error("同步函数不再支持权限装饰器，请改为 async def")
                return None

            return blocked
        return async_wrapper

    return decorator


def require_master(deny_message: str | None = None):
    """
    Master权限检查装饰器

    用于装饰只有Master用户才能执行的函数。

    Args:
        deny_message: 权限不足时的提示消息，如果为None则使用默认消息

    Example:
        @require_master()
        async def master_only_command(message: Message, chat_stream: ChatStream):
            # 只有Master用户才能执行
            pass
    """

    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # 尝试从参数中提取 ChatStream 对象
            chat_stream = None

            # 首先检查位置参数中的 ChatStream
            for arg in args:
                if isinstance(arg, ChatStream):
                    chat_stream = arg
                    break

            # 如果在位置参数中没找到，尝试从关键字参数中查找
            if chat_stream is None:
                chat_stream = kwargs.get("chat_stream")

            # 如果还没找到，检查是否是 PlusCommand 方法调用
            if chat_stream is None and args:
                # 检查第一个参数是否有 message.chat_stream 属性（PlusCommand 实例）
                instance = args[0]
                if hasattr(instance, "message") and hasattr(instance.message, "chat_stream"):
                    chat_stream = instance.message.chat_stream

            if chat_stream is None:
                logger.error(f"Master权限装饰器无法找到 ChatStream 对象，函数: {func.__name__}")
                return None

            # 检查是否为Master用户
            is_master = permission_api.is_master(chat_stream.platform, chat_stream.user_info.user_id)

            if not is_master:
                message = deny_message or "❌ 此操作仅限Master用户执行"
                await text_to_stream(message, chat_stream.stream_id)
                if func.__name__ == "execute" and hasattr(args[0], "send_text"):
                    return False, "需要Master权限", True
                return None

            # 权限检查通过，执行原函数
            return await func(*args, **kwargs)

        if not iscoroutinefunction(func):
            logger.warning(f"函数 {func.__name__} 使用 require_master 但非异步，已强制阻止执行")

            async def blocked(*_a, **_k):
                logger.error("同步函数不再支持 require_master，请改为 async def")
                return None

            return blocked
        return async_wrapper

    return decorator


class PermissionChecker:
    """
    权限检查工具类

    提供一些便捷的权限检查方法，用于在代码中进行权限验证。
    """

    @staticmethod
    def check_permission(chat_stream: ChatStream, permission_node: str) -> bool:
        raise RuntimeError(
            "PermissionChecker.check_permission 已移除同步支持，请直接 await permission_api.check_permission"
        )

    @staticmethod
    def is_master(chat_stream: ChatStream) -> bool:
        """
        检查用户是否为Master用户

        Args:
            chat_stream: 聊天流对象

        Returns:
            bool: 是否为Master用户
        """
        return permission_api.is_master(chat_stream.platform, chat_stream.user_info.user_id)

    @staticmethod
    async def ensure_permission(chat_stream: ChatStream, permission_node: str, deny_message: str | None = None) -> bool:
        """
        确保用户拥有指定权限，如果没有权限会发送消息并返回False

        Args:
            chat_stream: 聊天流对象
            permission_node: 权限节点名称
            deny_message: 权限不足时的提示消息

        Returns:
            bool: 是否拥有权限
        """
        has_permission = await permission_api.check_permission(
            chat_stream.platform, chat_stream.user_info.user_id, permission_node
        )
        if not has_permission:
            message = deny_message or f"❌ 你没有执行此操作的权限\n需要权限: {permission_node}"
            await text_to_stream(message, chat_stream.stream_id)
        return has_permission

    @staticmethod
    async def ensure_master(chat_stream: ChatStream, deny_message: str | None = None) -> bool:
        """
        确保用户为Master用户，如果不是会发送消息并返回False

        Args:
            chat_stream: 聊天流对象
            deny_message: 权限不足时的提示消息

        Returns:
            bool: 是否为Master用户
        """
        is_master = PermissionChecker.is_master(chat_stream)

        if not is_master:
            message = deny_message or "❌ 此操作仅限Master用户执行"
            await text_to_stream(message, chat_stream.stream_id)

        return is_master
