# MCP工具集成 - 简化指南

## ✅ 已完成的工作

MCP (Model Context Protocol) 工具支持已经完全集成到MoFox Bot！**AI现在可以自动发现并调用MCP工具了**。

## 🎯 快速开始

### 步骤1: 启动MCP服务器

首先你需要一个MCP服务器。最简单的方式是使用官方提供的文件系统服务器：

```bash
# 安装（需要Node.js）
npm install -g @modelcontextprotocol/server-filesystem

# 启动服务器，允许访问指定目录
mcp-server-filesystem --port 3000 /path/to/your/project
```

### 步骤2: 配置Bot

编辑 `config/bot_config.toml`，在文件末尾添加：

```toml
[[mcp_servers]]
name = "filesystem"
url = "http://localhost:3000"
api_key = ""  # 如果服务器不需要认证就留空
timeout = 30
enabled = true
```

### 步骤3: 启动Bot

```bash
python bot.py
```

启动后你会看到：

```
[INFO] 连接MCP服务器: filesystem (http://localhost:3000)
[INFO] 从filesystem获取5个工具
[INFO] MCP工具提供器初始化成功
```

### 步骤4: AI自动使用工具

现在AI可以自动调用MCP工具了！

**示例对话：**

```
用户: 帮我读取README.md文件的内容

AI: [内部决策: 需要读取文件 → 调用 filesystem_read_file 工具]
    README.md的内容是...

用户: 列出当前目录下的所有文件

AI: [调用 filesystem_list_directory 工具]
    当前目录包含以下文件：
    - README.md
    - bot.py
    - ...
```

## 🔧 工作原理

```
用户消息
    ↓
AI决策系统 (ToolExecutor)
    ↓
获取可用工具列表
    ↓
【包含Bot内置工具 + MCP工具】 ← 自动合并
    ↓
AI选择需要的工具
    ↓
执行工具调用
    ↓
返回结果给用户
```

## 📝 配置多个MCP服务器

```toml
# 文件系统工具
[[mcp_servers]]
name = "filesystem"
url = "http://localhost:3000"
enabled = true

# Git工具
[[mcp_servers]]
name = "git"
url = "http://localhost:3001"
enabled = true

# 数据库工具
[[mcp_servers]]
name = "database"
url = "http://localhost:3002"
api_key = "your-secret-key"
enabled = true
```

每个服务器的工具会自动添加名称前缀：
- `filesystem_read_file`
- `git_status`
- `database_query`

## 🛠️ 可用的MCP服务器

官方提供的MCP服务器：

1. **@modelcontextprotocol/server-filesystem** - 文件系统操作
2. **@modelcontextprotocol/server-git** - Git操作
3. **@modelcontextprotocol/server-github** - GitHub API
4. **@modelcontextprotocol/server-sqlite** - SQLite数据库
5. **@modelcontextprotocol/server-postgres** - PostgreSQL数据库

你也可以开发自定义MCP服务器！

## 🐛 常见问题

### Q: 如何查看AI是否使用了MCP工具？

查看日志，会显示：
```
[INFO] [工具执行器] 正在执行工具: filesystem_read_file
[INFO] 调用MCP工具: filesystem_read_file
```

### Q: MCP服务器连接失败怎么办？

检查：
1. MCP服务器是否正在运行
2. URL配置是否正确（注意端口号）
3. 防火墙是否阻止连接

### Q: 如何临时禁用MCP工具？

在配置中设置 `enabled = false`：

```toml
[[mcp_servers]]
name = "filesystem"
url = "http://localhost:3000"
enabled = false  # 禁用
```

## 📚 相关文档

- **详细集成文档**: [MCP_TOOLS_INTEGRATION.md](./MCP_TOOLS_INTEGRATION.md)
- **MCP SSE客户端**: [MCP_SSE_USAGE.md](./MCP_SSE_USAGE.md)
- **MCP协议官方文档**: https://github.com/anthropics/mcp

## 🎉 总结

MCP工具支持已经完全集成！你只需要：

1. ✅ 启动MCP服务器
2. ✅ 在`bot_config.toml`中配置
3. ✅ 启动Bot

**AI会自动发现并使用工具，无需任何额外代码！**

---

**实现方式**: 通过修改`tool_api.py`和`tool_use.py`，将MCP工具无缝集成到现有工具系统
**版本**: v1.0.0
**日期**: 2025-10-05
