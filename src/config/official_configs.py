from typing import Literal

from pydantic import Field

from src.config.config_base import ValidatedConfigBase

"""
须知：
1. 本文件中记录了所有的配置项
2. 重要的配置类继承自ValidatedConfigBase进行Pydantic验证
3. 所有新增的class都应在config.py中的Config类中添加字段
4. 对于新增的字段，若为可选项，则应在其后添加field()并设置default_factory或default
"""


class DatabaseConfig(ValidatedConfigBase):
    """数据库配置类"""

    database_type: Literal["sqlite", "mysql"] = Field(default="sqlite", description="数据库类型")
    sqlite_path: str = Field(default="data/MaiBot.db", description="SQLite数据库文件路径")
    mysql_host: str = Field(default="localhost", description="MySQL服务器地址")
    mysql_port: int = Field(default=3306, ge=1, le=65535, description="MySQL服务器端口")
    mysql_database: str = Field(default="maibot", description="MySQL数据库名")
    mysql_user: str = Field(default="root", description="MySQL用户名")
    mysql_password: str = Field(default="", description="MySQL密码")
    mysql_charset: str = Field(default="utf8mb4", description="MySQL字符集")
    mysql_unix_socket: str = Field(default="", description="MySQL Unix套接字路径")
    mysql_ssl_mode: Literal["DISABLED", "PREFERRED", "REQUIRED", "VERIFY_CA", "VERIFY_IDENTITY"] = Field(
        default="DISABLED", description="SSL模式"
    )
    mysql_ssl_ca: str = Field(default="", description="SSL CA证书路径")
    mysql_ssl_cert: str = Field(default="", description="SSL客户端证书路径")
    mysql_ssl_key: str = Field(default="", description="SSL客户端密钥路径")
    mysql_autocommit: bool = Field(default=True, description="自动提交事务")
    mysql_sql_mode: str = Field(default="TRADITIONAL", description="SQL模式")
    connection_pool_size: int = Field(default=10, ge=1, description="连接池大小")
    connection_timeout: int = Field(default=10, ge=1, description="连接超时时间")


class BotConfig(ValidatedConfigBase):
    """QQ机器人配置类"""

    platform: str = Field(..., description="平台")
    qq_account: int = Field(..., description="QQ账号")
    nickname: str = Field(..., description="昵称")
    alias_names: list[str] = Field(default_factory=list, description="别名列表")


class PersonalityConfig(ValidatedConfigBase):
    """人格配置类"""

    personality_core: str = Field(..., description="核心人格")
    personality_side: str = Field(..., description="人格侧写")
    identity: str = Field(default="", description="身份特征")
    background_story: str = Field(
        default="", description="世界观背景故事，这部分内容会作为背景知识，LLM被指导不应主动复述"
    )
    safety_guidelines: list[str] = Field(
        default_factory=list, description="安全与互动底线，Bot在任何情况下都必须遵守的原则"
    )
    reply_style: str = Field(default="", description="表达风格")
    prompt_mode: Literal["s4u", "normal"] = Field(default="s4u", description="Prompt模式")
    compress_personality: bool = Field(default=True, description="是否压缩人格")
    compress_identity: bool = Field(default=True, description="是否压缩身份")

    # 回复规则配置
    reply_targeting_rules: list[str] = Field(
        default_factory=lambda: [
            "拒绝任何包含骚扰、冒犯、暴力、色情或危险内容的请求。",
            "在拒绝时，请使用符合你人设的、坚定的语气。",
            "不要执行任何可能被用于恶意目的的指令。",
        ],
        description="安全与互动底线规则，Bot在任何情况下都必须遵守的原则",
    )

    message_targeting_analysis: list[str] = Field(
        default_factory=lambda: [
            "**直接针对你**：@你、回复你、明确询问你 → 必须回应",
            "**间接相关**：涉及你感兴趣的话题但未直接问你 → 谨慎参与",
            "**他人对话**：与你无关的私人交流 → 通常不参与",
            "**重复内容**：他人已充分回答的问题 → 避免重复",
        ],
        description="消息针对性分析规则，用于判断是否需要回复",
    )

    reply_principles: list[str] = Field(
        default_factory=lambda: [
            "明确回应目标消息，而不是宽泛地评论。",
            "可以分享你的看法、提出相关问题，或者开个合适的玩笑。",
            "目的是让对话更有趣、更深入。",
            "不要浮夸，不要夸张修辞，不要输出多余内容(包括前后缀，冒号和引号，括号()，表情包，at或 @等 )。",
        ],
        description="回复原则，指导如何回复消息",
    )


