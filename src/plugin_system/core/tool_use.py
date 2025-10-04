import inspect
import time
from typing import Any

from src.chat.message_receive.chat_stream import get_chat_manager
from src.chat.utils.prompt import Prompt, global_prompt_manager
from src.common.cache_manager import tool_cache
from src.common.logger import get_logger
from src.config.config import global_config, model_config
from src.llm_models.payload_content import ToolCall
from src.llm_models.utils_model import LLMRequest
from src.plugin_system.apis.tool_api import get_llm_available_tool_definitions, get_tool_instance
from src.plugin_system.base.base_tool import BaseTool
from src.plugin_system.core.global_announcement_manager import global_announcement_manager

logger = get_logger("tool_use")


def init_tool_executor_prompt():
    """初始化工具执行器的提示词"""
    tool_executor_prompt = """
你是一个专门执行工具的助手。你的名字是{bot_name}。现在是{time_now}。
群里正在进行的聊天内容：
{chat_history}

现在，{sender}发送了内容:{target_message},你想要回复ta。
请仔细分析聊天内容，考虑以下几点：
1. 内容中是否包含需要查询信息的问题
2. 是否有明确的工具使用指令

If you need to use a tool, please directly call the corresponding tool function. If you do not need to use any tool, simply output "No tool needed".
"""
    Prompt(tool_executor_prompt, "tool_executor_prompt")


# 初始化提示词
init_tool_executor_prompt()


