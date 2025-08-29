#!/usr/bin/env python3
"""
Rust Video Keyframe Extraction API Server
高性能视频关键帧提取API服务 

功能:
- 视频上传和关键帧提取
- 异步多线程处理
- 性能监控和健康检查
- 自动资源清理

启动: python api_server.py
地址: http://localhost:8050
"""

import os
import json
import subprocess
import tempfile
import zipfile
import shutil
import asyncio
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

import uvicorn
from fastapi import FastAPI, File, UploadFile, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# 导入配置管理
from config import config

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# 内置视频处理器 (整合版)
# ============================================================================

class VideoKeyframeExtractor:
    """整合的视频关键帧提取器"""
    
    def __init__(self, rust_binary_path: Optional[str] = None):
        self.rust_binary_path = rust_binary_path or self._find_rust_binary()
        if not self.rust_binary_path or not Path(self.rust_binary_path).exists():
            raise FileNotFoundError(f"Rust binary not found: {self.rust_binary_path}")
    
    def _find_rust_binary(self) -> str:
        """查找Rust二进制文件"""
        possible_paths = [
            "./target/debug/rust-video.exe",
            "./target/release/rust-video.exe", 
            "./target/debug/rust-video",
            "./target/release/rust-video"
        ]
        
        for path in possible_paths:
            if Path(path).exists():
                return str(Path(path).absolute())
        
        # 尝试构建
        try:
            subprocess.run(["cargo", "build"], check=True, capture_output=True)
            for path in possible_paths:
                if Path(path).exists():
                    return str(Path(path).absolute())
        except subprocess.CalledProcessError:
            pass
            
        raise FileNotFoundError("Rust binary not found and build failed")
    
    def process_video(
        self,
        video_path: str,
        output_dir: str = "outputs",
        scene_threshold: float = 0.3,
        max_frames: int = 50,
        resize_width: Optional[int] = None,
        time_interval: Optional[float] = None
    ) -> Dict[str, Any]:
        """处理视频提取关键帧"""
        
        video_path = Path(video_path)
        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")
        
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 构建命令
        cmd = [self.rust_binary_path, str(video_path), str(output_dir)]
        cmd.extend(["--scene-threshold", str(scene_threshold)])
        cmd.extend(["--max-frames", str(max_frames)])
        
        if resize_width:
            cmd.extend(["--resize-width", str(resize_width)])
        if time_interval:
            cmd.extend(["--time-interval", str(time_interval)])
        
        # 执行处理
        start_time = time.time()
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=300  # 5分钟超时
            )
            
            processing_time = time.time() - start_time
            
            # 解析输出
            output_files = list(output_dir.glob("*.jpg"))
            
            return {
                "status": "success",
                "processing_time": processing_time,
                "output_directory": str(output_dir),
                "keyframe_count": len(output_files),
                "keyframes": [str(f) for f in output_files],
                "rust_output": result.stdout,
                "command": " ".join(cmd)
            }
            
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=408, detail="Video processing timeout")
        except subprocess.CalledProcessError as e:
            raise HTTPException(
                status_code=500,
                detail=f"Video processing failed: {e.stderr}"
            )

# ============================================================================
# 异步处理器 (整合版)
# ============================================================================

