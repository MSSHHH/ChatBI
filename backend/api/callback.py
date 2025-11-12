"""
流式输出回调处理器
用于 SSE 流式输出
"""
from typing import Any, Callable, Dict, List, Optional

from langchain_core.callbacks.base import BaseCallbackHandler

from backend.services.conversation_memory import ConversationMemoryStore


class StreamingCallbackHandler(BaseCallbackHandler):
    """流式输出回调处理器"""
    
    def __init__(
        self,
        token_callback: Optional[Callable[[str], None]] = None,
        memory_store: Optional[ConversationMemoryStore] = None,
        session_id: Optional[str] = None,
    ):
        self.token_buffer: List[str] = []
        self.final_message: str = ""
        self.has_streaming_started: bool = False
        self.has_streaming_ended: bool = False
        self.token_callback = token_callback  # 用于实时发送 token 的回调函数
        self.memory_store = memory_store
        self.session_id = session_id

        # 工具调用追踪缓存
        self._tool_stack: List[str] = []
        self._intent_payload: Optional[Dict[str, Any]] = None
        self._generated_sql: Optional[str] = None
        self._execution_payload: Optional[Dict[str, Any]] = None
    
    def on_llm_new_token(self, token: str, **kwargs) -> None:
        """处理新的 token"""
        if not self.has_streaming_started:
            self.has_streaming_started = True
        
        self.token_buffer.append(token)
        self.final_message = "".join(self.token_buffer)
        
        # 如果有回调函数，实时发送 token
        if self.token_callback:
            try:
                self.token_callback(token)
            except Exception as e:
                print(f"Error in token callback: {e}")
    
    def on_llm_end(self, response, **kwargs) -> None:
        """LLM 输出结束"""
        self.has_streaming_ended = True
        self.has_streaming_started = False
    
    # ------------------------------------------------------------------
    # 工具调用追踪
    # ------------------------------------------------------------------
    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs) -> None:
        """记录当前调用的工具名称，用于在 on_tool_end 阶段识别输出。"""
        tool_name = None
        if serialized:
            tool_name = serialized.get("name")
        if not tool_name:
            tool_name = kwargs.get("name")
        if tool_name:
            self._tool_stack.append(tool_name)
    
    def on_tool_end(self, output: Any, **kwargs) -> None:
        """根据工具名称缓存结构化数据，便于会话记忆使用。"""
        tool_name = kwargs.get("name")
        if not tool_name and self._tool_stack:
            tool_name = self._tool_stack.pop()
        elif tool_name and self._tool_stack and self._tool_stack[-1] == tool_name:
            self._tool_stack.pop()

        if tool_name == "analyze_nl_intent":
            if isinstance(output, dict):
                self._intent_payload = output
        elif tool_name == "text2sqlite_query":
            if isinstance(output, dict):
                sql = output.get("sqlite_query")
                if isinstance(sql, str):
                    self._generated_sql = sql.strip()
        elif tool_name == "execute_sqlite_query":
            if isinstance(output, dict):
                self._execution_payload = output
    
    def on_llm_error(self, error: Exception, **kwargs) -> None:
        """LLM 错误处理"""
        self.final_message = f"错误: {str(error)}"
        self.has_streaming_ended = True

    # ------------------------------------------------------------------
    # 会话记忆辅助
    # ------------------------------------------------------------------
    def consume_tracked_data(self) -> Dict[str, Any]:
        """
        获取一次对话中追踪到的工具输出，并在返回后清空缓存。

        Returns:
            包含 intent/sql/result 的字典（可能部分为空）。
        """
        data = {
            "intent_payload": self._intent_payload,
            "generated_sql": self._generated_sql,
            "execution_payload": self._execution_payload,
        }
        self._intent_payload = None
        self._generated_sql = None
        self._execution_payload = None
        self._tool_stack.clear()
        return data

