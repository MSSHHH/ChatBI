"""
会话记忆服务模块。

该模块提供用于存储多轮数据分析对话上下文的结构化内存实现，包含以下核心能力：
1. 解析并标准化自然语言意图工具返回的计划数据；
2. 保存每一轮查询的 SQL、结果快照、简要总结等信息；
3. 生成可供 LLM 复用的上下文提示，确保在多轮对话中实现精准的上下文感知；
4. 线程安全的会话级内存管理器，方便在 FastAPI/异步场景中复用。

设计原则：
- 所有结构均采用 dataclass，便于序列化与类型检查；
- 提供 to_dict()/from_dict() 方法，方便未来扩展持久化能力；
- 内存提示尽量保持简洁，避免向模型输入冗余信息。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import datetime
import json
import threading
import uuid


def _now_utc() -> datetime.datetime:
    """统一的 UTC 时间戳生成函数，便于单元测试注入。"""
    return datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)


# ---------------------------------------------------------------------------
# 分析计划结构定义
# ---------------------------------------------------------------------------


@dataclass
class FilterCondition:
    """筛选条件描述。"""

    field: str
    op: str
    value: Any

    def to_text(self) -> str:
        """生成自然语言描述，便于提示词拼接。"""
        value_repr = json.dumps(self.value, ensure_ascii=False)
        return f"{self.field} {self.op} {value_repr}"


@dataclass
class HavingCondition(FilterCondition):
    """Having 条件与 FilterCondition 结构一致，单独定义方便区分。"""


@dataclass
class AggregationSpec:
    """聚合字段或表达式描述。"""

    agg: Optional[str]
    field: str
    alias: Optional[str] = None

    def to_text(self) -> str:
        if self.agg:
            label = f"{self.agg}({self.field})"
        else:
            label = self.field
        if self.alias:
            label += f" AS {self.alias}"
        return label


@dataclass
class OrderBySpec:
    """排序字段描述。"""

    field: str
    direction: str = "asc"

    def to_text(self) -> str:
        return f"{self.field} {self.direction.upper()}"


@dataclass
class FollowUpDirective:
    """多轮追问时的复用策略描述。"""

    refers_previous: bool = False
    use_last_sql: bool = False
    modify: Optional[str] = None

    def to_text(self) -> str:
        if not self.refers_previous and not self.modify:
            return ""
        pieces: List[str] = []
        if self.refers_previous:
            pieces.append("参考上一轮上下文")
        if self.use_last_sql:
            pieces.append("复用上一轮 SQL")
        if self.modify:
            pieces.append(f"修改点：{self.modify}")
        return "；".join(pieces)


@dataclass
class TimeRange:
    """时间范围描述。"""

    start: Optional[str] = None
    end: Optional[str] = None

    def is_valid(self) -> bool:
        return bool(self.start or self.end)

    def to_text(self) -> str:
        if not self.is_valid():
            return ""
        return f"{self.start or '未知'} ~ {self.end or '未知'}"


@dataclass
class AnalysisPlan:
    """
    结构化的分析计划定义，对应 analyze_nl_intent 工具的输出。

    Notes:
        - select 字段允许混合 str 与 dict（聚合表达式），在标准化过程中统一转换为 AggregationSpec/str。
        - entities 用于提示核心实体，例如“订单”“客户”。
    """

    task: str = "analysis"
    entities: List[str] = field(default_factory=list)
    select: List[AggregationSpec | str] = field(default_factory=list)
    filters: List[FilterCondition] = field(default_factory=list)
    group_by: List[str] = field(default_factory=list)
    having: List[HavingCondition] = field(default_factory=list)
    order_by: List[OrderBySpec] = field(default_factory=list)
    limit: Optional[int] = None
    time_range: Optional[TimeRange] = None
    follow_up: Optional[FollowUpDirective] = None
    explanations: Optional[str] = None
    raw_payload: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # 构造与序列化逻辑
    # ------------------------------------------------------------------
    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "AnalysisPlan":
        """从 analyze_nl_intent 原始返回构造结构化对象。"""
        select_items: List[AggregationSpec | str] = []
        for item in payload.get("select", []) or []:
            if isinstance(item, dict):
                select_items.append(
                    AggregationSpec(
                        agg=item.get("agg"),
                        field=item.get("field", ""),
                        alias=item.get("alias"),
                    )
                )
            else:
                select_items.append(str(item))

        filters = [
            FilterCondition(
                field=str(f.get("field")),
                op=str(f.get("op")),
                value=f.get("value"),
            )
            for f in payload.get("filters", []) or []
            if f.get("field") and f.get("op") is not None
        ]

        having = [
            HavingCondition(
                field=str(f.get("field")),
                op=str(f.get("op")),
                value=f.get("value"),
            )
            for f in payload.get("having", []) or []
            if f.get("field") and f.get("op") is not None
        ]

        order_by = [
            OrderBySpec(
                field=str(item.get("field")),
                direction=str(item.get("direction", "asc")),
            )
            for item in payload.get("order_by", []) or []
            if item.get("field")
        ]

        time_range = None
        if payload.get("time_range"):
            time_range = TimeRange(
                start=payload["time_range"].get("start"),
                end=payload["time_range"].get("end"),
            )

        follow_up = None
        if payload.get("follow_up"):
            follow_up = FollowUpDirective(
                refers_previous=bool(payload["follow_up"].get("refers_previous")),
                use_last_sql=bool(payload["follow_up"].get("use_last_sql")),
                modify=payload["follow_up"].get("modify"),
            )

        return cls(
            task=str(payload.get("task", "analysis")),
            entities=[str(e) for e in payload.get("entities", []) or []],
            select=select_items,
            filters=filters,
            group_by=[str(g) for g in payload.get("group_by", []) or []],
            having=having,
            order_by=order_by,
            limit=payload.get("limit"),
            time_range=time_range,
            follow_up=follow_up,
            explanations=payload.get("explanations"),
            raw_payload=payload,
        )

    def to_payload(self) -> Dict[str, Any]:
        """转换回普通 dict，便于存储。"""
        return {
            "task": self.task,
            "entities": self.entities,
            "select": [
                item.to_text() if isinstance(item, AggregationSpec) else item
                for item in self.select
            ],
            "filters": [vars(f) for f in self.filters],
            "group_by": self.group_by,
            "having": [vars(f) for f in self.having],
            "order_by": [vars(o) for o in self.order_by],
            "limit": self.limit,
            "time_range": vars(self.time_range) if self.time_range else None,
            "follow_up": vars(self.follow_up) if self.follow_up else None,
            "explanations": self.explanations,
        }

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------
    def summarize(self) -> str:
        """为了提示词生成的紧凑文本摘要。"""
        parts: List[str] = []
        if self.entities:
            parts.append(f"实体: {', '.join(self.entities)}")
        if self.select:
            select_desc = ", ".join(
                item.to_text() if isinstance(item, AggregationSpec) else item
                for item in self.select
            )
            parts.append(f"字段: {select_desc}")
        if self.filters:
            filter_desc = "; ".join(f.to_text() for f in self.filters)
            parts.append(f"筛选: {filter_desc}")
        if self.group_by:
            parts.append(f"分组: {', '.join(self.group_by)}")
        if self.having:
            having_desc = "; ".join(h.to_text() for h in self.having)
            parts.append(f"Having: {having_desc}")
        if self.order_by:
            order_desc = ", ".join(o.to_text() for o in self.order_by)
            parts.append(f"排序: {order_desc}")
        if self.limit:
            parts.append(f"限制: {self.limit}")
        if self.time_range and self.time_range.is_valid():
            parts.append(f"时间范围: {self.time_range.to_text()}")
        if self.follow_up:
            follow = self.follow_up.to_text()
            if follow:
                parts.append(f"追问: {follow}")
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# 查询结果快照与会话轮次
# ---------------------------------------------------------------------------


@dataclass
class QueryResultSnapshot:
    """用于多轮复用的查询结果摘要。"""

    columns: Sequence[str] = field(default_factory=list)
    sample_rows: Sequence[Sequence[Any]] = field(default_factory=list)
    row_count: int = 0
    has_more: bool = False
    execution_status: str = "unknown"
    raw_result: Optional[Dict[str, Any]] = None

    @classmethod
    def from_execute_payload(cls, payload: Dict[str, Any]) -> "QueryResultSnapshot":
        """
        从 execute_sqlite_query 工具返回的数据构造快照。

        Returns:
            QueryResultSnapshot
        """
        if not payload:
            return cls(execution_status="empty")

        status = payload.get("status", "unknown")
        if status != "success":
            return cls(
                execution_status=status,
                raw_result=payload,
            )

        result = payload.get("result") or {}
        columns = result.get("columns") or []
        rows = result.get("rows") or []
        row_count = len(rows)
        preview = rows[:5]

        return cls(
            columns=list(columns),
            sample_rows=list(preview),
            row_count=row_count,
            has_more=row_count > len(preview),
            execution_status=status,
            raw_result=payload,
        )

    def describe(self) -> str:
        """构造自然语言描述，便于提示词使用。"""
        if self.execution_status != "success":
            return f"执行失败: {self.execution_status}"
        if not self.columns:
            return "执行成功，但未返回列。"
        preview_lines = []
        for row in self.sample_rows:
            preview_lines.append(", ".join(str(item) for item in row))
        preview_text = (" | ".join(preview_lines)) if preview_lines else "无样本数据"
        more = "，包含更多行" if self.has_more else ""
        return f"返回列 {self.columns}，样本数据: {preview_text}{more}"


@dataclass
class ConversationTurn:
    """单轮对话数据。"""

    turn_id: str
    user_query: str
    assistant_response: str
    created_at: datetime.datetime
    intent_plan: Optional[AnalysisPlan] = None
    generated_sql: Optional[str] = None
    result_snapshot: Optional[QueryResultSnapshot] = None

    def short_summary(self) -> str:
        """用于上下文提示的简洁描述。"""
        pieces = [f"问: {self.user_query}"]
        if self.intent_plan:
            pieces.append(f"计划: {self.intent_plan.summarize()}")
        if self.generated_sql:
            pieces.append(f"SQL: {self.generated_sql}")
        if self.result_snapshot:
            pieces.append(f"结果: {self.result_snapshot.describe()}")
        pieces.append(f"答: {self.assistant_response}")
        return "\n".join(pieces)


# ---------------------------------------------------------------------------
# 会话级内存管理
# ---------------------------------------------------------------------------


class SessionConversationMemory:
    """维护单个 session 的对话记忆。"""

    def __init__(self, session_id: str, max_turns: int = 20) -> None:
        self.session_id = session_id
        self.max_turns = max_turns
        self.created_at = _now_utc()
        self.updated_at = self.created_at
        self._turns: List[ConversationTurn] = []

    # ------------------------------------------------------------------
    # 基本操作
    # ------------------------------------------------------------------
    def append_turn(self, turn: ConversationTurn) -> None:
        """追加一轮对话，自动维护最大长度。"""
        self._turns.append(turn)
        self.updated_at = _now_utc()
        if len(self._turns) > self.max_turns:
            overflow = len(self._turns) - self.max_turns
            del self._turns[0:overflow]

    def last_turn(self) -> Optional[ConversationTurn]:
        return self._turns[-1] if self._turns else None

    def last_successful_sql(self) -> Optional[str]:
        for turn in reversed(self._turns):
            if turn.generated_sql:
                return turn.generated_sql
        return None

    def last_result_schema(self) -> Optional[List[str]]:
        for turn in reversed(self._turns):
            if turn.result_snapshot and turn.result_snapshot.columns:
                return list(turn.result_snapshot.columns)
        return None

    def iter_recent(self, limit: int = 3) -> Iterable[ConversationTurn]:
        """获取最近若干轮对话，按时间顺序返回。"""
        return list(self._turns[-limit:])

    # ------------------------------------------------------------------
    # 上下文生成
    # ------------------------------------------------------------------
    def build_context_prompt(self, limit: int = 3) -> str:
        """
        生成供 LLM 参考的上下文提示。

        包含最近 limit 轮的问答、计划、SQL 及结果描述。
        """
        turns = self.iter_recent(limit)
        if not turns:
            return ""
        sections = []
        for idx, turn in enumerate(turns, start=1):
            sections.append(f"[历史#{idx}]\n{turn.short_summary()}")
        return "\n\n".join(sections)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为 Dict，便于调试或持久化。"""
        return {
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "turns": [
                {
                    "turn_id": turn.turn_id,
                    "user_query": turn.user_query,
                    "assistant_response": turn.assistant_response,
                    "created_at": turn.created_at.isoformat(),
                    "intent_plan": turn.intent_plan.to_payload()
                    if turn.intent_plan
                    else None,
                    "generated_sql": turn.generated_sql,
                    "result_snapshot": {
                        "columns": list(turn.result_snapshot.columns),
                        "sample_rows": [list(row) for row in turn.result_snapshot.sample_rows],
                        "row_count": turn.result_snapshot.row_count,
                        "has_more": turn.result_snapshot.has_more,
                        "execution_status": turn.result_snapshot.execution_status,
                    }
                    if turn.result_snapshot
                    else None,
                }
                for turn in self._turns
            ],
        }