class AsyncVideoProcessor:
    """高性能异步视频处理器"""
    
    def __init__(self):
        self.extractor = VideoKeyframeExtractor()
    
    async def process_video_async(
        self,
        upload_file: UploadFile,
        processing_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """异步视频处理主流程"""
        
        start_time = time.time()
        
        # 1. 异步保存上传文件
        upload_start = time.time()
        temp_fd, temp_path_str = tempfile.mkstemp(suffix='.mp4')
        temp_path = Path(temp_path_str)
        
        try:
            os.close(temp_fd)
            
            # 异步读取并保存文件
            content = await upload_file.read()
            with open(temp_path, 'wb') as f:
                f.write(content)
            
            upload_time = time.time() - upload_start
            file_size = len(content)
            
            # 2. 多线程处理视频
            process_start = time.time()
            temp_output_dir = tempfile.mkdtemp()
            output_path = Path(temp_output_dir)
            
            try:
                # 在线程池中异步处理
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    self._process_video_sync,
                    str(temp_path),
                    str(output_path),
                    processing_params
                )
                
                process_time = time.time() - process_start
                total_time = time.time() - start_time
                
                # 添加性能指标
                result.update({
                    'performance': {
                        'file_size_mb': file_size / (1024 * 1024),
                        'upload_time': upload_time,
                        'processing_time': process_time,
                        'total_api_time': total_time,
                        'upload_speed_mbps': (file_size / (1024 * 1024)) / upload_time if upload_time > 0 else 0
                    }
                })
                
                return result
                
            finally:
                # 清理输出目录
                try:
                    shutil.rmtree(temp_output_dir, ignore_errors=True)
                except Exception as e:
                    logger.warning(f"Failed to cleanup output directory: {e}")
                
        finally:
            # 清理临时文件
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except Exception as e:
                logger.warning(f"Failed to cleanup temp file: {e}")
    
    def _process_video_sync(self, video_path: str, output_dir: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """在线程池中同步处理视频"""
        return self.extractor.process_video(
            video_path=video_path,
            output_dir=output_dir,
            **params
        )

# ============================================================================
# FastAPI 应用初始化
# ============================================================================

app = FastAPI(
    title="Rust Video Keyframe API",
    description="高性能视频关键帧提取API服务",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局处理器实例
video_processor = AsyncVideoProcessor()

# 简单的统计
stats = {
    "total_requests": 0,
    "processing_times": [],
    "start_time": datetime.now()
}

# ============================================================================
# API 路由
# ============================================================================

@app.get("/", response_class=JSONResponse)
async def root():
    """API根路径"""
    return {
        "message": "Rust Video Keyframe Extraction API",
        "version": "2.0.0",
        "status": "ready",
        "docs": "/docs",
        "health": "/health",
        "metrics": "/metrics"
    }

@app.get("/health")
async def health_check():
    """健康检查端点"""
    try:
        # 检查Rust二进制
        rust_binary = video_processor.extractor.rust_binary_path
        rust_status = "ok" if Path(rust_binary).exists() else "missing"
        
        return {
            "status": rust_status,
            "timestamp": datetime.now().isoformat(),
            "version": "2.0.0",
            "rust_binary": rust_binary
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Health check failed: {str(e)}")

@app.get("/metrics")
async def get_metrics():
    """获取性能指标"""
    avg_time = sum(stats["processing_times"]) / len(stats["processing_times"]) if stats["processing_times"] else 0
    uptime = (datetime.now() - stats["start_time"]).total_seconds()
    
    return {
        "total_requests": stats["total_requests"],
        "average_processing_time": avg_time,
        "last_24h_requests": stats["total_requests"],  # 简化版本
        "system_info": {
            "uptime_seconds": uptime,
            "memory_usage": "N/A",  # 可以扩展
            "cpu_usage": "N/A"
        }
    }

@app.post("/extract-keyframes")
async def extract_keyframes(
    video: UploadFile = File(..., description="视频文件"),
    scene_threshold: float = Form(0.3, description="场景变化阈值"),
    max_frames: int = Form(50, description="最大关键帧数量"),
    resize_width: Optional[int] = Form(None, description="调整宽度"),
    time_interval: Optional[float] = Form(None, description="时间间隔")
):
    """提取视频关键帧 (主要API端点)"""
    
    # 参数验证
    if not video.filename.lower().endswith(('.mp4', '.avi', '.mov', '.mkv')):
        raise HTTPException(status_code=400, detail="不支持的视频格式")
    
    # 更新统计
    stats["total_requests"] += 1
    
    try:
        # 构建处理参数
        params = {
            "scene_threshold": scene_threshold,
            "max_frames": max_frames
        }
        if resize_width:
            params["resize_width"] = resize_width
        if time_interval:
            params["time_interval"] = time_interval
        
        # 异步处理
        start_time = time.time()
        result = await video_processor.process_video_async(video, params)
        processing_time = time.time() - start_time
        
        # 更新统计
        stats["processing_times"].append(processing_time)
        if len(stats["processing_times"]) > 100:  # 保持最近100次记录
            stats["processing_times"] = stats["processing_times"][-100:]
        
        return JSONResponse(content=result)
        
    except Exception as e:
        logger.error(f"Processing failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")

@app.post("/extract-keyframes-zip")
async def extract_keyframes_zip(
    video: UploadFile = File(...),
    scene_threshold: float = Form(0.3),
    max_frames: int = Form(50),
    resize_width: Optional[int] = Form(None),
    time_interval: Optional[float] = Form(None)
):
    """提取关键帧并返回ZIP文件"""
    
    # 验证文件类型
    if not video.filename.lower().endswith(('.mp4', '.avi', '.mov', '.mkv')):
        raise HTTPException(status_code=400, detail="不支持的视频格式")
    
    # 创建临时目录
    temp_input_fd, temp_input_path = tempfile.mkstemp(suffix='.mp4')
    temp_output_dir = tempfile.mkdtemp()
    
    try:
        os.close(temp_input_fd)
        
        # 保存上传的视频
        content = await video.read()
        with open(temp_input_path, 'wb') as f:
            f.write(content)
        
        # 处理参数
        params = {
            "scene_threshold": scene_threshold,
            "max_frames": max_frames
        }
        if resize_width:
            params["resize_width"] = resize_width
        if time_interval:
            params["time_interval"] = time_interval
        
        # 处理视频
        result = video_processor.extractor.process_video(
            video_path=temp_input_path,
            output_dir=temp_output_dir,
            **params
        )
        
        # 创建ZIP文件
        zip_fd, zip_path = tempfile.mkstemp(suffix='.zip')
        os.close(zip_fd)
        
        with zipfile.ZipFile(zip_path, 'w') as zip_file:
            # 添加关键帧图片
            for keyframe_path in result.get("keyframes", []):
                if Path(keyframe_path).exists():
                    zip_file.write(keyframe_path, Path(keyframe_path).name)
            
            # 添加处理信息
            info_content = json.dumps(result, indent=2, ensure_ascii=False)
            zip_file.writestr("processing_info.json", info_content)
        
        # 返回ZIP文件
        return FileResponse(
            zip_path,
            media_type='application/zip',
            filename=f"keyframes_{video.filename}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")
    
    finally:
        # 清理临时文件
        for path in [temp_input_path, temp_output_dir]:
            try:
                if Path(path).is_file():
                    Path(path).unlink()
                elif Path(path).is_dir():
                    shutil.rmtree(path, ignore_errors=True)
            except Exception:
                pass

# ============================================================================
# 应用启动
# ============================================================================

def main():
    """启动API服务器"""
    
    # 获取配置
    server_config = config.get('server')
    host = server_config.get('host', '0.0.0.0')
    port = server_config.get('port', 8050)
    
    print(f"""
Rust Video Keyframe Extraction API
=====================================
地址: http://{host}:{port}
文档: http://{host}:{port}/docs
健康检查: http://{host}:{port}/health
性能指标: http://{host}:{port}/metrics
=====================================
    """)
    
    # 检查Rust二进制
    try:
        rust_binary = video_processor.extractor.rust_binary_path
        print(f"✓ Rust binary: {rust_binary}")
    except Exception as e:
        print(f"⚠️  Rust binary check failed: {e}")
    
    # 启动服务器
    uvicorn.run(
        "api_server:app",
        host=host,
        port=port,
        reload=False,  # 生产环境关闭热重载
        access_log=True
    )

if __name__ == "__main__":
    main()
