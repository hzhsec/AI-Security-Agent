"""
工具系统 - 支持 shell / shell_batch / file_read / file_write / http_request
AI 返回 tool 字段后，由 ToolDispatcher 路由到对应处理器
"""
import logging
import requests
from typing import Dict, Any, List

from executor import executor
from result_structurer import summarize_command_output
from security import security, SecurityError
from tool_registry import tool_registry

logger = logging.getLogger(__name__)


# ─── 工具返回格式 ─────────────────────────────────────────────────────────────

class ToolResult:
    def __init__(self, output: str, success: bool, tool: str, status: str = "", note: str = "", structured_summary: str = ""):
        self.output = output
        self.success = success
        self.tool = tool
        self.status = status or ("ok" if success else "error")
        self.note = note
        self.structured_summary = structured_summary

    def __repr__(self):
        return f"ToolResult(tool={self.tool}, success={self.success}, status={self.status})"


# ─── 各工具处理函数 ───────────────────────────────────────────────────────────

def _normalize_shell_like_payload(action: Dict[str, Any]) -> Dict[str, Any]:
    """
    兼容模型把 shell / shell_batch 参数生成错类型的情况。
    目标是尽量把“能执行的内容”纠正成可运行格式，而不是直接抛异常中断任务。
    """
    tool_name = (action.get("tool") or "").strip().lower()
    normalized = dict(action)

    if tool_name == "shell":
        command = normalized.get("command", "")
        if isinstance(command, list):
            commands = [str(item).strip() for item in command if str(item).strip()]
            if len(commands) == 1:
                normalized["command"] = commands[0]
            else:
                normalized["tool"] = "shell_batch"
                normalized["commands"] = commands
                normalized["command"] = ""
                logger.info("[ToolFix] shell.command 为列表，已自动转为 shell_batch")
        elif command is None:
            normalized["command"] = ""
        elif not isinstance(command, str):
            normalized["command"] = str(command)

    elif tool_name == "shell_batch":
        commands = normalized.get("commands", [])
        if isinstance(commands, str):
            normalized["commands"] = [commands]
        elif isinstance(commands, tuple):
            normalized["commands"] = [str(item) for item in commands]
        elif not isinstance(commands, list):
            normalized["commands"] = [str(commands)] if commands else []

    return normalized

def tool_shell(action: Dict[str, Any]) -> ToolResult:
    """
    执行 Linux shell 命令。
    action: {"tool": "shell", "command": "df -h"}
    """
    action = _normalize_shell_like_payload(action)
    if action.get("tool") == "shell_batch":
        return tool_shell_batch(action)

    command = action.get("command", "")
    if not isinstance(command, str):
        command = str(command)
    command = command.strip()
    if not command:
        return ToolResult("[shell] command 字段为空", False, "shell", status="error")

    result = executor.run(command)
    status = "ok" if result.success else "error"
    structured = summarize_command_output(command, result.output)
    final_output = result.output
    if structured.get("summary_text"):
        final_output += f"\n\n[{structured['summary_title']}]\n{structured['summary_text']}"
    return ToolResult(
        final_output,
        result.success,
        "shell",
        status=status,
        structured_summary=structured.get("summary_text", ""),
    )


def tool_shell_batch(action: Dict[str, Any]) -> ToolResult:
    """
    批量顺序执行多条 shell 命令，合并输出，一步顶多步。
    action: {"tool": "shell_batch", "commands": ["cmd1", "cmd2", ...]}
    
    每条命令单独执行，结果合并后一次性返回给 AI。
    某条命令失败不会中断后续命令（除非设置 stop_on_error=true）。
    """
    action = _normalize_shell_like_payload(action)
    commands = action.get("commands", [])
    stop_on_error: bool = action.get("stop_on_error", False)

    if isinstance(commands, str):
        commands = [commands]
    elif not isinstance(commands, list):
        return ToolResult("[shell_batch] commands 字段必须是字符串列表", False, "shell_batch", status="error")

    normalized_commands: List[str] = []
    for cmd in commands:
        if not isinstance(cmd, str):
            return ToolResult("[shell_batch] commands 列表中的每一项都必须是字符串", False, "shell_batch", status="error")
        normalized_commands.append(cmd)

    commands = normalized_commands

    if not commands:
        return ToolResult("[shell_batch] commands 字段为空或不是列表", False, "shell_batch", status="error")

    outputs = []
    all_success = True
    success_count = 0
    fail_count = 0
    separator = "─" * 50

    for i, cmd in enumerate(commands, 1):
        cmd = cmd.strip()
        if not cmd:
            continue

        outputs.append(f"[{i}/{len(commands)}] $ {cmd}")
        result = executor.run(cmd)

        rendered_output = result.output
        structured = summarize_command_output(cmd, result.output)
        if structured.get("summary_text"):
            rendered_output += f"\n\n[{structured['summary_title']}]\n{structured['summary_text']}"

        if rendered_output:
            outputs.append(rendered_output)
        else:
            outputs.append("(无输出)")

        if not result.success:
            all_success = False
            fail_count += 1
            outputs.append(f"[退出码: {result.returncode}]")
            if stop_on_error:
                outputs.append(f"[stop_on_error=true，在第{i}条命令失败后停止]")
                break
        else:
            success_count += 1

        outputs.append(separator)

    combined_output = "\n".join(outputs)
    status = "ok" if all_success else ("partial" if success_count > 0 else "error")
    note = ""
    if status == "partial":
        note = f"批量命令部分成功：成功 {success_count} 条，失败 {fail_count} 条"
    elif status == "error":
        note = f"批量命令执行失败：失败 {fail_count} 条"
    return ToolResult(combined_output, all_success, "shell_batch", status=status, note=note)