class ConversationMemoryStore:
    """
    线程安全的会话记忆存储。

    由于 FastAPI 默认使用多线程事件循环，使用 Lock 确保并发安全。
    """

    def __init__(self, max_turns_per_session: int = 20) -> None:
        self._sessions: Dict[str, SessionConversationMemory] = {}
        self._lock = threading.RLock()
        self.max_turns_per_session = max_turns_per_session

    def get_session(self, session_id: str) -> SessionConversationMemory:
        """获取（或初始化）指定 session 的记忆对象。"""
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = SessionConversationMemory(
                    session_id=session_id,
                    max_turns=self.max_turns_per_session,
                )
            return self._sessions[session_id]

    def reset_session(self, session_id: str) -> None:
        """清空指定 session 的记忆。"""
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]

    def snapshot(self, session_id: str) -> Optional[Dict[str, Any]]:
        """返回 session 的序列化快照，便于调试。"""
        with self._lock:
            session = self._sessions.get(session_id)
        if not session:
            return None
        return session.to_dict()

    def commit_turn(
        self,
        session_id: str,
        user_query: str,
        assistant_response: str,
        intent_payload: Optional[Dict[str, Any]] = None,
        generated_sql: Optional[str] = None,
        execution_result: Optional[Dict[str, Any]] = None,
    ) -> ConversationTurn:
        """
        组合信息并写入新的对话轮次。

        Args:
            session_id: 会话 ID
            user_query: 用户自然语言问题
            assistant_response: 模型最终回答
            intent_payload: analyze_nl_intent 返回的原始计划
            generated_sql: text2sqlite 工具生成的 SQL
            execution_result: execute_sqlite_query 的执行结果
        """
        intent_plan = AnalysisPlan.from_payload(intent_payload) if intent_payload else None
        result_snapshot = (
            QueryResultSnapshot.from_execute_payload(execution_result)
            if execution_result
            else None
        )

        turn = ConversationTurn(
            turn_id=str(uuid.uuid4()),
            user_query=user_query,
            assistant_response=assistant_response,
            created_at=_now_utc(),
            intent_plan=intent_plan,
            generated_sql=generated_sql,
            result_snapshot=result_snapshot,
        )

        session = self.get_session(session_id)
        session.append_turn(turn)
        return turn


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def build_memory_context_text(
    memory_store: ConversationMemoryStore,
    session_id: str,
    limit: int = 3,
) -> str:
    """
    基于存储的 Session 记忆生成上下文提示。

    Args:
        memory_store: 会话记忆仓库
        session_id: 会话 ID
        limit: 最近多少轮
    """
    session = memory_store.get_session(session_id)
    return session.build_context_prompt(limit=limit)


def extract_last_sql_and_schema(
    memory_store: ConversationMemoryStore,
    session_id: str,
) -> Tuple[Optional[str], Optional[List[str]]]:
    """
    快捷方法：从会话记忆中获取上一轮 SQL 与结果列名。
    """
    session = memory_store.get_session(session_id)
    return session.last_successful_sql(), session.last_result_schema()


