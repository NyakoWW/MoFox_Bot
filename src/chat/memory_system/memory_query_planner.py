# -*- coding: utf-8 -*-
"""记忆检索查询规划器"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import orjson

from src.chat.memory_system.memory_chunk import MemoryType
from src.common.logger import get_logger
from src.llm_models.utils_model import LLMRequest

logger = get_logger(__name__)


@dataclass
class MemoryQueryPlan:
    """查询规划结果"""

    semantic_query: str
    memory_types: List[MemoryType] = field(default_factory=list)
    subject_includes: List[str] = field(default_factory=list)
    object_includes: List[str] = field(default_factory=list)
    required_keywords: List[str] = field(default_factory=list)
    optional_keywords: List[str] = field(default_factory=list)
    owner_filters: List[str] = field(default_factory=list)
    recency_preference: str = "any"
    limit: int = 10
    emphasis: Optional[str] = None
    raw_plan: Dict[str, Any] = field(default_factory=dict)

    def ensure_defaults(self, fallback_query: str, default_limit: int) -> None:
        if not self.semantic_query:
            self.semantic_query = fallback_query
        if self.limit <= 0:
            self.limit = default_limit
        self.recency_preference = (self.recency_preference or "any").lower()
        if self.recency_preference not in {"any", "recent", "historical"}:
            self.recency_preference = "any"
        self.emphasis = (self.emphasis or "balanced").lower()


class MemoryQueryPlanner:
    """基于小模型的记忆检索查询规划器"""

    def __init__(self, planner_model: Optional[LLMRequest], default_limit: int = 10):
        self.model = planner_model
        self.default_limit = default_limit

    async def plan_query(self, query_text: str, context: Dict[str, Any]) -> MemoryQueryPlan:
        if not self.model:
            logger.debug("未提供查询规划模型，使用默认规划")
            return self._default_plan(query_text)

        prompt = self._build_prompt(query_text, context)

        try:
            response, _ = await self.model.generate_response_async(prompt, temperature=0.2)
            payload = self._extract_json_payload(response)
            if not payload:
                logger.debug("查询规划模型未返回结构化结果，使用默认规划")
                return self._default_plan(query_text)

            try:
                data = orjson.loads(payload)
            except orjson.JSONDecodeError as exc:
                preview = payload[:200]
                logger.warning("解析查询规划JSON失败: %s，片段: %s", exc, preview)
                return self._default_plan(query_text)

            plan = self._parse_plan_dict(data, query_text)
            plan.ensure_defaults(query_text, self.default_limit)
            return plan

        except Exception as exc:
            logger.error("查询规划模型调用失败: %s", exc, exc_info=True)
            return self._default_plan(query_text)

    def _default_plan(self, query_text: str) -> MemoryQueryPlan:
        return MemoryQueryPlan(
            semantic_query=query_text,
            limit=self.default_limit
        )

    def _parse_plan_dict(self, data: Dict[str, Any], fallback_query: str) -> MemoryQueryPlan:
        semantic_query = self._safe_str(data.get("semantic_query")) or fallback_query

        def _collect_list(key: str) -> List[str]:
            value = data.get(key)
            if isinstance(value, str):
                return [value]
            if isinstance(value, list):
                return [self._safe_str(item) for item in value if self._safe_str(item)]
            return []

        memory_type_values = _collect_list("memory_types")
        memory_types: List[MemoryType] = []
        for item in memory_type_values:
            if not item:
                continue
            try:
                memory_types.append(MemoryType(item))
            except ValueError:
                # 尝试匹配value值
                normalized = item.lower()
                for mt in MemoryType:
                    if mt.value == normalized:
                        memory_types.append(mt)
                        break

        plan = MemoryQueryPlan(
            semantic_query=semantic_query,
            memory_types=memory_types,
            subject_includes=_collect_list("subject_includes"),
            object_includes=_collect_list("object_includes"),
            required_keywords=_collect_list("required_keywords"),
            optional_keywords=_collect_list("optional_keywords"),
            owner_filters=_collect_list("owner_filters"),
            recency_preference=self._safe_str(data.get("recency")) or "any",
            limit=self._safe_int(data.get("limit"), self.default_limit),
            emphasis=self._safe_str(data.get("emphasis")) or "balanced",
            raw_plan=data
        )
        return plan

    def _build_prompt(self, query_text: str, context: Dict[str, Any]) -> str:
        participants = context.get("participants") or context.get("speaker_names") or []
        if isinstance(participants, str):
            participants = [participants]
        participants = [p for p in participants if isinstance(p, str) and p.strip()]
        participant_preview = "、".join(participants[:5]) or "未知"

        persona = context.get("bot_personality") or context.get("bot_identity") or "未知"

        # 构建未读消息上下文信息
        context_section = ""
        if context.get("has_unread_context") and context.get("unread_messages_context"):
            unread_context = context["unread_messages_context"]
            unread_messages = unread_context.get("messages", [])
            unread_keywords = unread_context.get("keywords", [])
            unread_participants = unread_context.get("participants", [])
            context_summary = unread_context.get("context_summary", "")

            if unread_messages:
                # 构建未读消息摘要
                message_previews = []
                for msg in unread_messages[:5]:  # 最多显示5条
                    sender = msg.get("sender", "未知")
                    content = msg.get("content", "")[:100]  # 限制每条消息长度
                    message_previews.append(f"{sender}: {content}")

                context_section = f"""

