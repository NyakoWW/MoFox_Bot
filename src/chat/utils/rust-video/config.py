"""
配置管理模块
处理 config.toml 文件的读取和管理
"""

import os
from pathlib import Path
from typing import Dict, Any

try:
    import toml
except ImportError:
    print("⚠️  需要安装 toml: pip install toml")
    # 提供基础配置作为后备
    toml = None

class ConfigManager:
    """配置管理器"""
    
    def __init__(self, config_file: str = "config.toml"):
        self.config_file = Path(config_file)
        self._config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        if toml is None or not self.config_file.exists():
            return self._get_default_config()
        
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return toml.load(f)
        except Exception as e:
            print(f"⚠️  配置文件读取失败: {e}")
            return self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """默认配置"""
        return {
            "server": {
                "host": "0.0.0.0",
                "port": 8000,
                "workers": 1,
                "reload": False,
                "log_level": "info"
            },
            "api": {
                "title": "Video Keyframe Extraction API",
                "description": "高性能视频关键帧提取服务",
                "version": "1.0.0",
                "max_file_size": "100MB"
            },
            "processing": {
                "default_threshold": 0.3,
                "default_output_format": "png",
                "max_frames": 10000,
                "temp_dir": "temp",
                "upload_dir": "uploads",
                "output_dir": "outputs"
            },
            "rust": {
                "executable_name": "video_keyframe_extractor",
                "executable_path": "target/release"
            },
            "ffmpeg": {
                "auto_detect": True,
                "custom_path": "",
                "timeout": 300
            },
            "storage": {
                "cleanup_interval": 3600,
                "max_storage_size": "10GB",
                "result_retention_days": 7
            },
            "monitoring": {
                "enable_metrics": True,
                "enable_logging": True,
                "log_file": "logs/api.log",
                "max_log_size": "100MB"
            },
            "security": {
                "allowed_origins": ["*"],
                "max_concurrent_tasks": 10,
                "rate_limit_per_minute": 60
            },
            "development": {
                "debug": False,
                "auto_reload": False,
                "cors_enabled": True
            }
        }
    
    def get(self, section: str, key: str = None, default=None):
        """获取配置值"""
        if key is None:
            return self._config.get(section, default)
        return self._config.get(section, {}).get(key, default)
    
    def get_server_config(self):
        """获取服务器配置"""
        return self.get("server")
    
    def get_api_config(self):
        """获取API配置"""
        return self.get("api")
    
    def get_processing_config(self):
        """获取处理配置"""
        return self.get("processing")
    
    def reload(self):
        """重新加载配置"""
        self._config = self._load_config()

# 全局配置实例
config = ConfigManager()
