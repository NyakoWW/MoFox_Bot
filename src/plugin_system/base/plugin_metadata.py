from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

@dataclass
class PluginMetadata:
    """
    插件元数据，用于存储插件的开发者信息和用户帮助信息。
    """
    name: str  # 插件名称 (供用户查看)
    description: str  # 插件功能描述
    usage: str  # 插件使用方法

    # 以下为可选字段，参考自 _manifest.json 和 NoneBot 设计
    type: Optional[str] = None  # 插件类别: "library", "application"

    # 从原 _manifest.json 迁移的字段
    version: str = "1.0.0"  # 插件版本
    author: str = ""  # 作者名称
    license: Optional[str] = None  # 开源协议
    repository_url: Optional[str] = None  # 仓库地址
    keywords: List[str] = field(default_factory=list)  # 关键词
    categories: List[str] = field(default_factory=list)  # 分类

    # 扩展字段
    extra: Dict[str, Any] = field(default_factory=dict)  # 其他任意信息