## 📋 未读消息上下文 (共{unread_context.get('total_count', 0)}条未读消息)
### 最近消息预览:
{chr(10).join(message_previews)}

### 上下文关键词:
{', '.join(unread_keywords[:15]) if unread_keywords else '无'}

### 对话参与者:
{', '.join(unread_participants) if unread_participants else '无'}

### 上下文摘要:
{context_summary[:300] if context_summary else '无'}
"""
        else:
            context_section = """

## 📋 未读消息上下文:
无未读消息或上下文信息不可用
"""

        return f"""
你是一名记忆检索规划助手，请基于输入生成一个简洁的 JSON 检索计划。
你的任务是分析当前查询并结合未读消息的上下文，生成更精准的记忆检索策略。

仅需提供以下字段：
- semantic_query: 用于向量召回的自然语言描述，要求具体且贴合当前查询和上下文；
- memory_types: 建议检索的记忆类型列表，取值范围来自 MemoryType 枚举 (personal_fact,event,preference,opinion,relationship,emotion,knowledge,skill,goal,experience,contextual)；
- subject_includes: 建议出现在记忆主语中的人物或角色；
- object_includes: 建议关注的对象、主题或关键信息；
- required_keywords: 建议必须包含的关键词（从上下文中提取）；
- recency: 推荐的时间偏好，可选 recent/any/historical；
- limit: 推荐的最大返回数量 (1-15)；
- emphasis: 检索重点，可选 balanced/contextual/recent/comprehensive。

请不要生成谓语字段，也不要额外补充其它参数。

## 当前查询:
"{query_text}"

## 已知对话参与者:
{participant_preview}

## 机器人设定:
{persona}{context_section}

## 🎯 指导原则:
1. **上下文关联**: 优先分析与当前查询相关的未读消息内容和关键词
2. **语义理解**: 结合上下文理解查询的真实意图，而非字面意思
3. **参与者感知**: 考虑未读消息中的参与者，检索与他们相关的记忆
4. **主题延续**: 关注未读消息中讨论的主题，检索相关的历史记忆
5. **时间相关性**: 如果未读消息讨论最近的事件，偏向检索相关时期的记忆

请直接输出符合要求的 JSON 对象，禁止添加额外文本或 Markdown 代码块。
"""

    def _extract_json_payload(self, response: str) -> Optional[str]:
        if not response:
            return None

        stripped = response.strip()
        code_block_match = re.search(r"```(?:json)?\s*(.*?)```", stripped, re.IGNORECASE | re.DOTALL)
        if code_block_match:
            candidate = code_block_match.group(1).strip()
            if candidate:
                return candidate

        start = stripped.find("{")
        end = stripped.rfind("}")
        if start != -1 and end != -1 and end > start:
            return stripped[start:end + 1]

        return stripped if stripped.startswith("{") and stripped.endswith("}") else None

    @staticmethod
    def _safe_str(value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        if value is None:
            return ""
        return str(value).strip()

    @staticmethod
    def _safe_int(value: Any, default: int) -> int:
        try:
            number = int(value)
            if number <= 0:
                return default
            return number
        except (TypeError, ValueError):
            return default