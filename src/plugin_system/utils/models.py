"""这是一个示例的插件清单文件。
{
  "manifest_version": 1,
  "format_version": "1.0.0",
  "name": "插件名称",
  "description": "插件描述",
  "version": "1.0.0",
  "author": {
    "name": "作者名称"
  },
  "license": "MIT",
  "keywords": ["关键词1", "关键词2"],
  "categories": ["分类1", "分类2"],
  "host_application": {
    "name": "MaiBot",
    "min_version": "0.10.0"
  },
  "entry_points": {
    "main": "plugin.py"
  },
  "plugin_info": {
    "is_built_in": false,
    "plugin_type": "类型",
    "components": [
      {
        "type": "组件类型",
        "name": "组件名称",
        "description": "组件描述"
      }
    ],
    "features": [
      "特性1",
      "特性2"
    ]
  }
}
"""

from __future__ import annotations

from pydantic import BaseModel


class ManifestPluginInfoComponent(BaseModel):
    type: str
    name: str
    description: str


class ManifestPluginInfo(BaseModel):
    is_built_in: bool = False
    plugin_type: str = "general"
    components: list[ManifestPluginInfoComponent] = []
    features: list[str] = []


class ManifestAuthor(BaseModel):
    name: str


class Manifest(BaseModel):
    name: str
    description: str
    version: str
    format_version: str = "1.0.0"
    manifest_version: int
    author: ManifestAuthor
    license: str = "MIT"
    keywords: list[str] = []
    categories: list[str] = []
    host_application: dict[str, str] = {"name": "MaiBot", "min_version": "0.10.0"}
    entry_points: dict[str, str] = {"main": "plugin.py"}
