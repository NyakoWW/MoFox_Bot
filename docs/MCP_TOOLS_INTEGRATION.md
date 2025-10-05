# MCP工具集成完整指南

## 概述

MoFox Bot现在完全支持MCP (Model Context Protocol)，包括：
1. **MCP SSE客户端** - 与支持MCP的LLM（如Claude）通信
2. **MCP工具提供器** - 将MCP服务器的工具集成到Bot，让AI能够调用

## 架构说明

```
┌─────────────────────────────────────────┐
│        MoFox Bot AI系统                  │
│  ┌───────────────────────────────────┐  │
│  │  AI决策层 (ToolExecutor)         │  │
│  │  - 分析用户请求                   │  │
│  │  - 决定调用哪些工具               │  │
│  └───────────────┬───────────────────┘  │
│                  │                       │
│  ┌───────────────▼───────────────────┐  │
│  │  工具注册表 (ComponentRegistry)   │  │
│  │  - Bot内置工具                    │  │
│  │  - MCP动态工具 ✨                 │  │
│  └───────────────┬───────────────────┘  │
│                  │                       │
│  ┌───────────────▼───────────────────┐  │
│  │  MCP工具提供器插件                │  │
│  │  - 连接MCP服务器                  │  │
│  │  - 动态注册工具                   │  │
│  └───────────────┬───────────────────┘  │
└──────────────────┼───────────────────────┘
                   │
    ┌──────────────▼──────────────┐
    │     MCP连接器                │
    │  - tools/list               │
    │  - tools/call               │
    │  - resources/list (未来)   │
    └──────────────┬──────────────┘
                   │
    ┌──────────────▼──────────────┐
    │      MCP服务器               │
    │  - 文件系统工具              │
    │  - Git工具                  │
    │  - 数据库工具               │
    │  - 自定义工具...            │
    └─────────────────────────────┘
```

## 完整配置步骤

### 步骤1: 启动MCP服务器

首先你需要一个运行中的MCP服务器。这里以官方的文件系统MCP服务器为例：

```bash
# 安装MCP服务器（以filesystem为例）
npm install -g @modelcontextprotocol/server-filesystem

# 启动服务器
mcp-server-filesystem --port 3000 /path/to/allowed/directory
```

或使用其他MCP服务器：
- **Git MCP**: 提供Git操作工具
- **数据库MCP**: 提供数据库查询工具
- **自定义MCP服务器**: 你自己开发的MCP服务器

### 步骤2: 配置MCP工具提供器插件

编辑配置文件 `config/plugins/mcp_tools_provider.toml`：

```toml
[plugin]
enabled = true  # 启用插件

# 配置MCP服务器
[[mcp_servers]]
name = "filesystem"  # 服务器标识名
url = "http://localhost:3000"  # MCP服务器地址
api_key = ""  # API密钥（如果需要）
timeout = 30  # 超时时间
enabled = true  # 是否启用

# 可以配置多个MCP服务器
[[mcp_servers]]
name = "git"
url = "http://localhost:3001"
enabled = true
```

### 步骤3: 启动Bot

```bash
python bot.py
```

启动后，你会在日志中看到：

```
[INFO] MCP工具提供器插件启动中...
[INFO] 发现 1 个MCP服务器配置
[INFO] 正在连接MCP服务器: filesystem (http://localhost:3000)
[INFO] 从MCP服务器 'filesystem' 获取到 5 个工具
[INFO] ✓ 已注册MCP工具: filesystem_read_file
[INFO] ✓ 已注册MCP工具: filesystem_write_file
[INFO] ✓ 已注册MCP工具: filesystem_list_directory
...
[INFO] MCP工具提供器插件启动完成，共注册 5 个工具
```

### 步骤4: AI自动调用MCP工具

现在AI可以自动发现并调用这些工具！例如：

**用户**: "帮我读取项目根目录下的README.md文件"

**AI决策过程**:
1. 分析用户请求 → 需要读取文件
2. 查找可用工具 → 发现 `filesystem_read_file`
3. 调用工具 → `filesystem_read_file(path="README.md")`
4. 获取结果 → 文件内容
5. 生成回复 → "README.md的内容是..."

## 工具命名规则

MCP工具会自动添加服务器名前缀，避免冲突：

- 原始工具名: `read_file`
- 注册后: `filesystem_read_file`

