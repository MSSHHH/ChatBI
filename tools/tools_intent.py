from typing import Any, Dict, List, Optional
from langchain_core.tools import tool
from langchain.chat_models import init_chat_model
import os
from dotenv import load_dotenv
from contextvars import ContextVar

load_dotenv()

_intent_llm = None
_intent_model_name: Optional[str] = None
_intent_context: ContextVar[Dict[str, Any]] = ContextVar("_intent_context", default={})


def set_intent_context(
	session_id: str,
	last_sql: Optional[str] = None,
	last_result_schema: Optional[List[str]] = None,
) -> None:
	"""
	设置当前请求的默认上下文，供 analyze_nl_intent 自动复用。
	"""
	payload: Dict[str, Any] = {
		"session_id": session_id,
		"last_sql": last_sql or "",
		"last_result_schema": last_result_schema or [],
	}
	_intent_context.set(payload)


def clear_intent_context() -> None:
	"""清空上下文，避免串话。"""
	_intent_context.set({})


def _get_intent_context() -> Dict[str, Any]:
	return _intent_context.get({})


def _get_llm(model_name: str = "qwen-plus"):
	"""
	延迟初始化用于意图解析的 LLM，默认与主模型一致。
	"""
	global _intent_llm, _intent_model_name
	if _intent_llm is None or _intent_model_name != model_name:
		_intent_llm = init_chat_model(
			model=model_name,
			model_provider="openai",
			base_url=os.getenv(
				"OPENAI_API_BASE_URL",
				"https://api.deepseek.com/v1",
			),
		)
		_intent_model_name = model_name
	return _intent_llm


def _build_intent_prompt(text: str, last_sql: str = "", last_result_schema: str = "") -> str:
	"""
	构造意图解析提示词，要求输出严格 JSON。
	"""
	example_json = r"""{
  "task": "analysis | comparison | trend | aggregation | listing",
  "entities": ["orders", "customers"],
  "select": ["customer_name", {"agg": "sum", "field": "total_amount", "alias": "total"}],
  "filters": [
    {"field": "order_date", "op": ">=", "value": "2025-01-01"},
    {"field": "status", "op": "in", "value": ["paid","shipped"]}
  ],
  "group_by": ["customer_id"],
  "having": [{"field": "total", "op": ">", "value": 1000}],
  "order_by": [{"field": "total", "direction": "desc"}],
  "limit": 50,
  "time_range": {"start": "2025-01-01", "end": "2025-12-31"},
  "follow_up": {
    "refers_previous": true,
    "use_last_sql": true,
    "modify": "change group_by to month(order_date) and aggregate by count(*)"
  },
  "explanations": "Chinese brief reasoning about how to map to SQL"
}"""
	return (
		"你是一个“自然语言到结构化分析计划”的专家。请将用户问题解析为严谨的结构化计划（JSON）。\n"
		"要求：\n"
		"1) 输出必须是合法 JSON，且仅输出 JSON，不要任何额外文字；\n"
		"2) 覆盖筛选(filters)、分组(group_by/having)、聚合(agg)、排序(order_by)、限制(limit)、时间范围(time_range)；\n"
		"3) 若问题为追问/上下文关联，使用 follow_up 字段体现修改点或复用上轮 SQL；\n"
		"4) 允许 select 中包含聚合表达式对象；\n"
		"5) 保持字段名与用户语义一致，别做无端映射；\n"
		"6) 简要中文解释填入 explanations 字段。\n"
		f"用户问题: {text}\n"
		f"上轮SQL(可为空): {last_sql}\n"
		f"上轮结果Schema(可为空): {last_result_schema}\n"
		f"示例: {example_json}\n"
	)


@tool(
	"analyze_nl_intent",
	description="将自然语言问题解析为结构化分析计划(JSON)，覆盖筛选/分组/聚合/排序/时间范围，支持基于上轮结果的追问。",
)
def analyze_nl_intent(text: str, last_sql: str = "", last_result_schema: str = "", model_name: str = "qwen-plus") -> Dict[str, Any]:
	"""
	参数:
		text: 自然语言问题
		last_sql: 上一轮已执行的 SQL（如有）
		last_result_schema: 上一轮结果的列结构提示（如有）
		model_name: 用于解析的模型名称（默认与主模型一致）
	返回:
		结构化的意图计划(JSON对象)
	"""
	if not last_sql or not last_result_schema:
		context = _get_intent_context()
		if not last_sql:
			last_sql = context.get("last_sql", "")
		if not last_result_schema:
			last_result_schema = context.get("last_result_schema", [])

	prompt = _build_intent_prompt(text, last_sql, last_result_schema)
	llm = _get_llm(model_name)
	resp = llm.invoke(prompt)
	# langchain 返回消息对象，content 为字符串
	import json
	try:
		return json.loads(resp.content)
	except Exception:
		# 兜底：若模型未输出严格 JSON，尝试从代码块或花括号截取
		txt = resp.content.strip()
		start = txt.find("{")
		end = txt.rfind("}")
		if start != -1 and end != -1 and end > start:
			try:
				return json.loads(txt[start : end + 1])
			except Exception:
				pass
		return {"error": "intent_parse_failed", "raw": txt}