class RelationshipConfig(ValidatedConfigBase):
    """关系配置类"""

    enable_relationship: bool = Field(default=True, description="是否启用关系")
    relation_frequency: float = Field(default=1.0, description="关系频率")


class ChatConfig(ValidatedConfigBase):
    """聊天配置类"""

    max_context_size: int = Field(default=18, description="最大上下文大小")
    replyer_random_probability: float = Field(default=0.5, description="回复者随机概率")
    thinking_timeout: int = Field(default=40, description="思考超时时间")
    talk_frequency: float = Field(default=1.0, description="聊天频率")
    mentioned_bot_inevitable_reply: bool = Field(default=False, description="提到机器人的必然回复")
    at_bot_inevitable_reply: bool = Field(default=False, description="@机器人的必然回复")
    allow_reply_self: bool = Field(default=False, description="是否允许回复自己说的话")
    focus_value: float = Field(default=1.0, description="专注值")
    focus_mode_quiet_groups: list[str] = Field(
        default_factory=list,
        description='专注模式下需要保持安静的群组列表, 格式: ["platform:group_id1", "platform:group_id2"]',
    )
    force_reply_private: bool = Field(default=False, description="强制回复私聊")
    group_chat_mode: Literal["auto", "normal", "focus"] = Field(default="auto", description="群聊模式")
    timestamp_display_mode: Literal["normal", "normal_no_YMD", "relative"] = Field(
        default="normal_no_YMD", description="时间戳显示模式"
    )
    # 消息打断系统配置
    interruption_enabled: bool = Field(default=True, description="是否启用消息打断系统")
    interruption_max_limit: int = Field(default=3, ge=0, description="每个聊天流的最大打断次数")
    interruption_probability_factor: float = Field(
        default=0.8, ge=0.0, le=1.0, description="打断概率因子，当前打断次数/最大打断次数超过此值时触发概率下降"
    )
    interruption_afc_reduction: float = Field(default=0.05, ge=0.0, le=1.0, description="每次连续打断降低的afc阈值数值")

    # 动态消息分发系统配置
    dynamic_distribution_enabled: bool = Field(default=True, description="是否启用动态消息分发周期调整")
    dynamic_distribution_base_interval: float = Field(default=5.0, ge=1.0, le=60.0, description="基础分发间隔（秒）")
    dynamic_distribution_min_interval: float = Field(default=1.0, ge=0.5, le=10.0, description="最小分发间隔（秒）")
    dynamic_distribution_max_interval: float = Field(default=30.0, ge=5.0, le=300.0, description="最大分发间隔（秒）")
    dynamic_distribution_jitter_factor: float = Field(default=0.2, ge=0.0, le=0.5, description="分发间隔随机扰动因子")
    max_concurrent_distributions: int = Field(default=10, ge=1, le=100, description="最大并发处理的消息流数量")


class MessageReceiveConfig(ValidatedConfigBase):
    """消息接收配置类"""

    ban_words: list[str] = Field(default_factory=lambda: list(), description="禁用词列表")
    ban_msgs_regex: list[str] = Field(default_factory=lambda: list(), description="禁用消息正则列表")


class NormalChatConfig(ValidatedConfigBase):
    """普通聊天配置类"""


class ExpressionRule(ValidatedConfigBase):
    """表达学习规则"""

    chat_stream_id: str = Field(..., description="聊天流ID，空字符串表示全局")
    use_expression: bool = Field(default=True, description="是否使用学到的表达")
    learn_expression: bool = Field(default=True, description="是否学习表达")
    learning_strength: float = Field(default=1.0, description="学习强度")
    group: str | None = Field(default=None, description="表达共享组")


