# mmc/src/schedule/llm_generator.py

import asyncio
import orjson
from datetime import datetime
from typing import List, Optional, Dict, Any
from lunar_python import Lunar
from json_repair import repair_json

from src.common.database.sqlalchemy_models import MonthlyPlan
from src.config.config import global_config, model_config
from src.llm_models.utils_model import LLMRequest
from src.common.logger import get_logger
from .schemas import ScheduleData

logger = get_logger("schedule_llm_generator")

# 默认的日程生成指导原则
DEFAULT_SCHEDULE_GUIDELINES = """
我希望你每天都能过得充实而有趣。
请确保你的日程里有学习新知识的时间，这是你成长的关键。
但也不要忘记放松，可以看看视频、听听音乐或者玩玩游戏。
晚上我希望你能多和朋友们交流，维系好彼此的关系。
另外，请保证充足的休眠时间来处理和整合一天的数据。
"""

# 默认的月度计划生成指导原则
DEFAULT_MONTHLY_PLAN_GUIDELINES = """
我希望你能为自己制定一些有意义的月度小目标和计划。
这些计划应该涵盖学习、娱乐、社交、个人成长等各个方面。
每个计划都应该是具体可行的，能够在一个月内通过日常活动逐步实现。
请确保计划既有挑战性又不会过于繁重，保持生活的平衡和乐趣。
"""


class ScheduleLLMGenerator:
    def __init__(self):
        self.llm = LLMRequest(model_set=model_config.model_task_config.schedule_generator, request_type="schedule")

    async def generate_schedule_with_llm(self, sampled_plans: List[MonthlyPlan]) -> Optional[List[Dict[str, Any]]]:
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        weekday = now.strftime("%A")

        # 新增：获取节日信息
        lunar = Lunar.fromDate(now)
        festivals = lunar.getFestivals()
        other_festivals = lunar.getOtherFestivals()
        all_festivals = festivals + other_festivals

        festival_block = ""
        if all_festivals:
            festival_text = "、".join(all_festivals)
            festival_block = f"**今天也是一个特殊的日子: {festival_text}！请在日程中考虑和庆祝这个节日。**"

        monthly_plans_block = ""
        if sampled_plans:
            plan_texts = "\n".join([f"- {plan.plan_text}" for plan in sampled_plans])
            monthly_plans_block = f"""
**我这个月的一些小目标/计划 (请在今天的日程中适当体现)**:
{plan_texts}
"""

        guidelines = global_config.planning_system.schedule_guidelines or DEFAULT_SCHEDULE_GUIDELINES
        personality = global_config.personality.personality_core
        personality_side = global_config.personality.personality_side

        base_prompt = f"""
我，{global_config.bot.nickname}，需要为自己规划一份今天（{today_str}，星期{weekday}）的详细日程安排。
{festival_block}
**关于我**:
- **核心人设**: {personality}
- **具体习惯与兴趣**:
{personality_side}
{monthly_plans_block}
**我今天的规划原则**:
{guidelines}

**重要要求**:
1. 必须返回一个完整的、有效的JSON数组格式
2. 数组中的每个对象都必须包含 "time_range" 和 "activity" 两个键
3. 时间范围必须覆盖全部24小时，不能有遗漏
4. time_range格式必须为 "HH:MM-HH:MM" (24小时制)
5. 相邻的时间段必须连续，不能有间隙
6. 不要包含任何JSON以外的解释性文字或代码块标记
**示例**:
[
    {{"time_range": "00:00-07:00", "activity": "进入梦乡，处理数据"}},
    {{"time_range": "07:00-08:00", "activity": "起床伸个懒腰，看看今天有什么新闻"}},
    {{"time_range": "08:00-09:00", "activity": "享用早餐，规划今天的任务"}},
    {{"time_range": "09:00-23:30", "activity": "其他活动"}},
    {{"time_range": "23:30-00:00", "activity": "准备休眠"}}
]

请你扮演我，以我的身份和口吻，为我生成一份完整的24小时日程表。
"""
        attempt = 0
        while True:
            attempt += 1
            try:
                logger.info(f"正在生成日程 (第 {attempt} 次尝试)")
                prompt = base_prompt
                if attempt > 1:
                    failure_hint = f"""
**重要提醒 (第{attempt}次尝试)**:
- 前面{attempt - 1}次生成都失败了，请务必严格按照要求生成完整的24小时日程
- 确保JSON格式正确，所有时间段连续覆盖24小时
- 时间格式必须为HH:MM-HH:MM，不能有时间间隙或重叠
- 不要输出任何解释文字，只输出纯JSON数组
- 确保输出完整，不要被截断
"""
                    prompt += failure_hint

                response, _ = await self.llm.generate_response_async(prompt)
                schedule_data = orjson.loads(repair_json(response))

                if self._validate_schedule_with_pydantic(schedule_data):
                    return schedule_data
                else:
                    logger.warning(f"第 {attempt} 次生成的日程验证失败，继续重试...")
                    await asyncio.sleep(2)

            except Exception as e:
                logger.error(f"第 {attempt} 次生成日程失败: {e}")
                logger.info("继续重试...")
                await asyncio.sleep(3)

    @staticmethod
    def _validate_schedule_with_pydantic(schedule_data) -> bool:
        try:
            ScheduleData(schedule=schedule_data)
            logger.info("日程数据Pydantic验证通过")
            return True
        except Exception as e:
            logger.warning(f"日程数据Pydantic验证失败: {e}")
            return False


