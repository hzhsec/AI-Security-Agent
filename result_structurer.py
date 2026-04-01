"""
命令结果结构化模块。
对高频安全巡检命令做本地摘要，减少模型反复从原始文本里找关键信息。
"""
import re
from typing import Dict, List


def summarize_command_output(command: str, output: str) -> Dict[str, str]:
    """根据命令和输出生成结构化摘要。"""
    command_text = (command or "").strip()
    output_text = (output or "").strip()
    if not command_text or not output_text:
        return {"summary_text": "", "summary_title": ""}

    lower_command = command_text.lower()

    handlers = [
        (_is_process_command, _summarize_process_output),
        (_is_network_command, _summarize_network_output),
        (_is_persistence_command, _summarize_persistence_output),
        (_is_login_command, _summarize_login_output),
    ]

    for matcher, handler in handlers:
        if matcher(lower_command):
            summary_text = handler(output_text)
            if summary_text:
                return {"summary_text": summary_text, "summary_title": "结构化摘要"}

    return {"summary_text": "", "summary_title": ""}


def _is_process_command(command: str) -> bool:
    return any(keyword in command for keyword in ["ps ", "tasklist", "get-process", "wmic process"])


def _is_network_command(command: str) -> bool:
    return any(keyword in command for keyword in ["netstat", "ss ", "get-nettcpconnection"])


def _is_persistence_command(command: str) -> bool:
    return any(keyword in command for keyword in ["crontab", "schtasks", "systemctl", "service ", "autoruns"])


def _is_login_command(command: str) -> bool:
    return any(keyword in command for keyword in ["last", "lastlog", "who", "query user", "quser", "get-winevent", "wevtutil"])


def _summarize_process_output(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    findings: List[str] = []

    if "name=" in output.lower():
        names = re.findall(r"(?im)^name=(.+)$", output)
        pids = re.findall(r"(?im)^processid=(.+)$", output)
        paths = re.findall(r"(?im)^executablepath=(.*)$", output)
        if names:
            paired = []
            for idx, name in enumerate(names[:5]):
                pid = pids[idx].strip() if idx < len(pids) else "?"
                path = paths[idx].strip() if idx < len(paths) else ""
                extra = " | 无路径" if not path else f" | {path[:80]}"
                paired.append(f"- {name.strip()} (PID {pid}){extra}")
            findings.append(f"识别到 {len(names)} 个进程条目：")
            findings.extend(paired)
            if any(not (paths[idx].strip() if idx < len(paths) else "") for idx in range(min(len(names), len(paired)))):
                findings.append("- 注意：存在无法获取可执行路径的进程，建议继续核查权限、签名或父进程关系")
            return "\n".join(findings)

    proc_lines = [line for line in lines if re.search(r"\b\d+\b", line)]
    if proc_lines:
        findings.append(f"检测到进程输出共 {len(proc_lines)} 行，示例：")
        findings.extend(f"- {line[:120]}" for line in proc_lines[:5])
        return "\n".join(findings)
    return ""


def _summarize_network_output(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    network_lines = [
        line for line in lines
        if re.search(r"(?i)\b(listen|listening|established|tcp|udp)\b", line)
    ]
    if not network_lines:
        return ""

    listening = [line for line in network_lines if re.search(r"(?i)\b(listen|listening)\b", line)]
    established = [line for line in network_lines if re.search(r"(?i)\bestablished\b", line)]

    summary = [
        f"网络连接摘要：共识别 {len(network_lines)} 条关键网络记录",
        f"- 监听记录: {len(listening)} 条",
        f"- 已建立连接: {len(established)} 条",
    ]
    if listening:
        summary.append("- 监听示例:")
        summary.extend(f"  - {line[:120]}" for line in listening[:5])
    if established:
        summary.append("- 建连示例:")
        summary.extend(f"  - {line[:120]}" for line in established[:5])
    return "\n".join(summary)


def _summarize_persistence_output(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    useful = [line for line in lines if len(line) > 3]
    if not useful:
        return ""

    summary = [f"持久化项摘要：共识别 {len(useful)} 行相关输出"]
    summary.extend(f"- {line[:120]}" for line in useful[:6])
    return "\n".join(summary)


def _summarize_login_output(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    useful = [line for line in lines if not line.lower().startswith(("wtmp begins", "username"))]
    if not useful:
        return ""

    summary = [f"登录/审计摘要：共识别 {len(useful)} 条相关记录"]
    summary.extend(f"- {line[:120]}" for line in useful[:6])
    return "\n".join(summary)