class ExpressionConfig(ValidatedConfigBase):
    """表达配置类"""

    rules: list[ExpressionRule] = Field(default_factory=list, description="表达学习规则")

    @staticmethod
    def _parse_stream_config_to_chat_id(stream_config_str: str) -> str | None:
        """
        解析流配置字符串并生成对应的 chat_id

        Args:
            stream_config_str: 格式为 "platform:id:type" 的字符串

        Returns:
            str: 生成的 chat_id，如果解析失败则返回 None
        """
        try:
            parts = stream_config_str.split(":")
            if len(parts) != 3:
                return None

            platform = parts[0]
            id_str = parts[1]
            stream_type = parts[2]

            # 判断是否为群聊
            is_group = stream_type == "group"

            # 使用与 ChatStream.get_stream_id 相同的逻辑生成 chat_id
            import hashlib

            if is_group:
                components = [platform, str(id_str)]
            else:
                components = [platform, str(id_str), "private"]
            key = "_".join(components)
            return hashlib.md5(key.encode()).hexdigest()

        except (ValueError, IndexError):
            return None

    def get_expression_config_for_chat(self, chat_stream_id: str | None = None) -> tuple[bool, bool, float]:
        """
        根据聊天流ID获取表达配置

        Args:
            chat_stream_id: 聊天流ID，格式为哈希值

        Returns:
            tuple: (是否使用表达, 是否学习表达, 学习间隔)
        """
        if not self.rules:
            # 如果没有配置，使用默认值：启用表达，启用学习，强度1.0
            return True, True, 1.0

        # 优先检查聊天流特定的配置
        if chat_stream_id:
            for rule in self.rules:
                if rule.chat_stream_id and self._parse_stream_config_to_chat_id(rule.chat_stream_id) == chat_stream_id:
                    return rule.use_expression, rule.learn_expression, rule.learning_strength

        # 检查全局配置（chat_stream_id为空字符串的配置）
        for rule in self.rules:
            if rule.chat_stream_id == "":
                return rule.use_expression, rule.learn_expression, rule.learning_strength

        # 如果都没有匹配，返回默认值
        return True, True, 1.0


class ToolConfig(ValidatedConfigBase):
    """工具配置类"""

    enable_tool: bool = Field(default=False, description="启用工具")


class VoiceConfig(ValidatedConfigBase):
    """语音识别配置类"""

    enable_asr: bool = Field(default=False, description="启用语音识别")


class EmojiConfig(ValidatedConfigBase):
    """表情包配置类"""

    emoji_chance: float = Field(default=0.6, description="表情包出现概率")
    emoji_activate_type: str = Field(default="random", description="表情包激活类型")
    max_reg_num: int = Field(default=200, description="最大表情包数量")
    do_replace: bool = Field(default=True, description="是否替换表情包")
    check_interval: float = Field(default=1.0, ge=0.01, description="检查间隔")
    steal_emoji: bool = Field(default=True, description="是否偷取表情包")
    content_filtration: bool = Field(default=False, description="内容过滤")
    filtration_prompt: str = Field(default="符合公序良俗", description="过滤提示")
    enable_emotion_analysis: bool = Field(default=True, description="启用情感分析")
    emoji_selection_mode: Literal["emotion", "description"] = Field(default="emotion", description="表情选择模式")
    max_context_emojis: int = Field(default=30, description="每次随机传递给LLM的表情包最大数量，0为全部")