class ToolExecutor:
    """独立的工具执行器组件

    可以直接输入聊天消息内容，自动判断并执行相应的工具，返回结构化的工具执行结果。
    """

    def __init__(self, chat_id: str):
        """初始化工具执行器

        Args:
            executor_id: 执行器标识符，用于日志记录
            chat_id: 聊天标识符，用于日志记录
        """
        self.chat_id = chat_id
        # chat_stream 和 log_prefix 将在异步方法中初始化
        self.chat_stream = None  # type: ignore
        self.log_prefix = f"[{chat_id}]"

        self.llm_model = LLMRequest(model_set=model_config.model_task_config.tool_use, request_type="tool_executor")

        # 二步工具调用状态管理
        self._pending_step_two_tools: dict[str, dict[str, Any]] = {}
        """待处理的第二步工具调用，格式为 {tool_name: step_two_definition}"""
        self._log_prefix_initialized = False

        # logger.info(f"{self.log_prefix}工具执行器初始化完成")  # 移到异步初始化中

    async def _initialize_log_prefix(self):
        """异步初始化log_prefix和chat_stream"""
        if not self._log_prefix_initialized:
            from src.chat.message_receive.chat_stream import get_chat_manager
            self.chat_stream = await get_chat_manager().get_stream(self.chat_id)
            stream_name = await get_chat_manager().get_stream_name(self.chat_id)
            self.log_prefix = f"[{stream_name or self.chat_id}]"
            self._log_prefix_initialized = True
            logger.info(f"{self.log_prefix}工具执行器初始化完成")

    async def execute_from_chat_message(
        self, target_message: str, chat_history: str, sender: str, return_details: bool = False
    ) -> tuple[list[dict[str, Any]], list[str], str]:
        """从聊天消息执行工具

        Args:
            target_message: 目标消息内容
            chat_history: 聊天历史
            sender: 发送者
            return_details: 是否返回详细信息(使用的工具列表和提示词)

        Returns:
            如果return_details为False: Tuple[List[Dict], List[str], str] - (工具执行结果列表, 空, 空)
            如果return_details为True: Tuple[List[Dict], List[str], str] - (结果列表, 使用的工具, 提示词)
        """
        # 初始化log_prefix
        await self._initialize_log_prefix()

        # 获取可用工具
        tools = self._get_tool_definitions()

        # 获取当前时间
        time_now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

        bot_name = global_config.bot.nickname

        # 构建工具调用提示词
        prompt = await global_prompt_manager.format_prompt(
            "tool_executor_prompt",
            target_message=target_message,
            chat_history=chat_history,
            sender=sender,
            bot_name=bot_name,
            time_now=time_now,
        )

        logger.debug(f"{self.log_prefix}开始LLM工具调用分析")

        # 调用LLM进行工具决策
        response, (reasoning_content, model_name, tool_calls) = await self.llm_model.generate_response_async(
            prompt=prompt, tools=tools, raise_when_empty=False
        )

        # 执行工具调用
        tool_results, used_tools = await self.execute_tool_calls(tool_calls)

        if used_tools:
            logger.info(f"{self.log_prefix}工具执行完成，共执行{len(used_tools)}个工具: {used_tools}")

        if return_details:
            return tool_results, used_tools, prompt
        else:
            return tool_results, [], ""

    def _get_tool_definitions(self) -> list[dict[str, Any]]:
        all_tools = get_llm_available_tool_definitions()
        user_disabled_tools = global_announcement_manager.get_disabled_chat_tools(self.chat_id)

        # 获取基础工具定义（包括二步工具的第一步）
        tool_definitions = [definition for name, definition in all_tools if name not in user_disabled_tools]

        # 检查是否有待处理的二步工具第二步调用
        pending_step_two = getattr(self, "_pending_step_two_tools", {})
        if pending_step_two:
            # 添加第二步工具定义
            for tool_name, step_two_def in pending_step_two.items():
                tool_definitions.append(step_two_def)

        return tool_definitions

    async def execute_tool_calls(self, tool_calls: list[ToolCall] | None) -> tuple[list[dict[str, Any]], list[str]]:
        """执行工具调用

        Args:
            tool_calls: LLM返回的工具调用列表

        Returns:
            Tuple[List[Dict], List[str]]: (工具执行结果列表, 使用的工具名称列表)
        """
        tool_results: list[dict[str, Any]] = []
        used_tools = []

        if not tool_calls:
            logger.debug(f"{self.log_prefix}无需执行工具")
            return [], []

        # 提取tool_calls中的函数名称
        func_names = []
        for call in tool_calls:
            try:
                if hasattr(call, "func_name"):
                    func_names.append(call.func_name)
            except Exception as e:
                logger.error(f"{self.log_prefix}获取工具名称失败: {e}")
                continue

        if func_names:
            logger.info(f"{self.log_prefix}开始执行工具调用: {func_names}")
        else:
            logger.warning(f"{self.log_prefix}未找到有效的工具调用")

        # 执行每个工具调用
        for tool_call in tool_calls:
            try:
                tool_name = tool_call.func_name
                logger.debug(f"{self.log_prefix}执行工具: {tool_name}")

                # 执行工具
                result = await self.execute_tool_call(tool_call)

                if result:
                    tool_info = {
                        "type": result.get("type", "unknown_type"),
                        "id": result.get("id", f"tool_exec_{time.time()}"),
                        "content": result.get("content", ""),
                        "tool_name": tool_name,
                        "timestamp": time.time(),
                    }
                    content = tool_info["content"]
                    if not isinstance(content, (str, list, tuple)):
                        tool_info["content"] = str(content)

                    tool_results.append(tool_info)
                    used_tools.append(tool_name)
                    logger.info(f"{self.log_prefix}工具{tool_name}执行成功，类型: {tool_info['type']}")
                    preview = content[:200]
                    logger.debug(f"{self.log_prefix}工具{tool_name}结果内容: {preview}...")
            except Exception as e:
                logger.error(f"{self.log_prefix}工具{tool_name}执行失败: {e}")
                # 添加错误信息到结果中
                error_info = {
                    "type": "tool_error",
                    "id": f"tool_error_{time.time()}",
                    "content": f"工具{tool_name}执行失败: {e!s}",
                    "tool_name": tool_name,
                    "timestamp": time.time(),
                }
                tool_results.append(error_info)

        return tool_results, used_tools

    async def execute_tool_call(
        self, tool_call: ToolCall, tool_instance: BaseTool | None = None
    ) -> dict[str, Any] | None:
        """执行单个工具调用，并处理缓存"""

        function_args = tool_call.args or {}
        tool_instance = tool_instance or get_tool_instance(tool_call.func_name)

        # 如果工具不存在或未启用缓存，则直接执行
        if not tool_instance or not tool_instance.enable_cache:
            return await self._original_execute_tool_call(tool_call, tool_instance)

        # --- 缓存逻辑开始 ---
        try:
            tool_file_path = inspect.getfile(tool_instance.__class__)
            semantic_query = None
            if tool_instance.semantic_cache_query_key:
                semantic_query = function_args.get(tool_instance.semantic_cache_query_key)

            cached_result = await tool_cache.get(
                tool_name=tool_call.func_name,
                function_args=function_args,
                tool_file_path=tool_file_path,
                semantic_query=semantic_query,
            )
            if cached_result:
                logger.info(f"{self.log_prefix}使用缓存结果，跳过工具 {tool_call.func_name} 执行")
                return cached_result
        except Exception as e:
            logger.error(f"{self.log_prefix}检查工具缓存时出错: {e}")

        # 缓存未命中，执行原始工具调用
        result = await self._original_execute_tool_call(tool_call, tool_instance)

        # 将结果存入缓存
        try:
            tool_file_path = inspect.getfile(tool_instance.__class__)
            semantic_query = None
            if tool_instance.semantic_cache_query_key:
                semantic_query = function_args.get(tool_instance.semantic_cache_query_key)

            await tool_cache.set(
                tool_name=tool_call.func_name,
                function_args=function_args,
                tool_file_path=tool_file_path,
                data=result,
                ttl=tool_instance.cache_ttl,
                semantic_query=semantic_query,
            )
        except Exception as e:
            logger.error(f"{self.log_prefix}设置工具缓存时出错: {e}")
        # --- 缓存逻辑结束 ---

        return result

    async def _original_execute_tool_call(
        self, tool_call: ToolCall, tool_instance: BaseTool | None = None
    ) -> dict[str, Any] | None:
        """执行单个工具调用的原始逻辑"""
        try:
            function_name = tool_call.func_name
            function_args = tool_call.args or {}
            logger.info(
                f"{self.log_prefix} 正在执行工具: [bold green]{function_name}[/bold green] | 参数: {function_args}"
            )
            function_args["llm_called"] = True  # 标记为LLM调用

            # 检查是否是二步工具的第二步调用
            if "_" in function_name and function_name.count("_") >= 1:
                # 可能是二步工具的第二步调用，格式为 "tool_name_sub_tool_name"
                parts = function_name.split("_", 1)
                if len(parts) == 2:
                    base_tool_name, sub_tool_name = parts
                    base_tool_instance = get_tool_instance(base_tool_name)

                    if base_tool_instance and base_tool_instance.is_two_step_tool:
                        logger.info(f"{self.log_prefix}执行二步工具第二步: {base_tool_name}.{sub_tool_name}")
                        result = await base_tool_instance.execute_step_two(sub_tool_name, function_args)

                        # 清理待处理的第二步工具
                        self._pending_step_two_tools.pop(base_tool_name, None)

                        if result:
                            logger.debug(f"{self.log_prefix}二步工具第二步 {function_name} 执行成功")
                            return {
                                "tool_call_id": tool_call.call_id,
                                "role": "tool",
                                "name": function_name,
                                "type": "function",
                                "content": result.get("content", ""),
                            }

            # 获取对应工具实例
            tool_instance = tool_instance or get_tool_instance(function_name)
            if not tool_instance:
                logger.warning(f"未知工具名称: {function_name}")
                return None

            # 执行工具并记录日志
            logger.debug(f"{self.log_prefix}执行工具 {function_name}，参数: {function_args}")
            result = await tool_instance.execute(function_args)

            # 检查是否是二步工具的第一步结果
            if result and result.get("type") == "two_step_tool_step_one":
                logger.info(f"{self.log_prefix}二步工具第一步完成: {function_name}")
                # 保存第二步工具定义
                next_tool_def = result.get("next_tool_definition")
                if next_tool_def:
                    self._pending_step_two_tools[function_name] = next_tool_def
                    logger.debug(f"{self.log_prefix}已保存第二步工具定义: {next_tool_def['name']}")

            if result:
                logger.debug(f"{self.log_prefix}工具 {function_name} 执行成功，结果: {result}")
                return {
                    "tool_call_id": tool_call.call_id,
                    "role": "tool",
                    "name": function_name,
                    "type": "function",
                    "content": result.get("content", ""),
                }
            logger.warning(f"{self.log_prefix}工具 {function_name} 返回空结果")
            return None
        except Exception as e:
            logger.error(f"执行工具调用时发生错误: {e!s}")
            raise e

    async def execute_specific_tool_simple(self, tool_name: str, tool_args: dict) -> dict | None:
        """直接执行指定工具

        Args:
            tool_name: 工具名称
            tool_args: 工具参数
            validate_args: 是否验证参数

        Returns:
            Optional[Dict]: 工具执行结果，失败时返回None
        """
        try:
            tool_call = ToolCall(
                call_id=f"direct_tool_{time.time()}",
                func_name=tool_name,
                args=tool_args,
            )

            logger.info(f"{self.log_prefix}直接执行工具: {tool_name}")

            result = await self.execute_tool_call(tool_call)

            if result:
                tool_info = {
                    "type": result.get("type", "unknown_type"),
                    "id": result.get("id", f"direct_tool_{time.time()}"),
                    "content": result.get("content", ""),
                    "tool_name": tool_name,
                    "timestamp": time.time(),
                }
                logger.info(f"{self.log_prefix}直接工具执行成功: {tool_name}")
                return tool_info

        except Exception as e:
            logger.error(f"{self.log_prefix}直接工具执行失败 {tool_name}: {e}")

        return None


"""
ToolExecutor使用示例：

# 1. 基础使用 - 从聊天消息执行工具
executor = ToolExecutor(chat_id=my_chat_id)
results, _, _ = await executor.execute_from_chat_message(
    target_message="今天天气怎么样？现在几点了？",
    chat_history="",
    sender="用户"
)

# 2. 获取详细信息
results, used_tools, prompt = await executor.execute_from_chat_message(
    target_message="帮我查询Python相关知识",
    chat_history="",
    sender="用户",
    return_details=True
)

# 3. 直接执行特定工具
result = await executor.execute_specific_tool_simple(
    tool_name="get_knowledge",
    tool_args={"query": "机器学习"}
)
"""