如果有多个MCP服务器提供相同名称的工具，它们会被区分开：
- 服务器A: `serverA_search`
- 服务器B: `serverB_search`

## 配置示例

### 示例1: 本地文件操作

```toml
[[mcp_servers]]
name = "local_fs"
url = "http://localhost:3000"
enabled = true
```

**可用工具**:
- `local_fs_read_file` - 读取文件
- `local_fs_write_file` - 写入文件
- `local_fs_list_directory` - 列出目录

### 示例2: Git操作

```toml
[[mcp_servers]]
name = "git"
url = "http://localhost:3001"
enabled = true
```

**可用工具**:
- `git_status` - 查看Git状态
- `git_commit` - 提交更改
- `git_log` - 查看提交历史

### 示例3: 多服务器配置

```toml
[[mcp_servers]]
name = "filesystem"
url = "http://localhost:3000"
enabled = true

[[mcp_servers]]
name = "database"
url = "http://localhost:3002"
api_key = "db-secret-key"
enabled = true

[[mcp_servers]]
name = "api_tools"
url = "https://mcp.example.com"
api_key = "your-api-key"
timeout = 60
enabled = true
```

## 开发自定义MCP服务器

你可以开发自己的MCP服务器来提供自定义工具：

```javascript
// 简单的MCP服务器示例 (Node.js)
const express = require('express');
const app = express();

app.use(express.json());

// 列出工具
app.post('/tools/list', (req, res) => {
  res.json({
    tools: [
      {
        name: 'custom_tool',
        description: '自定义工具描述',
        inputSchema: {
          type: 'object',
          properties: {
            param1: {
              type: 'string',
              description: '参数1'
            }
          },
          required: ['param1']
        }
      }
    ]
  });
});

// 执行工具
app.post('/tools/call', async (req, res) => {
  const { name, arguments: args } = req.body;
  
  if (name === 'custom_tool') {
    // 执行你的逻辑
    const result = await doSomething(args.param1);
    
    res.json({
      content: [
        {
          type: 'text',
          text: result
        }
      ]
    });
  }
});

app.listen(3000, () => {
  console.log('MCP服务器运行在 http://localhost:3000');
});
```

## 常见问题

### Q: MCP服务器连接失败？

**检查**:
1. MCP服务器是否正在运行
2. URL配置是否正确
3. 防火墙是否阻止连接
4. 查看日志中的具体错误信息

### Q: 工具注册成功但AI不调用？

**原因**:
- 工具描述不够清晰
- 参数定义不明确

**解决**:
在MCP服务器端优化工具的`description`和`inputSchema`

### Q: 如何禁用某个MCP服务器？

在配置中设置：
```toml
[[mcp_servers]]
enabled = false  # 禁用
```

### Q: 如何查看已注册的MCP工具？

查看启动日志，或在Bot运行时检查组件注册表。

## MCP协议规范

MCP服务器必须实现以下端点：

### 1. POST /tools/list
列出所有可用工具

**响应**:
```json
{
  "tools": [
    {
      "name": "tool_name",
      "description": "工具描述",
      "inputSchema": {
        "type": "object",
        "properties": { ... },
        "required": [...]
      }
    }
  ]
}
```

### 2. POST /tools/call
执行工具

**请求**:
```json
{
  "name": "tool_name",
  "arguments": { ... }
}
```

**响应**:
```json
{
  "content": [
    {
      "type": "text",
      "text": "执行结果"
    }
  ]
}
```

## 高级功能

### 动态刷新工具列表

工具列表默认缓存5分钟。如果MCP服务器更新了工具，Bot会自动在下次缓存过期后刷新。

### 错误处理

MCP工具调用失败时，会返回错误信息给AI，AI可以据此做出相应处理或提示用户。

### 性能优化

- 工具列表有缓存机制
- 支持并发工具调用
- 自动重试机制

## 相关文档

- [MCP SSE使用指南](./MCP_SSE_USAGE.md)
- [MCP协议官方文档](https://github.com/anthropics/mcp)
- [插件开发文档](../README.md)

## 更新日志

### v1.0.0 (2025-10-05)
- ✅ 完整的MCP工具集成
- ✅ 动态工具注册
- ✅ 多服务器支持
- ✅ 自动错误处理

---

**集成状态**: ✅ 生产就绪  
**版本**: v1.0.0  
**更新时间**: 2025-10-05