def tool_file_read(action: Dict[str, Any]) -> ToolResult:
    """
    读取文件内容。
    action: {"tool": "file_read", "path": "/etc/hostname"}
    """
    path = action.get("path", "").strip()
    if not path:
        return ToolResult("[file_read] path 字段为空", False, "file_read", status="error")

    try:
        path = security.check_file_path(path, write_mode=False)
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(8192)  # 最多读 8KB
        if len(content) == 8192:
            content += "\n... [文件已截断]"
        logger.info(f"[file_read] 读取文件: {path}")
        return ToolResult(content, True, "file_read", status="ok")
    except SecurityError as e:
        return ToolResult(f"[file_read 安全拦截] {e}", False, "file_read", status="error")
    except FileNotFoundError:
        return ToolResult(f"[file_read] 文件不存在: {path}", False, "file_read", status="error")
    except Exception as e:
        return ToolResult(f"[file_read] 读取错误: {e}", False, "file_read", status="error")


def tool_file_write(action: Dict[str, Any]) -> ToolResult:
    """
    写入文件内容。
    action: {"tool": "file_write", "path": "/tmp/test.txt", "content": "hello"}
    """
    path = action.get("path", "").strip()
    content = action.get("content", "")
    if not path:
        return ToolResult("[file_write] path 字段为空", False, "file_write", status="error")

    try:
        path = security.check_file_path(path, write_mode=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"[file_write] 写入文件: {path} ({len(content)} bytes)")
        return ToolResult(f"文件写入成功: {path}", True, "file_write", status="ok")
    except SecurityError as e:
        return ToolResult(f"[file_write 安全拦截] {e}", False, "file_write", status="error")
    except Exception as e:
        return ToolResult(f"[file_write] 写入错误: {e}", False, "file_write", status="error")


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
        return ToolResult("[http_request] url 字段为空", False, "http_request", status="error")

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
        return ToolResult(output, resp.ok, "http_request", status="ok" if resp.ok else "error")
    except SecurityError as e:
        return ToolResult(f"[http_request 安全拦截] {e}", False, "http_request", status="error")
    except requests.exceptions.Timeout:
        return ToolResult(f"[http_request] 请求超时: {url}", False, "http_request", status="error")
    except Exception as e:
        return ToolResult(f"[http_request] 请求错误: {e}", False, "http_request", status="error")


def tool_finish(action: Dict[str, Any]) -> ToolResult:
    """
    任务完成标记，AI 返回 tool=finish 时表示任务结束。
    action: {"tool": "finish", "summary": "任务已完成，..."}
    """
    summary = action.get("summary", "任务已完成")
    return ToolResult(summary, True, "finish", status="ok")


def tool_mcp(action: Dict[str, Any]) -> ToolResult:
    """
    调用 MCP 风格注册能力。
    action: {"tool": "mcp_tool", "mcp_tool": "nmap_web_scan", "arguments": {"target": "example.com"}}
    """
    capability_name = (
        action.get("mcp_tool")
        or action.get("capability")
        or action.get("name")
        or ""
    ).strip()
    arguments = action.get("arguments", {})

    if not capability_name:
        return ToolResult("[mcp_tool] mcp_tool 字段为空", False, "mcp_tool", status="error")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return ToolResult("[mcp_tool] arguments 必须是对象", False, "mcp_tool", status="error")

    result = tool_registry.execute_capability(capability_name, arguments)
    output = result.get("output", "")
    command = result.get("command", "")
    if command:
        output = f"[capability] {capability_name}\n[command] {command}\n{output}"
    else:
        output = f"[capability] {capability_name}\n{output}"
    success = result.get("success", False)
    return ToolResult(output, success, "mcp_tool", status="ok" if success else "error")


# ─── 工具分发器 ───────────────────────────────────────────────────────────────

TOOL_MAP = {
    "shell": tool_shell,
    "shell_batch": tool_shell_batch,
    "file_read": tool_file_read,
    "file_write": tool_file_write,
    "http_request": tool_http_request,
    "mcp_tool": tool_mcp,
    "finish": tool_finish,
}

TOOL_DESCRIPTIONS = """
可用工具列表：
- shell: 执行单条 shell 命令（Linux bash / Windows cmd 均支持），参数: command (str)
- shell_batch: 【推荐】批量顺序执行多条命令（一步顶多步），参数: commands (list[str]), stop_on_error (bool, 默认false)
- file_read: 读取文件内容，参数: path (str)
- file_write: 写入文件内容，参数: path (str), content (str)
- http_request: 发送 HTTP 请求，参数: url (str), method (str, 默认GET), headers (dict), body (str)
- mcp_tool: 调用已注册的 MCP 风格工具能力，参数: mcp_tool (str), arguments (dict)
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