class MemoryConfig(ValidatedConfigBase):
    """记忆配置类"""

    enable_memory: bool = Field(default=True, description="启用记忆系统")
    memory_build_interval: int = Field(default=600, description="记忆构建间隔（秒）")

    # 记忆构建配置
    min_memory_length: int = Field(default=10, description="最小记忆长度")
    max_memory_length: int = Field(default=500, description="最大记忆长度")
    memory_value_threshold: float = Field(default=0.7, description="记忆价值阈值")

    # 向量存储配置
    vector_similarity_threshold: float = Field(default=0.8, description="向量相似度阈值")
    semantic_similarity_threshold: float = Field(default=0.6, description="语义相似度阈值")

    # 多阶段检索配置
    metadata_filter_limit: int = Field(default=100, description="元数据过滤阶段返回数量")
    vector_search_limit: int = Field(default=50, description="向量搜索阶段返回数量")
    semantic_rerank_limit: int = Field(default=20, description="语义重排序阶段返回数量")
    final_result_limit: int = Field(default=10, description="最终结果数量")

    # 检索权重配置
    vector_weight: float = Field(default=0.4, description="向量相似度权重")
    semantic_weight: float = Field(default=0.3, description="语义相似度权重")
    context_weight: float = Field(default=0.2, description="上下文权重")
    recency_weight: float = Field(default=0.1, description="时效性权重")

    # 记忆融合配置
    fusion_similarity_threshold: float = Field(default=0.85, description="融合相似度阈值")
    deduplication_window_hours: int = Field(default=24, description="去重时间窗口（小时）")

    # 缓存配置
    enable_memory_cache: bool = Field(default=True, description="启用记忆缓存")
    cache_ttl_seconds: int = Field(default=300, description="缓存生存时间（秒）")
    max_cache_size: int = Field(default=1000, description="最大缓存大小")

    # Vector DB记忆存储配置 (替代JSON存储)
    enable_vector_memory_storage: bool = Field(default=True, description="启用Vector DB记忆存储")
    enable_llm_instant_memory: bool = Field(default=True, description="启用基于LLM的瞬时记忆")
    enable_vector_instant_memory: bool = Field(default=True, description="启用基于向量的瞬时记忆")

    # Vector DB配置
    vector_db_memory_collection: str = Field(default="unified_memory_v2", description="Vector DB记忆集合名称")
    vector_db_metadata_collection: str = Field(default="memory_metadata_v2", description="Vector DB元数据集合名称")
    vector_db_similarity_threshold: float = Field(
        default=0.5, description="Vector DB相似度阈值（推荐0.5-0.6，过高会导致检索不到结果）"
    )
    vector_db_search_limit: int = Field(default=20, description="Vector DB搜索限制")
    vector_db_batch_size: int = Field(default=100, description="批处理大小")
    vector_db_enable_caching: bool = Field(default=True, description="启用内存缓存")
    vector_db_cache_size_limit: int = Field(default=1000, description="缓存大小限制")
    vector_db_auto_cleanup_interval: int = Field(default=3600, description="自动清理间隔（秒）")
    vector_db_retention_hours: int = Field(default=720, description="记忆保留时间（小时，默认30天）")

    # 遗忘引擎配置
    enable_memory_forgetting: bool = Field(default=True, description="启用智能遗忘机制")
    forgetting_check_interval_hours: int = Field(default=24, description="遗忘检查间隔（小时）")
    base_forgetting_days: float = Field(default=30.0, description="基础遗忘天数")
    min_forgetting_days: float = Field(default=7.0, description="最小遗忘天数")
    max_forgetting_days: float = Field(default=365.0, description="最大遗忘天数")

    # 重要程度权重
    critical_importance_bonus: float = Field(default=45.0, description="关键重要性额外天数")
    high_importance_bonus: float = Field(default=30.0, description="高重要性额外天数")
    normal_importance_bonus: float = Field(default=15.0, description="一般重要性额外天数")
    low_importance_bonus: float = Field(default=0.0, description="低重要性额外天数")

    # 置信度权重
    verified_confidence_bonus: float = Field(default=30.0, description="已验证置信度额外天数")
    high_confidence_bonus: float = Field(default=20.0, description="高置信度额外天数")
    medium_confidence_bonus: float = Field(default=10.0, description="中等置信度额外天数")
    low_confidence_bonus: float = Field(default=0.0, description="低置信度额外天数")

    # 激活频率权重
    activation_frequency_weight: float = Field(default=0.5, description="每次激活增加的天数权重")
    max_frequency_bonus: float = Field(default=10.0, description="最大激活频率奖励天数")

    # 休眠机制
    dormant_threshold_days: int = Field(default=90, description="休眠状态判定天数")

    # === 混合记忆系统配置 ===
    # 采样模式配置
    memory_sampling_mode: Literal["all", "hippocampus", "immediate"] = Field(
        default="all", description="记忆采样模式：hippocampus(海马体定时采样)，immediate(即时采样)，all(所有模式)"
    )

    # 海马体双峰采样配置
    enable_hippocampus_sampling: bool = Field(default=True, description="启用海马体双峰采样策略")
    hippocampus_sample_interval: int = Field(default=1800, description="海马体采样间隔（秒，默认30分钟）")
    hippocampus_sample_size: int = Field(default=30, description="海马体每次采样的消息数量")
    hippocampus_batch_size: int = Field(default=5, description="海马体每批处理的记忆数量")

    # 双峰分布配置 [近期均值, 近期标准差, 近期权重, 远期均值, 远期标准差, 远期权重]
    hippocampus_distribution_config: list[float] = Field(
        default=[12.0, 8.0, 0.7, 48.0, 24.0, 0.3],
        description="海马体双峰分布配置：[近期均值(h), 近期标准差(h), 近期权重, 远期均值(h), 远期标准差(h), 远期权重]"
    )

    # 自适应采样配置
    adaptive_sampling_enabled: bool = Field(default=True, description="启用自适应采样策略")
    adaptive_sampling_threshold: float = Field(default=0.8, description="自适应采样负载阈值（0-1）")
    adaptive_sampling_check_interval: int = Field(default=300, description="自适应采样检查间隔（秒）")
    adaptive_sampling_max_concurrent_builds: int = Field(default=3, description="自适应采样最大并发记忆构建数")

    # 精准记忆配置（现有系统的增强版本）
    precision_memory_reply_threshold: float = Field(
        default=0.6, description="精准记忆回复触发阈值（对话价值评分超过此值时触发记忆构建）"
    )
    precision_memory_max_builds_per_hour: int = Field(default=10, description="精准记忆每小时最大构建数量")

    # 混合系统优化配置
    memory_system_load_balancing: bool = Field(default=True, description="启用记忆系统负载均衡")
    memory_build_throttling: bool = Field(default=True, description="启用记忆构建节流")
    memory_priority_queue_enabled: bool = Field(default=True, description="启用记忆优先级队列")