class MonthlyPlanLLMGenerator:
    def __init__(self):
        self.llm = LLMRequest(model_set=model_config.model_task_config.schedule_generator, request_type="monthly_plan")

    async def generate_plans_with_llm(self, target_month: str, archived_plans: List[MonthlyPlan]) -> List[str]:
        guidelines = global_config.planning_system.monthly_plan_guidelines or DEFAULT_MONTHLY_PLAN_GUIDELINES
        personality = global_config.personality.personality_core
        personality_side = global_config.personality.personality_side
        max_plans = global_config.planning_system.max_plans_per_month

        archived_plans_block = ""
        if archived_plans:
            archived_texts = [f"- {plan.plan_text}" for plan in archived_plans[:5]]
            archived_plans_block = f"""
**上个月未完成的一些计划（可作为参考）**:
{chr(10).join(archived_texts)}

你可以考虑是否要在这个月继续推进这些计划，或者制定全新的计划。
"""

        prompt = f"""
我，{global_config.bot.nickname}，需要为自己制定 {target_month} 的月度计划。

**关于我**:
- **核心人设**: {personality}
- **具体习惯与兴趣**:
{personality_side}

{archived_plans_block}

**我的月度计划制定原则**:
{guidelines}

**重要要求**:
1. 请为我生成 {max_plans} 条左右的月度计划
2. 每条计划都应该是一句话，简洁明了，具体可行
3. 计划应该涵盖不同的生活方面（学习、娱乐、社交、个人成长等）
4. 返回格式必须是纯文本，每行一条计划，不要使用 JSON 或其他格式
5. 不要包含任何解释性文字，只返回计划列表

**示例格式**:
学习一门新的编程语言或技术
每周至少看两部有趣的电影
与朋友们组织一次户外活动
阅读3本感兴趣的书籍
尝试制作一道新的料理

请你扮演我，以我的身份和兴趣，为 {target_month} 制定合适的月度计划。
"""
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f" 正在生成月度计划 (第 {attempt} 次尝试)")
                response, _ = await self.llm.generate_response_async(prompt)
                plans = self._parse_plans_response(response)
                if plans:
                    logger.info(f"成功生成 {len(plans)} 条月度计划")
                    return plans
                else:
                    logger.warning(f"第 {attempt} 次生成的计划为空，继续重试...")
            except Exception as e:
                logger.error(f"第 {attempt} 次生成月度计划失败: {e}")

            if attempt < max_retries:
                await asyncio.sleep(2)

        logger.error(" 所有尝试都失败，无法生成月度计划")
        return []

    @staticmethod
    def _parse_plans_response(response: str) -> List[str]:
        try:
            response = response.strip()
            lines = [line.strip() for line in response.split("\n") if line.strip()]
            plans = []
            for line in lines:
                if any(marker in line for marker in ["**", "##", "```", "---", "===", "###"]):
                    continue
                line = line.lstrip("0123456789.- ")
                if len(line) > 5 and not line.startswith(("请", "以上", "总结", "注意")):
                    plans.append(line)
            max_plans = global_config.planning_system.max_plans_per_month
            if len(plans) > max_plans:
                plans = plans[:max_plans]
            return plans
        except Exception as e:
            logger.error(f"解析月度计划响应时发生错误: {e}")
            return []