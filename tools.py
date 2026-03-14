"""
工具系统 - 支持 shell / shell_batch / file_read / file_write / http_request
AI 返回 tool 字段后，由 ToolDispatcher 路由到对应处理器
"""
import logging
import requests
from typing import Dict, Any, List

from executor import executor
from security import security, SecurityError

logger = logging.getLogger(__name__)


# ─── 工具返回格式 ─────────────────────────────────────────────────────────────

class ToolResult:
    def __init__(self, output: str, success: bool, tool: str):
        self.output = output
        self.success = success
        self.tool = tool

    def __repr__(self):
        return f"ToolResult(tool={self.tool}, success={self.success})"


# ─── 各工具处理函数 ───────────────────────────────────────────────────────────

def tool_shell(action: Dict[str, Any]) -> ToolResult:
    """
    执行 Linux shell 命令。
    action: {"tool": "shell", "command": "df -h"}
    """
    command = action.get("command", "").strip()
    if not command:
        return ToolResult("[shell] command 字段为空", False, "shell")

    result = executor.run(command)
    return ToolResult(result.output, result.success, "shell")


def tool_shell_batch(action: Dict[str, Any]) -> ToolResult:
    """
    批量顺序执行多条 shell 命令，合并输出，一步顶多步。
    action: {"tool": "shell_batch", "commands": ["cmd1", "cmd2", ...]}
    
    每条命令单独执行，结果合并后一次性返回给 AI。
    某条命令失败不会中断后续命令（除非设置 stop_on_error=true）。
    """
    commands: List[str] = action.get("commands", [])
    stop_on_error: bool = action.get("stop_on_error", False)

    if not commands:
        return ToolResult("[shell_batch] commands 字段为空或不是列表", False, "shell_batch")

    outputs = []
    all_success = True
    separator = "─" * 50

    for i, cmd in enumerate(commands, 1):
        cmd = cmd.strip()
        if not cmd:
            continue

        outputs.append(f"[{i}/{len(commands)}] $ {cmd}")
        result = executor.run(cmd)

        if result.output:
            outputs.append(result.output)
        else:
            outputs.append("(无输出)")

        if not result.success:
            all_success = False
            outputs.append(f"[退出码: {result.returncode}]")
            if stop_on_error:
                outputs.append(f"[stop_on_error=true，在第{i}条命令失败后停止]")
                break

        outputs.append(separator)

    combined_output = "\n".join(outputs)
    return ToolResult(combined_output, all_success, "shell_batch")


def tool_file_read(action: Dict[str, Any]) -> ToolResult:
    """
    读取文件内容。
    action: {"tool": "file_read", "path": "/etc/hostname"}
    """
    path = action.get("path", "").strip()
    if not path:
        return ToolResult("[file_read] path 字段为空", False, "file_read")

    try:
        path = security.check_file_path(path, write_mode=False)
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(8192)  # 最多读 8KB
        if len(content) == 8192:
            content += "\n... [文件已截断]"
        logger.info(f"[file_read] 读取文件: {path}")
        return ToolResult(content, True, "file_read")
    except SecurityError as e:
        return ToolResult(f"[file_read 安全拦截] {e}", False, "file_read")
    except FileNotFoundError:
        return ToolResult(f"[file_read] 文件不存在: {path}", False, "file_read")
    except Exception as e:
        return ToolResult(f"[file_read] 读取错误: {e}", False, "file_read")


def tool_file_write(action: Dict[str, Any]) -> ToolResult:
    """
    写入文件内容。
    action: {"tool": "file_write", "path": "/tmp/test.txt", "content": "hello"}
    """
    path = action.get("path", "").strip()
    content = action.get("content", "")
    if not path:
        return ToolResult("[file_write] path 字段为空", False, "file_write")

    try:
        path = security.check_file_path(path, write_mode=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"[file_write] 写入文件: {path} ({len(content)} bytes)")
        return ToolResult(f"文件写入成功: {path}", True, "file_write")
    except SecurityError as e:
        return ToolResult(f"[file_write 安全拦截] {e}", False, "file_write")
    except Exception as e:
        return ToolResult(f"[file_write] 写入错误: {e}", False, "file_write")


def tool_http_request(action: Dict[str, Any]) -> ToolResult:
    """
    发送 HTTP 请求。
    action: {"tool": "http_request", "method": "GET", "url": "https://...", "headers": {}, "body": ""}
    """
    url = action.get("url", "").strip()
    method = action.get("method", "GET").upper()
    headers = action.get("headers", {})
    body = action.get("body", None)
    timeout = action.get("timeout", 15)

    if not url:
        return ToolResult("[http_request] url 字段为空", False, "http_request")

    try:
        url = security.sanitize_url(url)
        resp = requests.request(
            method, url,
            headers=headers,
            data=body,
            timeout=timeout,
            allow_redirects=True,
        )
        output = (
            f"HTTP {resp.status_code} {resp.reason}\n"
            f"Headers: {dict(resp.headers)}\n"
            f"Body: {resp.text[:2000]}"
        )
        logger.info(f"[http_request] {method} {url} -> {resp.status_code}")
        return ToolResult(output, resp.ok, "http_request")
    except SecurityError as e:
        return ToolResult(f"[http_request 安全拦截] {e}", False, "http_request")
    except requests.exceptions.Timeout:
        return ToolResult(f"[http_request] 请求超时: {url}", False, "http_request")
    except Exception as e:
        return ToolResult(f"[http_request] 请求错误: {e}", False, "http_request")


def tool_finish(action: Dict[str, Any]) -> ToolResult:
    """
    任务完成标记，AI 返回 tool=finish 时表示任务结束。
    action: {"tool": "finish", "summary": "任务已完成，..."}
    """
    summary = action.get("summary", "任务已完成")
    return ToolResult(summary, True, "finish")


# ─── 工具分发器 ───────────────────────────────────────────────────────────────

TOOL_MAP = {
    "shell": tool_shell,
    "shell_batch": tool_shell_batch,
    "file_read": tool_file_read,
    "file_write": tool_file_write,
    "http_request": tool_http_request,
    "finish": tool_finish,
}

TOOL_DESCRIPTIONS = """
可用工具列表：
- shell: 执行单条 shell 命令（Linux bash / Windows cmd 均支持），参数: command (str)
- shell_batch: 【推荐】批量顺序执行多条命令（一步顶多步），参数: commands (list[str]), stop_on_error (bool, 默认false)
- file_read: 读取文件内容，参数: path (str)
- file_write: 写入文件内容，参数: path (str), content (str)
- http_request: 发送 HTTP 请求，参数: url (str), method (str, 默认GET), headers (dict), body (str)
- finish: 标记任务完成并输出完整报告，参数: summary (str) - 必须包含巡检结论
"""


class ToolDispatcher:
    """工具分发器，根据 AI 返回的 tool 字段调用对应处理器"""

    def dispatch(self, action: Dict[str, Any]) -> ToolResult:
        tool_name = action.get("tool", "").lower().strip()

        if tool_name not in TOOL_MAP:
            available = ", ".join(TOOL_MAP.keys())
            return ToolResult(
                f"[ToolDispatcher] 未知工具: '{tool_name}'，可用工具: {available}",
                False,
                tool_name,
            )

        handler = TOOL_MAP[tool_name]
        logger.info(f"[ToolDispatcher] 调用工具: {tool_name}")
        return handler(action)


# 全局工具分发器
dispatcher = ToolDispatcher()
