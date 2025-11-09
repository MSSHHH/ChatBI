"""
流式输出回调处理器
用于 SSE 流式输出
"""
from typing import List, Optional, Callable
from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.messages import BaseMessage
import queue
import threading


class StreamingCallbackHandler(BaseCallbackHandler):
    """流式输出回调处理器"""
    
    def __init__(self, token_callback: Optional[Callable[[str], None]] = None):
        self.token_buffer: List[str] = []
        self.final_message: str = ""
        self.has_streaming_started: bool = False
        self.has_streaming_ended: bool = False
        self.token_callback = token_callback  # 用于实时发送 token 的回调函数
        self.token_queue = queue.Queue()  # 用于存储待发送的 token
    
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
    
    def on_llm_error(self, error: Exception, **kwargs) -> None:
        """LLM 错误处理"""
        self.final_message = f"错误: {str(error)}"
        self.has_streaming_ended = True

