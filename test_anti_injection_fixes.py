#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试修复后的反注入系统
验证MessageRecv属性访问和ProcessingStats
"""

import asyncio
import sys
import os
from dataclasses import asdict

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.common.logger import get_logger

logger = get_logger("test_fixes")

async def test_processing_stats():
    """测试ProcessingStats类"""
    print("=== ProcessingStats 测试 ===")
    
    try:
        from src.chat.antipromptinjector.config import ProcessingStats
        
        stats = ProcessingStats()
        
        # 测试所有属性是否存在
        required_attrs = [
            'total_messages', 'detected_injections', 'blocked_messages', 
            'shielded_messages', 'error_count', 'total_process_time', 'last_process_time'
        ]
        
        for attr in required_attrs:
            if hasattr(stats, attr):
                print(f"✅ 属性 {attr}: {getattr(stats, attr)}")
            else:
                print(f"❌ 缺少属性: {attr}")
                return False
        
        # 测试属性操作
        stats.total_messages += 1
        stats.error_count += 1
        stats.total_process_time += 0.5
        
        print(f"✅ 属性操作成功: messages={stats.total_messages}, errors={stats.error_count}")
        return True
        
    except Exception as e:
        print(f"❌ ProcessingStats测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_message_recv_structure():
    """测试MessageRecv结构访问"""
    print("\n=== MessageRecv 结构测试 ===")
    
    try:
        # 创建一个模拟的消息字典
        mock_message_dict = {
            "message_info": {
                "user_info": {
                    "user_id": "test_user_123",
                    "user_nickname": "测试用户",
                    "user_cardname": "测试用户"
                },
                "group_info": None,
                "platform": "qq",
                "time_stamp": 1234567890
            },
            "message_segment": {},
            "raw_message": "测试消息",
            "processed_plain_text": "测试消息"
        }
        
        from src.chat.message_receive.message import MessageRecv
        
        message = MessageRecv(mock_message_dict)
        
        # 测试user_id访问路径
        user_id = message.message_info.user_info.user_id
        print(f"✅ 成功访问 user_id: {user_id}")
        
        # 测试其他常用属性
        user_nickname = message.message_info.user_info.user_nickname
        print(f"✅ 成功访问 user_nickname: {user_nickname}")
        
        processed_text = message.processed_plain_text
        print(f"✅ 成功访问 processed_plain_text: {processed_text}")
        
        return True
        
    except Exception as e:
        print(f"❌ MessageRecv结构测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_anti_injector_initialization():
    """测试反注入器初始化"""
    print("\n=== 反注入器初始化测试 ===")
    
    try:
        from src.chat.antipromptinjector import get_anti_injector, initialize_anti_injector
        from src.chat.antipromptinjector.config import AntiInjectorConfig
        
        # 创建测试配置
        config = AntiInjectorConfig(
            enabled=True,
            auto_ban_enabled=False  # 避免数据库依赖
        )
        
        # 初始化反注入器
        initialize_anti_injector(config)
        anti_injector = get_anti_injector()
        
        # 检查stats对象
        if hasattr(anti_injector, 'stats'):
            stats = anti_injector.stats
            print(f"✅ 反注入器stats初始化成功: {type(stats).__name__}")
            
            # 测试stats属性
            print(f"   total_messages: {stats.total_messages}")
            print(f"   error_count: {stats.error_count}")
            
        else:
            print("❌ 反注入器缺少stats属性")
            return False
        
        return True
        
    except Exception as e:
        print(f"❌ 反注入器初始化测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """主测试函数"""
    print("开始测试修复后的反注入系统...")
    
    tests = [
        test_processing_stats,
        test_message_recv_structure,
        test_anti_injector_initialization
    ]
    
    results = []
    for test in tests:
        try:
            result = await test()
            results.append(result)
        except Exception as e:
            print(f"测试 {test.__name__} 异常: {e}")
            results.append(False)
    
    # 统计结果
    passed = sum(results)
    total = len(results)
    
    print(f"\n=== 测试结果汇总 ===")
    print(f"通过: {passed}/{total}")
    print(f"成功率: {passed/total*100:.1f}%")
    
    if passed == total:
        print("🎉 所有测试通过！修复成功！")
    else:
        print("⚠️ 部分测试未通过，需要进一步检查")
    
    return passed == total

if __name__ == "__main__":
    asyncio.run(main())