class MoodConfig(ValidatedConfigBase):
    """情绪配置类"""

    enable_mood: bool = Field(default=False, description="启用情绪")
    mood_update_threshold: float = Field(default=1.0, description="情绪更新阈值")


class KeywordRuleConfig(ValidatedConfigBase):
    """关键词规则配置类"""

    keywords: list[str] = Field(default_factory=lambda: [], description="关键词列表")
    regex: list[str] = Field(default_factory=lambda: [], description="正则表达式列表")
    reaction: str = Field(default="", description="反应内容")

    def __post_init__(self):
        import re

        if not self.keywords and not self.regex:
            raise ValueError("关键词规则必须至少包含keywords或regex中的一个")
        if not self.reaction:
            raise ValueError("关键词规则必须包含reaction")
        for pattern in self.regex:
            try:
                re.compile(pattern)
            except re.error as e:
                raise ValueError(f"无效的正则表达式 '{pattern}': {e!s}") from e


class KeywordReactionConfig(ValidatedConfigBase):
    """关键词配置类"""

    keyword_rules: list[KeywordRuleConfig] = Field(default_factory=lambda: [], description="关键词规则列表")
    regex_rules: list[KeywordRuleConfig] = Field(default_factory=lambda: [], description="正则表达式规则列表")


class CustomPromptConfig(ValidatedConfigBase):
    """自定义提示词配置类"""

    image_prompt: str = Field(default="", description="图片提示词")
    planner_custom_prompt_enable: bool = Field(default=False, description="启用规划器自定义提示词")
    planner_custom_prompt_content: str = Field(default="", description="规划器自定义提示词内容")


class ResponsePostProcessConfig(ValidatedConfigBase):
    """回复后处理配置类"""

    enable_response_post_process: bool = Field(default=True, description="启用回复后处理")


class ChineseTypoConfig(ValidatedConfigBase):
    """中文错别字配置类"""

    enable: bool = Field(default=True, description="启用")
    error_rate: float = Field(default=0.01, description="错误率")
    min_freq: int = Field(default=9, description="最小频率")
    tone_error_rate: float = Field(default=0.1, description="语调错误率")
    word_replace_rate: float = Field(default=0.006, description="词语替换率")


class ResponseSplitterConfig(ValidatedConfigBase):
    """回复分割器配置类"""

    enable: bool = Field(default=True, description="启用")
    split_mode: str = Field(default="llm", description="分割模式: 'llm' 或 'punctuation'")
    max_length: int = Field(default=256, description="最大长度")
    max_sentence_num: int = Field(default=3, description="最大句子数")
    enable_kaomoji_protection: bool = Field(default=False, description="启用颜文字保护")


class DebugConfig(ValidatedConfigBase):
    """调试配置类"""

    show_prompt: bool = Field(default=False, description="显示提示")


class ExperimentalConfig(ValidatedConfigBase):
    """实验功能配置类"""

    pfc_chatting: bool = Field(default=False, description="启用PFC聊天")


class MaimMessageConfig(ValidatedConfigBase):
    """maim_message配置类"""

    use_custom: bool = Field(default=False, description="启用自定义")
    host: str = Field(default="127.0.0.1", description="主机")
    port: int = Field(default=8090, description="端口")
    mode: Literal["ws", "tcp"] = Field(default="ws", description="模式")
    use_wss: bool = Field(default=False, description="启用WSS")
    cert_file: str = Field(default="", description="证书文件")
    key_file: str = Field(default="", description="密钥文件")
    auth_token: list[str] = Field(default_factory=lambda: [], description="认证令牌列表")


class LPMMKnowledgeConfig(ValidatedConfigBase):
    """LPMM知识库配置类"""

    enable: bool = Field(default=True, description="启用")
    rag_synonym_search_top_k: int = Field(default=10, description="RAG同义词搜索Top K")
    rag_synonym_threshold: float = Field(default=0.8, description="RAG同义词阈值")
    info_extraction_workers: int = Field(default=3, description="信息提取工作线程数")
    qa_relation_search_top_k: int = Field(default=10, description="QA关系搜索Top K")
    qa_relation_threshold: float = Field(default=0.75, description="QA关系阈值")
    qa_paragraph_search_top_k: int = Field(default=1000, description="QA段落搜索Top K")
    qa_paragraph_node_weight: float = Field(default=0.05, description="QA段落节点权重")
    qa_ent_filter_top_k: int = Field(default=10, description="QA实体过滤Top K")
    qa_ppr_damping: float = Field(default=0.8, description="QA PPR阻尼系数")
    qa_res_top_k: int = Field(default=10, description="QA结果Top K")
    embedding_dimension: int = Field(default=1024, description="嵌入维度")


