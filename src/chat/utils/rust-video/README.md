# 🎯 Rust Video Keyframe Extraction API

高性能视频关键帧提取API服务，基于Rust后端 + Python FastAPI。

## 📁 项目结构

```
rust-video/
├── outputs/              # 关键帧输出目录
├── src/                  # Rust源码
│   └── main.rs
├── target/               # Rust编译文件
├── api_server.py         # 🚀 主API服务器 (整合版)
├── start_server.py       # 生产启动脚本
├── config.py             # 配置管理
├── config.toml           # 配置文件
├── Cargo.toml           # Rust项目配置
├── Cargo.lock           # Rust依赖锁定
├── .gitignore           # Git忽略文件
└── README.md            # 项目文档
```

## 快速开始

### 1. 安装依赖
```bash
pip install fastapi uvicorn python-multipart aiofiles
```

### 2. 启动服务
```bash
# 开发模式
python api_server.py

# 生产模式
python start_server.py --mode prod --port 8050
```

### 3. 访问API
- **服务地址**: http://localhost:8050
- **API文档**: http://localhost:8050/docs
- **健康检查**: http://localhost:8050/health
- **性能指标**: http://localhost:8050/metrics

## API使用方法

### 主要端点

#### 1. 提取关键帧 (JSON响应)
```http
POST /extract-keyframes
Content-Type: multipart/form-data

- video: 视频文件 (.mp4, .avi, .mov, .mkv)
- scene_threshold: 场景变化阈值 (0.1-1.0, 默认0.3)
- max_frames: 最大关键帧数 (1-200, 默认50)
- resize_width: 调整宽度 (可选, 100-1920)
- time_interval: 时间间隔秒数 (可选, 0.1-60.0)
```

#### 2. 提取关键帧 (ZIP下载)
```http
POST /extract-keyframes-zip
Content-Type: multipart/form-data

参数同上，返回包含所有关键帧的ZIP文件
```

#### 3. 健康检查
```http
GET /health
```

#### 4. 性能指标
```http
GET /metrics
```

### Python客户端示例

```python
import requests

# 上传视频并提取关键帧
files = {'video': open('video.mp4', 'rb')}
data = {
    'scene_threshold': 0.3,
    'max_frames': 50,
    'resize_width': 800
}

response = requests.post(
    'http://localhost:8050/extract-keyframes',
    files=files,
    data=data
)

result = response.json()
print(f"提取了 {result['keyframe_count']} 个关键帧")
print(f"处理时间: {result['performance']['total_api_time']:.2f}秒")
```

### JavaScript客户端示例

```javascript
const formData = new FormData();
formData.append('video', videoFile);
formData.append('scene_threshold', '0.3');
formData.append('max_frames', '50');

fetch('http://localhost:8050/extract-keyframes', {
    method: 'POST',
    body: formData
})
.then(response => response.json())
.then(data => {
    console.log(`提取了 ${data.keyframe_count} 个关键帧`);
    console.log(`处理时间: ${data.performance.total_api_time}秒`);
});
```

### cURL示例

```bash
curl -X POST "http://localhost:8050/extract-keyframes" \
     -H "accept: application/json" \
     -H "Content-Type: multipart/form-data" \
     -F "video=@video.mp4" \
     -F "scene_threshold=0.3" \
     -F "max_frames=50"
```

## ⚙️ 配置

编辑 `config.toml` 文件：

```toml
[server]
host = "0.0.0.0"
port = 8050
debug = false

[processing]
default_scene_threshold = 0.3
default_max_frames = 50
timeout_seconds = 300

[performance]
async_workers = 4
max_file_size_mb = 500
```

## 性能特性

- **异步I/O**: 文件上传/下载异步处理
- **多线程处理**: 视频处理在独立线程池
- **内存优化**: 流式处理，减少内存占用
- **智能清理**: 自动临时文件管理
- **性能监控**: 实时处理时间和吞吐量统计

总之就是非常快（）

## 响应格式

```json
{
  "status": "success",
  "processing_time": 4.5,
  "output_directory": "/tmp/output_xxx",
  "keyframe_count": 15,
  "keyframes": [
    "/tmp/output_xxx/frame_001.jpg",
    "/tmp/output_xxx/frame_002.jpg"
  ],
  "performance": {
    "file_size_mb": 209.7,
    "upload_time": 0.23,
    "processing_time": 4.5,
    "total_api_time": 4.73,
    "upload_speed_mbps": 912.2
  },
  "rust_output": "处理完成",
  "command": "rust-video input.mp4 output/ --scene-threshold 0.3 --max-frames 50"
}
```

## 故障排除

### 常见问题

1. **Rust binary not found**
   ```bash
   cargo build  # 重新构建Rust项目
   ```

2. **端口被占用**
   ```bash
   # 修改config.toml中的端口号
   port = 8051
   ```

3. **内存不足**
   ```bash
   # 减少max_frames或resize_width参数
   ```

### 日志查看

服务启动时会显示详细的状态信息，包括：
- Rust二进制文件位置
- 配置加载状态
- 服务监听地址

## 集成支持

本API设计为独立服务，可轻松集成到任何项目中：

- **AI Bot项目**: 通过HTTP API调用
- **Web应用**: 直接前端调用或后端代理
- **移动应用**: REST API标准接口
- **批处理脚本**: Python/Shell脚本调用
