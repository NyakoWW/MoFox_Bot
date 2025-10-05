# MCP SSE 快速配置指南

## 什么是MCP SSE？

MCP (Model Context Protocol) SSE (Server-Sent Events) 是一种支持流式通信的协议，允许MoFox Bot通过SSE与兼容MCP协议的AI服务进行交互。

## 快速开始

### 步骤1: 安装依赖

```bash
# 使用uv（推荐）
uv sync

# 或使用pip
pip install mcp>=0.9.0 sse-starlette>=2.2.1
```

### 步骤2: 编辑配置文件

打开或创建 `model_config.toml` 文件，添加以下配置：

#### 2.1 添加MCP Provider

```toml
[[api_providers]]
name = "MCPProvider"                          # Provider名称，可自定义
base_url = "https://your-mcp-server.com"      # 你的MCP服务器地址
api_key = "your-mcp-api-key"                  # 你的API密钥
client_type = "mcp_sse"                       # 必须设置为 "mcp_sse"
timeout = 60                                  # 超时时间（秒）
max_retry = 2                                 # 最大重试次数
```

#### 2.2 添加MCP模型

```toml
[[models]]
model_identifier = "claude-3-5-sonnet-20241022"  # 模型ID
name = "mcp-claude"                              # 模型名称，用于引用
api_provider = "MCPProvider"                     # 使用上面配置的Provider
force_stream_mode = true                         # MCP建议使用流式模式
price_in = 3.0                                   # 输入价格（可选）
price_out = 15.0                                 # 输出价格（可选）
```

#### 2.3 在任务中使用MCP模型

```toml
# 例如：使用MCP模型作为回复模型
[model_task_config.replyer]
model_list = ["mcp-claude"]  # 引用上面定义的模型名称
temperature = 0.7
max_tokens = 800
```

### 步骤3: 验证配置

启动MoFox Bot，查看日志确认MCP SSE客户端是否正确加载：

```
[INFO] MCP-SSE客户端: 正在初始化...
[INFO] 已加载模型: mcp-claude (MCPProvider)
```

## 完整配置示例

```toml
# ===== MCP SSE Provider配置 =====
[[api_providers]]
name = "MCPProvider"
base_url = "https://api.anthropic.com"  # Anthropic的Claude支持MCP
api_key = "sk-ant-xxx..."
client_type = "mcp_sse"
timeout = 60
max_retry = 2
retry_interval = 10

# ===== MCP模型配置 =====
[[models]]
model_identifier = "claude-3-5-sonnet-20241022"
name = "mcp-claude-sonnet"
api_provider = "MCPProvider"
force_stream_mode = true
price_in = 3.0
price_out = 15.0

[[models]]
model_identifier = "claude-3-5-haiku-20241022"
name = "mcp-claude-haiku"
api_provider = "MCPProvider"
force_stream_mode = true
price_in = 1.0
price_out = 5.0

# ===== 任务配置：使用MCP模型 =====

# 回复生成使用Sonnet（高质量）
[model_task_config.replyer]
model_list = ["mcp-claude-sonnet"]
temperature = 0.7
max_tokens = 800

# 小型任务使用Haiku（快速响应）
[model_task_config.utils_small]
model_list = ["mcp-claude-haiku"]
temperature = 0.5
max_tokens = 500

# 工具调用使用Sonnet
[model_task_config.tool_use]
model_list = ["mcp-claude-sonnet"]
temperature = 0.3
max_tokens = 1000
```

## 支持的MCP服务

目前已知支持MCP协议的服务：

- ✅ **Anthropic Claude** (推荐)
- ✅ 任何实现MCP SSE协议的自定义服务器
- ⚠️ 其他服务需验证是否支持MCP协议

## 常见问题

### Q: 我的服务器不支持MCP怎么办？

A: 确保你的服务器实现了MCP SSE协议规范。如果是标准OpenAI API，请使用 `client_type = "openai"` 而不是 `"mcp_sse"`。

### Q: 如何测试MCP连接是否正常？

A: 启动Bot后，在日志中查找相关信息，或尝试发送一条测试消息。

### Q: MCP SSE与OpenAI客户端有什么区别？

A: 
- **MCP SSE**: 使用Server-Sent Events协议，支持更丰富的流式交互
- **OpenAI**: 使用标准OpenAI API格式
- **选择建议**: 如果你的服务明确支持MCP，使用MCP SSE；否则使用OpenAI客户端

### Q: 可以混合使用不同类型的客户端吗？

A: 可以！你可以在同一个配置文件中定义多个providers，使用不同的 `client_type`：

```toml
# OpenAI Provider
[[api_providers]]
name = "OpenAIProvider"
client_type = "openai"
# ...

# MCP Provider
[[api_providers]]
name = "MCPProvider"
client_type = "mcp_sse"
# ...

# Gemini Provider
[[api_providers]]
name = "GoogleProvider"
client_type = "aiohttp_gemini"
# ...
```

## 下一步

- 查看 [MCP_SSE_USAGE.md](./MCP_SSE_USAGE.md) 了解详细API使用
- 查看 [template/model_config_template.toml](../template/model_config_template.toml) 查看完整配置模板
- 参考 [README.md](../README.md) 了解MoFox Bot的整体架构

## 技术支持

如遇到问题，请：
1. 检查日志文件中的错误信息
2. 确认MCP服务器地址和API密钥正确
3. 验证服务器是否支持MCP SSE协议
4. 提交Issue到项目仓库
