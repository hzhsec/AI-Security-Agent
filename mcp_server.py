"""
最小可用的 MCP stdio Server。

当前实现重点支持：
1. initialize
2. tools/list
3. tools/call

这样后续可以让外部 MCP Client 直接消费本项目已经注册的结构化能力。
"""
import json
import logging
import sys
from typing import Any, Dict, Optional

from tool_registry import tool_registry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger(__name__)


class MCPServer:
    """基于 stdio 的最小 MCP Server。"""

    def __init__(self):
        self.server_name = "ai-security-agent"
        self.server_version = "0.1.0"

    def run(self):
        """持续读取 MCP 请求并返回响应。"""
        while True:
            message = self._read_message()
            if message is None:
                return
            response = self._handle_message(message)
            if response is not None:
                self._write_message(response)

    def _read_message(self) -> Optional[Dict[str, Any]]:
        """按 Content-Length 协议读取一条 JSON-RPC 消息。"""
        content_length = None

        while True:
            line = sys.stdin.buffer.readline()
            if not line:
                return None
            if line in (b"\r\n", b"\n"):
                break
            header = line.decode("utf-8", errors="replace").strip()
            if header.lower().startswith("content-length:"):
                content_length = int(header.split(":", 1)[1].strip())

        if content_length is None:
            return None

        body = sys.stdin.buffer.read(content_length)
        if not body:
            return None

        return json.loads(body.decode("utf-8"))

    def _write_message(self, payload: Dict[str, Any]):
        """写出一条 JSON-RPC 响应。"""
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
        sys.stdout.buffer.write(header)
        sys.stdout.buffer.write(body)
        sys.stdout.buffer.flush()

    def _handle_message(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """处理 MCP 消息。"""
        method = message.get("method")
        msg_id = message.get("id")
        params = message.get("params", {}) or {}

        if method == "notifications/initialized":
            return None

        if method == "initialize":
            protocol_version = params.get("protocolVersion", "2024-11-05")
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": protocol_version,
                    "serverInfo": {
                        "name": self.server_name,
                        "version": self.server_version,
                    },
                    "capabilities": {
                        "tools": {},
                    },
                },
            }

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "tools": self._list_tools(),
                },
            }

        if method == "tools/call":
            name = params.get("name", "")
            arguments = params.get("arguments", {}) or {}
            result = tool_registry.execute_capability(name, arguments)
            text = result.get("output", "")
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": text,
                        }
                    ],
                    "isError": not result.get("success", False),
                },
            }

        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {
                "code": -32601,
                "message": f"不支持的方法: {method}",
            },
        }

    def _list_tools(self):
        """把本地注册能力映射成 MCP tools/list 返回格式。"""
        tools = []
        for item in tool_registry.list_all():
            for capability in item.get("capabilities", []):
                tools.append({
                    "name": capability.get("name"),
                    "description": capability.get("description") or item.get("summary", ""),
                    "inputSchema": capability.get("args_schema", {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    }),
                })
        return tools


if __name__ == "__main__":
    try:
        MCPServer().run()
    except Exception as e:
        logger.exception(f"MCP Server 异常退出: {e}")
        raise
