#!/usr/bin/env python3
"""
启动脚本

支持开发模式和生产模式启动
"""

import os
import sys
import subprocess
import argparse
from pathlib import Path
from config import config


def check_rust_executable():
    """检查 Rust 可执行文件是否存在"""
    rust_config = config.get("rust")
    executable_name = rust_config.get("executable_name", "video_keyframe_extractor")
    executable_path = rust_config.get("executable_path", "target/release")
    
    possible_paths = [
        f"./{executable_path}/{executable_name}.exe",
        f"./{executable_path}/{executable_name}",
        f"./{executable_name}.exe",
        f"./{executable_name}"
    ]
    
    for path in possible_paths:
        if Path(path).exists():
            print(f"✓ Found Rust executable: {path}")
            return str(Path(path).absolute())
    
    print("⚠ Warning: Rust executable not found")
    print("Please compile first: cargo build --release")
    return None


def check_dependencies():
    """检查 Python 依赖"""
    try:
        import fastapi
        import uvicorn
        print("✓ FastAPI dependencies available")
        return True
    except ImportError as e:
        print(f"✗ Missing dependencies: {e}")
        print("Please install: pip install -r requirements.txt")
        return False


def install_dependencies():
    """安装依赖"""
    print("Installing dependencies...")
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], 
                      check=True)
        print("✓ Dependencies installed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Failed to install dependencies: {e}")
        return False


def start_development_server(host="127.0.0.1", port=8050, reload=True):
    """启动开发服务器"""
    print(f" Starting development server on http://{host}:{port}")
    print(f" API docs: http://{host}:{port}/docs")
    print(f" Health check: http://{host}:{port}/health")
    
    try:
        import uvicorn
        uvicorn.run(
            "api_server:app",
            host=host,
            port=port,
            reload=reload,
            log_level="info"
        )
    except ImportError:
        print("uvicorn not found, trying with subprocess...")
        subprocess.run([
            sys.executable, "-m", "uvicorn", 
            "api_server:app",
            "--host", host,
            "--port", str(port),
            "--reload" if reload else ""
        ])


def start_production_server(host="0.0.0.0", port=8000, workers=4):
    """启动生产服务器"""
    print(f"🚀 Starting production server on http://{host}:{port}")
    print(f"Workers: {workers}")
    
    subprocess.run([
        sys.executable, "-m", "uvicorn",
        "api_server:app",
        "--host", host,
        "--port", str(port),
        "--workers", str(workers),
        "--log-level", "warning"
    ])


def create_systemd_service():
    """创建 systemd 服务文件"""
    current_dir = Path.cwd()
    python_path = sys.executable
    
    service_content = f"""[Unit]
Description=Video Keyframe Extraction API Server
After=network.target

[Service]
Type=exec
User=www-data
WorkingDirectory={current_dir}
Environment=PATH=/usr/bin:/usr/local/bin
ExecStart={python_path} -m uvicorn api_server:app --host 0.0.0.0 --port 8000 --workers 4
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""
    
    service_file = Path("/etc/systemd/system/video-keyframe-api.service")
    
    try:
        with open(service_file, 'w') as f:
            f.write(service_content)
        
        print(f"✓ Systemd service created: {service_file}")
        print("To enable and start:")
        print("  sudo systemctl enable video-keyframe-api")
        print("  sudo systemctl start video-keyframe-api")
        
    except PermissionError:
        print("✗ Permission denied. Please run with sudo for systemd service creation")
        
        # 创建本地副本
        local_service = Path("./video-keyframe-api.service")
        with open(local_service, 'w') as f:
            f.write(service_content)
        
        print(f"✓ Service file created locally: {local_service}")
        print(f"To install: sudo cp {local_service} /etc/systemd/system/")


def main():
    parser = argparse.ArgumentParser(description="Video Keyframe Extraction API Server")
    
    # 从配置文件获取默认值
    server_config = config.get_server_config()
    
    parser.add_argument("--mode", choices=["dev", "prod", "install"], default="dev",
                       help="运行模式: dev (开发), prod (生产), install (安装依赖)")
    parser.add_argument("--host", default=server_config.get("host", "127.0.0.1"), help="绑定主机")
    parser.add_argument("--port", type=int, default=server_config.get("port", 8000), help="端口号")
    parser.add_argument("--workers", type=int, default=server_config.get("workers", 4), help="生产模式工作进程数")
    parser.add_argument("--no-reload", action="store_true", help="禁用自动重载")
    parser.add_argument("--check", action="store_true", help="仅检查环境")
    parser.add_argument("--create-service", action="store_true", help="创建 systemd 服务")
    
    args = parser.parse_args()
    
    print("=== Video Keyframe Extraction API Server ===")
    
    # 检查环境
    rust_exe = check_rust_executable()
    deps_ok = check_dependencies()
    
    if args.check:
        print("\n=== Environment Check ===")
        print(f"Rust executable: {'✓' if rust_exe else '✗'}")
        print(f"Python dependencies: {'✓' if deps_ok else '✗'}")
        return
    
    if args.create_service:
        create_systemd_service()
        return
    
    # 安装模式
    if args.mode == "install":
        if not deps_ok:
            install_dependencies()
        else:
            print("✓ Dependencies already installed")
        return
    
    # 检查必要条件
    if not rust_exe:
        print("✗ Cannot start without Rust executable")
        print("Please run: cargo build --release")
        sys.exit(1)
    
    if not deps_ok:
        print("Installing missing dependencies...")
        if not install_dependencies():
            sys.exit(1)
    
    # 启动服务器
    if args.mode == "dev":
        start_development_server(
            host=args.host, 
            port=args.port, 
            reload=not args.no_reload
        )
    elif args.mode == "prod":
        start_production_server(
            host=args.host, 
            port=args.port, 
            workers=args.workers
        )


if __name__ == "__main__":
    main()
