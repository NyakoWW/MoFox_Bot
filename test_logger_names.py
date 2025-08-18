#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试反注入系统logger配置
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.common.logger import get_logger

def test_logger_names():
    """测试不同logger名称的显示"""
    print("=== Logger名称测试 ===")
    
    # 测试不同的logger
    loggers = {
        "chat": "聊天相关",
        "anti_injector": "反注入主模块", 
        "anti_injector.detector": "反注入检测器",
        "anti_injector.shield": "反注入加盾器"
    }
    
    for logger_name, description in loggers.items():
        logger = get_logger(logger_name)
        logger.info(f"这是来自 {description} 的测试消息")
    
    print("测试完成，请查看上方日志输出的标签")

if __name__ == "__main__":
    test_logger_names()
