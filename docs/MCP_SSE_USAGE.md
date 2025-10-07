# MCP SSE 客户端使用指南

## 简介

MCP (Model Context Protocol) SSE (Server-Sent Events) 客户端支持通过SSE协议与MCP兼容的服务器进行通信。该客户端已集成到MoFox Bot的LLM模型客户端系统中。

## 功能特性

- ✅ 支持SSE流式响应
- ✅ 支持多轮对话
- ✅ 支持工具调用（Function Calling）
- ✅ 支持多模态内容（文本+图片）
- ✅ 自动处理中断信号
- ✅ 完整的Token使用统计

## 配置方法

### 1. 安装依赖

依赖已自动添加到项目中：
```bash
pip install mcp>=0.9.0 sse-starlette>=2.2.1
```

或使用uv：
```bash
uv sync
```

### 2. 配置API Provider

在 `model_config.toml` 配置文件中添加MCP SSE provider：

```toml
[[api_providers]]
name = "MCPProvider"
base_url = "https://your-mcp-server.com"  # MCP服务器地址
api_key = "your-mcp-api-key-here"
client_type = "mcp_sse"  # 使用MCP SSE客户端
max_retry = 2
timeout = 60  # MCP流式请求可能需要更长超时时间
retry_interval = 10
```

### 3. 配置模型

在同一个配置文件中添加使用MCP provider的模型：

```toml
[[models]]
model_identifier = "claude-3-5-sonnet-20241022"  # 或其他支持MCP的模型
name = "mcp-claude-sonnet"
api_provider = "MCPProvider"  # 对应上面配置的MCP provider
price_in = 3.0
price_out = 15.0
force_stream_mode = true  # MCP SSE默认使用流式模式
```

### 4. 在任务配置中使用MCP模型

可以在任何任务配置中使用MCP模型：

```toml
[model_task_config.replyer]
model_list = ["mcp-claude-sonnet"]  # 使用MCP模型
temperature = 0.7
max_tokens = 800
```

**注意**：配置模板已包含MCP SSE的示例配置，可参考 `template/model_config_template.toml`

## 使用示例

### 基础对话

```python
from src.llm_models.model_client.base_client import client_registry
from src.llm_models.payload_content.message import Message, MessageBuilder, RoleType
from src.config.api_ada_configs import APIProvider, ModelInfo

# 获取客户端
api_provider = APIProvider(
    name="mcp_provider",
    client_type="mcp_sse",
    base_url="https://your-mcp-server.com",
    api_key="your-api-key"
)

client = client_registry.get_client_class_instance(api_provider)

# 构建消息
messages = [
    MessageBuilder()
        .set_role(RoleType.User)
        .add_text_content("你好，请介绍一下你自己")
        .build()
]

# 获取响应
model_info = ModelInfo(
    name="mcp_model",
    api_provider="mcp_provider",
    model_identifier="your-model-name"
)

response = await client.get_response(
    model_info=model_info,
    message_list=messages,
    max_tokens=1024,
    temperature=0.7
)

print(response.content)
```

### 使用工具调用

```python
from src.llm_models.payload_content.tool_option import (
    ToolOptionBuilder,
    ToolParamType
)

# 定义工具
tools = [
    ToolOptionBuilder()
        .set_name("get_weather")
        .set_description("获取指定城市的天气信息")
        .add_param(
            name="city",
            param_type=ToolParamType.STRING,
            description="城市名称",
            required=True
        )
        .build()
]

# 发送请求
response = await client.get_response(
    model_info=model_info,
    message_list=messages,
    tool_options=tools,
    max_tokens=1024,
    temperature=0.7
)

# 检查工具调用
if response.tool_calls:
    for tool_call in response.tool_calls:
        print(f"调用工具: {tool_call.func_name}")
        print(f"参数: {tool_call.args}")
```

### 多模态对话

```python
import base64

# 读取图片并编码
with open("image.jpg", "rb") as f:
    image_data = base64.b64encode(f.read()).decode("utf-8")

# 构建多模态消息
messages = [
    MessageBuilder()
        .set_role(RoleType.User)
        .add_text_content("这张图片里有什么？")
        .add_image_content("jpg", image_data)
        .build()
]

response = await client.get_response(
    model_info=model_info,
    message_list=messages
)
```

### 中断处理

```python
import asyncio

# 创建中断事件
interrupt_flag = asyncio.Event()

# 在另一个协程中设置中断
async def interrupt_after_delay():
    await asyncio.sleep(5)
    interrupt_flag.set()

asyncio.create_task(interrupt_after_delay())

try:
    response = await client.get_response(
        model_info=model_info,
        message_list=messages,
        interrupt_flag=interrupt_flag
    )
except ReqAbortException:
    print("请求被中断")
```

## MCP协议规范

MCP SSE客户端遵循以下协议规范：

### 请求格式

```json
{
    "model": "model-name",
    "messages": [
        {
            "role": "user",
            "content": "message content"
        }
    ],
    "max_tokens": 1024,
    "temperature": 0.7,
    "stream": true,
    "tools": [
        {
            "name": "tool_name",
            "description": "tool description",
            "input_schema": {
                "type": "object",
                "properties": {...},
                "required": [...]
            }
        }
    ]
}
```

### SSE事件类型

客户端处理以下SSE事件：

1. **content_block_start** - 内容块开始
2. **content_block_delta** - 内容块增量
3. **content_block_stop** - 内容块结束
4. **message_delta** - 消息元数据更新
5. **message_stop** - 消息结束

## 限制说明

当前MCP SSE客户端的限制：

- ❌ 不支持嵌入（Embedding）功能
- ❌ 不支持音频转录功能
- ✅ 仅支持流式响应（SSE特性）

## 故障排查

### 连接失败

检查：
1. base_url是否正确
2. API key是否有效
3. 网络连接是否正常
4. 服务器是否支持SSE协议

### 解析错误

检查：
1. 服务器返回的SSE格式是否符合MCP规范
2. 查看日志中的详细错误信息

### 工具调用失败

检查：
1. 工具定义的schema是否正确
2. 服务器是否支持工具调用功能

## 相关文档

- [MCP协议规范](https://github.com/anthropics/mcp)
- [SSE规范](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events)
- [MoFox Bot文档](../README.md)

## 更新日志

### v0.8.1
- ✅ 添加MCP SSE客户端支持
- ✅ 支持流式响应和工具调用
- ✅ 支持多模态内容