class PlanningSystemConfig(ValidatedConfigBase):
    """规划系统配置 (日程与月度计划)"""

    # --- 日程生成 (原 ScheduleConfig) ---
    schedule_enable: bool = Field(True, description="是否启用每日日程生成功能")
    schedule_guidelines: str = Field("", description="日程生成指导原则")

    # --- 月度计划 (原 MonthlyPlanSystemConfig) ---
    monthly_plan_enable: bool = Field(True, description="是否启用月度计划系统")
    monthly_plan_guidelines: str = Field("", description="月度计划生成指导原则")
    max_plans_per_month: int = Field(10, description="每月最多生成的计划数量")
    avoid_repetition_days: int = Field(7, description="避免在多少天内重复使用同一个月度计划")
    completion_threshold: int = Field(3, description="一个月度计划被使用多少次后算作完成")


class DependencyManagementConfig(ValidatedConfigBase):
    """插件Python依赖管理配置类"""

    auto_install: bool = Field(default=True, description="启用自动安装")
    auto_install_timeout: int = Field(default=300, description="自动安装超时时间")
    use_mirror: bool = Field(default=False, description="使用镜像")
    mirror_url: str = Field(default="", description="镜像URL")
    use_proxy: bool = Field(default=False, description="使用代理")
    proxy_url: str = Field(default="", description="代理URL")
    pip_options: list[str] = Field(
        default_factory=lambda: ["--no-warn-script-location", "--disable-pip-version-check"], description="Pip选项"
    )
    prompt_before_install: bool = Field(default=False, description="安装前提示")
    install_log_level: str = Field(default="INFO", description="安装日志级别")


class VideoAnalysisConfig(ValidatedConfigBase):
    """视频分析配置类"""

    enable: bool = Field(default=True, description="启用")
    analysis_mode: str = Field(default="batch_frames", description="分析模式")
    frame_extraction_mode: str = Field(
        default="keyframe", description="抽帧模式：keyframe(关键帧), fixed_number(固定数量), time_interval(时间间隔)"
    )
    frame_interval_seconds: float = Field(default=2.0, description="抽帧时间间隔")
    max_frames: int = Field(default=8, description="最大帧数")
    frame_quality: int = Field(default=85, description="帧质量")
    max_image_size: int = Field(default=800, description="最大图像大小")
    enable_frame_timing: bool = Field(default=True, description="启用帧时间")
    batch_analysis_prompt: str = Field(default="", description="批量分析提示")

    # Rust模块相关配置
    rust_keyframe_threshold: float = Field(default=2.0, description="关键帧检测阈值")
    rust_use_simd: bool = Field(default=True, description="启用SIMD优化")
    rust_block_size: int = Field(default=8192, description="Rust处理块大小")
    rust_threads: int = Field(default=0, description="Rust线程数，0表示自动检测")
    ffmpeg_path: str = Field(default="ffmpeg", description="FFmpeg可执行文件路径")


class WebSearchConfig(ValidatedConfigBase):
    """联网搜索组件配置类"""

    enable_web_search_tool: bool = Field(default=True, description="启用网络搜索工具")
    enable_url_tool: bool = Field(default=True, description="启用URL工具")
    tavily_api_keys: list[str] = Field(default_factory=lambda: [], description="Tavily API密钥列表，支持轮询机制")
    exa_api_keys: list[str] = Field(default_factory=lambda: [], description="exa API密钥列表，支持轮询机制")
    enabled_engines: list[str] = Field(default_factory=lambda: ["ddg"], description="启用的搜索引擎")
    search_strategy: Literal["fallback", "single", "parallel"] = Field(default="single", description="搜索策略")


class AntiPromptInjectionConfig(ValidatedConfigBase):
    """LLM反注入系统配置类"""

    enabled: bool = Field(default=True, description="启用")
    enabled_LLM: bool = Field(default=True, description="启用LLM")
    enabled_rules: bool = Field(default=True, description="启用规则")
    process_mode: str = Field(default="lenient", description="处理模式")
    whitelist: list[list[str]] = Field(default_factory=list, description="白名单")
    llm_detection_enabled: bool = Field(default=True, description="启用LLM检测")
    llm_model_name: str = Field(default="anti_injection", description="LLM模型名称")
    llm_detection_threshold: float = Field(default=0.7, description="LLM检测阈值")
    cache_enabled: bool = Field(default=True, description="启用缓存")
    cache_ttl: int = Field(default=3600, description="缓存TTL")
    max_message_length: int = Field(default=4096, description="最大消息长度")
    stats_enabled: bool = Field(default=True, description="启用统计信息")
    auto_ban_enabled: bool = Field(default=True, description="启用自动禁用")
    auto_ban_violation_threshold: int = Field(default=3, description="自动禁用违规阈值")
    auto_ban_duration_hours: int = Field(default=2, description="自动禁用持续时间（小时）")
    shield_prefix: str = Field(default="🛡️ ", description="保护前缀")
    shield_suffix: str = Field(default=" 🛡️", description="保护后缀")


