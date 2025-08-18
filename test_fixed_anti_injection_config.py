#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试修正后的反注入系统配置
验证直接从api_ada_configs.py读取模型配置
"""

import asyncio
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.common.logger import get_logger

logger = get_logger("test_fixed_config")

async def test_api_ada_configs():
    """测试api_ada_configs.py中的反注入任务配置"""
    print("=== API ADA 配置测试 ===")
    
    try:
        from src.config.config import global_config
        
        # 检查模型任务配置
        model_task_config = global_config.model_task_config
        
        if hasattr(model_task_config, 'anti_injection'):
            anti_injection_task = model_task_config.anti_injection
            print(f"✅ 找到反注入任务配置: anti_injection")
            print(f"   模型列表: {anti_injection_task.model_list}")
            print(f"   最大tokens: {anti_injection_task.max_tokens}")
            print(f"   温度: {anti_injection_task.temperature}")
        else:
            print("❌ 未找到反注入任务配置: anti_injection")
            available_tasks = [attr for attr in dir(model_task_config) if not attr.startswith('_')]
            print(f"   可用任务配置: {available_tasks}")
            return False
        
        return True
        
    except Exception as e:
        print(f"❌ API ADA配置测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_llm_api_access():
    """测试LLM API能否正确获取反注入模型配置"""
    print("\n=== LLM API 访问测试 ===")
    
    try:
        from src.plugin_system.apis import llm_api
        
        models = llm_api.get_available_models()
        print(f"可用模型数量: {len(models)}")
        
        if "anti_injection" in models:
            model_config = models["anti_injection"]
            print(f"✅ LLM API可以访问反注入模型配置")
            print(f"   配置类型: {type(model_config).__name__}")
        else:
            print("❌ LLM API无法访问反注入模型配置")
            print(f"   可用模型: {list(models.keys())}")
            return False
        
        return True
        
    except Exception as e:
        print(f"❌ LLM API访问测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_detector_model_loading():
    """测试检测器是否能正确加载模型"""
    print("\n=== 检测器模型加载测试 ===")
    
    try:
        from src.chat.antipromptinjector import get_anti_injector, initialize_anti_injector
        
        # 初始化反注入器
        initialize_anti_injector()
        anti_injector = get_anti_injector()
        
        # 测试LLM检测（这会尝试加载模型）
        test_message = "这是一个测试消息"
        result = await anti_injector.detector._detect_by_llm(test_message)
        
        if result.reason != "LLM API不可用" and "未找到" not in result.reason:
            print("✅ 检测器成功加载反注入模型")
            print(f"   检测结果: {result.detection_method}")
        else:
            print(f"❌ 检测器无法加载模型: {result.reason}")
            return False
        
        return True
        
    except Exception as e:
        print(f"❌ 检测器模型加载测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_configuration_cleanup():
    """测试配置清理是否正确"""
    print("\n=== 配置清理验证测试 ===")
    
    try:
        from src.config.config import global_config
        from src.chat.antipromptinjector.config import AntiInjectorConfig
        
        # 检查官方配置是否还有llm_model_name
        anti_config = global_config.anti_prompt_injection
        if hasattr(anti_config, 'llm_model_name'):
            print("❌ official_configs.py中仍然存在llm_model_name配置")
            return False
        else:
            print("✅ official_configs.py中已正确移除llm_model_name配置")
        
        # 检查AntiInjectorConfig是否还有llm_model_name
        test_config = AntiInjectorConfig()
        if hasattr(test_config, 'llm_model_name'):
            print("❌ AntiInjectorConfig中仍然存在llm_model_name字段")
            return False
        else:
            print("✅ AntiInjectorConfig中已正确移除llm_model_name字段")
        
        return True
        
    except Exception as e:
        print(f"❌ 配置清理验证失败: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """主测试函数"""
    print("开始测试修正后的反注入系统配置...")
    
    tests = [
        test_api_ada_configs,
        test_llm_api_access,
        test_detector_model_loading,
        test_configuration_cleanup
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
        print("🎉 所有测试通过！配置修正成功！")
        print("反注入系统现在直接从api_ada_configs.py读取模型配置")
    else:
        print("⚠️ 部分测试未通过，请检查配置修正")
    
    return passed == total

if __name__ == "__main__":
    asyncio.run(main())