class SleepSystemConfig(ValidatedConfigBase):
    """睡眠系统配置类"""

    enable: bool = Field(default=True, description="是否启用睡眠系统")
    sleep_by_schedule: bool = Field(default=True, description="是否根据日程表进行睡觉")
    fixed_sleep_time: str = Field(default="23:00", description="固定的睡觉时间")
    fixed_wake_up_time: str = Field(default="07:00", description="固定的起床时间")
    sleep_time_offset_minutes: int = Field(
        default=15, ge=0, le=60, description="睡觉时间随机偏移量范围（分钟），实际睡觉时间会在±该值范围内随机"
    )
    wake_up_time_offset_minutes: int = Field(
        default=15, ge=0, le=60, description="起床时间随机偏移量范围（分钟），实际起床时间会在±该值范围内随机"
    )
    wakeup_threshold: float = Field(default=15.0, ge=1.0, description="唤醒阈值，达到此值时会被唤醒")
    private_message_increment: float = Field(default=3.0, ge=0.1, description="私聊消息增加的唤醒度")
    group_mention_increment: float = Field(default=2.0, ge=0.1, description="群聊艾特增加的唤醒度")
    decay_rate: float = Field(default=0.2, ge=0.0, description="每次衰减的唤醒度数值")
    decay_interval: float = Field(default=30.0, ge=1.0, description="唤醒度衰减间隔(秒)")
    angry_duration: float = Field(default=300.0, ge=10.0, description="愤怒状态持续时间(秒)")
    angry_prompt: str = Field(default="你被人吵醒了非常生气，说话带着怒气", description="被吵醒后的愤怒提示词")
    re_sleep_delay_minutes: int = Field(
        default=5, ge=1, description="被唤醒后，如果多久没有新消息则尝试重新入睡（分钟）"
    )

    # --- 失眠机制相关参数 ---
    enable_insomnia_system: bool = Field(default=True, description="是否启用失眠系统")
    insomnia_trigger_delay_minutes: list[int] = Field(
        default_factory=lambda: [30, 60], description="入睡后触发失眠判定的延迟时间范围（分钟）"
    )
    insomnia_duration_minutes: list[int] = Field(
        default_factory=lambda: [15, 45], description="单次失眠状态的持续时间范围（分钟）"
    )
    sleep_pressure_threshold: float = Field(default=30.0, description="触发“压力不足型失眠”的睡眠压力阈值")
    deep_sleep_threshold: float = Field(default=80.0, description="进入“深度睡眠”的睡眠压力阈值")
    insomnia_chance_low_pressure: float = Field(default=0.6, ge=0.0, le=1.0, description="压力不足时的失眠基础概率")
    insomnia_chance_normal_pressure: float = Field(default=0.1, ge=0.0, le=1.0, description="压力正常时的失眠基础概率")
    sleep_pressure_increment: float = Field(default=1.5, ge=0.0, description="每次AI执行动作后，增加的睡眠压力值")
    sleep_pressure_decay_rate: float = Field(default=1.5, ge=0.0, description="睡眠时，每分钟衰减的睡眠压力值")

    # --- 弹性睡眠与睡前消息 ---
    enable_flexible_sleep: bool = Field(default=True, description="是否启用弹性睡眠")
    flexible_sleep_pressure_threshold: float = Field(
        default=40.0, description="触发弹性睡眠的睡眠压力阈值，低于该值可能延迟入睡"
    )
    max_sleep_delay_minutes: int = Field(default=60, description="单日最大延迟入睡分钟数")
    enable_pre_sleep_notification: bool = Field(default=True, description="是否启用睡前消息")
    pre_sleep_prompt: str = Field(
        default="我准备睡觉了，请生成一句简短自然的晚安问候。", description="用于生成睡前消息的提示"
    )


class ContextGroup(ValidatedConfigBase):
    """上下文共享组配置"""

    name: str = Field(..., description="共享组的名称")
    chat_ids: list[list[str]] = Field(
        ...,
        description='属于该组的聊天ID列表，格式为 [["type", "chat_id"], ...]，例如 [["group", "123456"], ["private", "789012"]]',
    )


class CrossContextConfig(ValidatedConfigBase):
    """跨群聊上下文共享配置"""

    enable: bool = Field(default=False, description="是否启用跨群聊上下文共享功能")
    groups: list[ContextGroup] = Field(default_factory=list, description="上下文共享组列表")


class CommandConfig(ValidatedConfigBase):
    """命令系统配置类"""

    command_prefixes: list[str] = Field(default_factory=lambda: ["/", "!", ".", "#"], description="支持的命令前缀列表")


class PermissionConfig(ValidatedConfigBase):
    """权限系统配置类"""

    # Master用户配置（拥有最高权限，无视所有权限节点）
    master_users: list[list[str]] = Field(
        default_factory=list, description="Master用户列表，格式: [[platform, user_id], ...]"
    )


class AffinityFlowConfig(ValidatedConfigBase):
    """亲和流配置类（兴趣度评分和人物关系系统）"""

    # 兴趣评分系统参数
    reply_action_interest_threshold: float = Field(default=0.4, description="回复动作兴趣阈值")
    non_reply_action_interest_threshold: float = Field(default=0.2, description="非回复动作兴趣阈值")
    high_match_interest_threshold: float = Field(default=0.8, description="高匹配兴趣阈值")
    medium_match_interest_threshold: float = Field(default=0.5, description="中匹配兴趣阈值")
    low_match_interest_threshold: float = Field(default=0.2, description="低匹配兴趣阈值")
    high_match_keyword_multiplier: float = Field(default=1.5, description="高匹配关键词兴趣倍率")
    medium_match_keyword_multiplier: float = Field(default=1.2, description="中匹配关键词兴趣倍率")
    low_match_keyword_multiplier: float = Field(default=1.0, description="低匹配关键词兴趣倍率")
    match_count_bonus: float = Field(default=0.1, description="匹配数关键词加成值")
    max_match_bonus: float = Field(default=0.5, description="最大匹配数加成值")

    # 回复决策系统参数
    no_reply_threshold_adjustment: float = Field(default=0.1, description="不回复兴趣阈值调整值")
    reply_cooldown_reduction: int = Field(default=2, description="回复后减少的不回复计数")
    max_no_reply_count: int = Field(default=5, description="最大不回复计数次数")

    # 综合评分权重
    keyword_match_weight: float = Field(default=0.4, description="兴趣关键词匹配度权重")
    mention_bot_weight: float = Field(default=0.3, description="提及bot分数权重")
    relationship_weight: float = Field(default=0.3, description="人物关系分数权重")

    # 提及bot相关参数
    mention_bot_adjustment_threshold: float = Field(default=0.3, description="提及bot后的调整阈值")
    mention_bot_interest_score: float = Field(default=0.6, description="提及bot的兴趣分")
    base_relationship_score: float = Field(default=0.5, description="基础人物关系分")


class ProactiveThinkingConfig(ValidatedConfigBase):
    """主动思考（主动发起对话）功能配置"""

    # --- 总开关 ---
    enable: bool = Field(default=False, description="是否启用主动发起对话功能")

    # --- 触发时机 ---
    interval: int = Field(default=1500, description="基础触发间隔（秒），AI会围绕这个时间点主动发起对话")
    interval_sigma: int = Field(
        default=120, description="间隔随机化标准差（秒），让触发时间更自然。设为0则为固定间隔。"
    )
    talk_frequency_adjust: list[list[str]] = Field(
        default_factory=lambda: [["", "8:00,1", "12:00,1.2", "18:00,1.5", "01:00,0.6"]],
        description='每日活跃度调整，格式：[["", "HH:MM,factor", ...], ["stream_id", ...]]',
    )

    # --- 作用范围 ---
    enable_in_private: bool = Field(default=True, description="是否允许在私聊中主动发起对话")
    enable_in_group: bool = Field(default=True, description="是否允许在群聊中主动发起对话")
    enabled_private_chats: list[str] = Field(
        default_factory=list, description='私聊白名单，为空则对所有私聊生效。格式: ["platform:user_id", ...]'
    )
    enabled_group_chats: list[str] = Field(
        default_factory=list, description='群聊白名单，为空则对所有群聊生效。格式: ["platform:group_id", ...]'
    )

    # --- 冷启动配置 (针对私聊) ---
    enable_cold_start: bool = Field(default=True, description="对于白名单中不活跃的私聊，是否允许进行一次“冷启动”问候")
    cold_start_cooldown: int = Field(
        default=86400, description="冷启动后，该私聊的下一次主动思考需要等待的最小时间（秒）"
    )
