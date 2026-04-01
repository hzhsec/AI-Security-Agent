"""
AI Agent 核心逻辑 - DeepSeek API 调用 + Agent Loop 主循环
"""
import json
import uuid
import logging
import re
from typing import Dict, Any, List, Generator

from config import (
    MAX_ITERATIONS, MAX_SAME_COMMAND_ATTEMPTS, MAX_FAILED_COMMAND_ATTEMPTS,
    FINALIZE_MIN_SUMMARY_CHARS, FINALIZE_MIN_DONE_EVIDENCE,
    load_model_config, make_openai_client,
)
from memory import memory
from prompt_builder import get_agent_base_prompt, build_agent_workflow_hint, build_finalize_prompt
from tools import dispatcher
from tool_knowledge import tool_knowledge
from tool_registry import tool_registry

logger = logging.getLogger(__name__)


# ─── JSON 解析工具函数 ──────────────────────────────────────────────────────────

def parse_ai_response(raw: str) -> Dict[str, Any]:
    """
    从 AI 原始响应中解析 JSON。
    兼容以下情况：
    - AI 用 markdown 代码块包裹（```json ... ```）
    - 带 <think>...</think> 推理标签（MiniMax-M1 / DeepSeek-R1 等思维链模型）
    - JSON 被截断（自动补全闭合符号）
    """
    raw = raw.strip()

    # 剥离 <think>...</think> 推理过程（MiniMax-M1、DeepSeek-R1 等模型会输出思维链）
    # 支持多段 think 标签、大小写不敏感
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    raw = raw.strip()

    # 去掉 markdown 代码块
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        # 尝试提取第一个 JSON 对象
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass

        # 尝试修复截断的 JSON（补全缺失的 ] } " 等）
        fixed = raw.strip()
        opens = {"{": 0, "[": 0, "\"": 0}
        in_string = False
        escape = False

        for ch in fixed:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == "\"" and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue

            if ch == "{":
                opens["{"] += 1
            elif ch == "}":
                opens["{"] -= 1
            elif ch == "[":
                opens["["] += 1
            elif ch == "]":
                opens["["] -= 1

        # 补全缺失的闭合符号
        if in_string:
            fixed += "\""
        while opens["["] > 0:
            fixed += "]"
            opens["["] -= 1
        while opens["{"] > 0:
            fixed += "}"
            opens["{"] -= 1

        if fixed != raw.strip():
            try:
                logger.info(f"[JSON] 尝试修复截断的 JSON，原始长度: {len(raw)}, 修复后: {len(fixed)}")
                return json.loads(fixed)
            except Exception:
                pass

        logger.error(f"AI 响应无法解析为 JSON: {raw[:300]}")
        # 兜底：返回一个无操作的 shell 命令，让任务继续而非直接崩溃
        # （下一轮 AI 会看到 "格式错误" 的执行结果，有机会修正）
        return {
            "thought": f"AI 返回格式异常（可能包含未剥离的特殊标签），原始内容片段: {raw[:200]}",
            "tool": "shell",
            "command": "echo [上一步AI响应格式异常，请继续执行剩余任务]",
            "continue": True,
        }


def normalize_action(action: Dict[str, Any], current_phase: str = "collect") -> Dict[str, Any]:
    """
    对模型返回的动作做统一校验与修复。
    目标是尽量本地纠正明显格式错误，减少因输出漂移导致的任务中断。
    """
    if not isinstance(action, dict):
        return {
            "thought": "AI 返回的动作不是对象，已回退为纠错提示命令",
            "tool": "shell",
            "command": "echo [上一步AI动作不是合法对象，请按JSON协议重新规划]",
            "continue": True,
        }

    normalized = dict(action)
    tool = str(normalized.get("tool", "shell") or "shell").strip().lower()
    allowed_tools = {"shell", "shell_batch", "file_read", "file_write", "http_request", "mcp_tool", "finish"}
    if tool not in allowed_tools:
        tool = "shell"
    normalized["tool"] = tool

    for field in ("thought", "plan", "summary", "path", "url", "method", "learn_tool", "learn_usage", "mcp_tool"):
        value = normalized.get(field)
        if value is None:
            continue
        if not isinstance(value, str):
            normalized[field] = str(value)

    continue_value = normalized.get("continue", True)
    if isinstance(continue_value, str):
        normalized["continue"] = continue_value.strip().lower() not in ("false", "0", "no")
    else:
        normalized["continue"] = bool(continue_value)

    evidence = normalized.get("evidence", [])
    if isinstance(evidence, str):
        normalized["evidence"] = [evidence] if evidence.strip() else []
    elif isinstance(evidence, list):
        normalized["evidence"] = [str(item).strip() for item in evidence if str(item).strip()]
    else:
        normalized["evidence"] = [str(evidence)] if evidence else []

    arguments = normalized.get("arguments", {})
    if tool == "mcp_tool":
        if not isinstance(arguments, dict):
            normalized["arguments"] = {}
        if not normalized.get("mcp_tool", "").strip():
            normalized["tool"] = "shell"
            normalized["command"] = "echo [mcp_tool 缺少能力名，请重新选择能力或改用 shell]"
            normalized["continue"] = True

    command = normalized.get("command", "")
    commands = normalized.get("commands", [])

    if tool == "shell":
        if isinstance(command, list):
            normalized["tool"] = "shell_batch"
            normalized["commands"] = [str(item).strip() for item in command if str(item).strip()]
            normalized["command"] = ""
        elif command is None:
            normalized["command"] = ""
        elif not isinstance(command, str):
            normalized["command"] = str(command)

    if normalized["tool"] == "shell_batch":
        if isinstance(commands, str):
            normalized["commands"] = [commands] if commands.strip() else []
        elif isinstance(commands, list):
            normalized["commands"] = [str(item).strip() for item in commands if str(item).strip()]
        elif command:
            normalized["commands"] = [str(command).strip()]
        else:
            normalized["commands"] = []

        if not normalized["commands"] and isinstance(command, str) and command.strip():
            normalized["commands"] = [command.strip()]

        if len(normalized["commands"]) == 1 and current_phase == "conclude":
            normalized["tool"] = "shell"
            normalized["command"] = normalized["commands"][0]

    if normalized["tool"] == "finish":
        summary = (normalized.get("summary") or "").strip()
        if not summary:
            normalized["tool"] = "shell"
            normalized["command"] = "echo [finish 缺少 summary，请先整理 threats suspicious normal advice 再结束]"
            normalized["continue"] = True
        else:
            normalized["continue"] = False

    return normalized


# ─── AI Agent 主类 ─────────────────────────────────────────────────────────────

class LinuxAgent:
    """
    AI Agent 主类，支持 Linux / Windows 双系统模式。
    每次 API 调用时动态读取当前模型配置，支持运行时热切换。
    """

    def _get_client_and_model(self):
        """每次调用都重新读取配置，实现模型热切换（含代理支持）"""
        cfg = load_model_config()
        client = make_openai_client(cfg)
        return client, cfg["model"], cfg.get("provider", "unknown")

    def _call_ai(self, messages: List[Dict], stop_event=None) -> str:
        """
        调用 AI API，返回原始文本。
        stop_event: threading.Event，设置后会中断等待并抛出 StopIteration。
        """
        import concurrent.futures
        messages = self._compress_messages(messages)

        client, model, provider = self._get_client_and_model()
        logger.info(f"[AI] 使用模型: {provider} / {model}")

        def _do_call():
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.1,
                max_tokens=4096,
                response_format={"type": "json_object"},
            )
            return response.choices[0].message.content

        if stop_event is None:
            # 无停止信号，走原来的同步调用
            return _do_call()

        # 有停止信号：在线程池中执行，每 0.5s 检查一次 stop_event
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(_do_call)
        try:
            while True:
                try:
                    result = future.result(timeout=0.5)
                    executor.shutdown(wait=False, cancel_futures=False)
                    return result
                except concurrent.futures.TimeoutError:
                    if stop_event.is_set():
                        future.cancel()
                        executor.shutdown(wait=False, cancel_futures=True)
                        logger.info("[AI] 检测到停止信号，中断 AI API 等待")
                        raise StopIteration("用户停止任务")
                except Exception:
                    executor.shutdown(wait=False, cancel_futures=False)
                    raise
        except Exception:
            executor.shutdown(wait=False, cancel_futures=True)
            raise

    def _normalize_shell_batch_action(self, action: Dict[str, Any]) -> None:
        """
        兼容 AI 常见格式错误：
        1. tool=shell_batch 但误填 command
        2. commands 错误地返回为单个字符串
        """
        if action.get("tool", "shell") != "shell_batch":
            return

        commands = action.get("commands")
        command = action.get("command")

        if not commands and isinstance(command, str):
            single_cmd = command.strip()
            if single_cmd:
                # 保留整条命令，交给 shell 自己处理 && / ; / | 等语法，避免拆坏引号和控制符。
                action["commands"] = [single_cmd]
                logger.info(f"[ActionFix] 将 shell_batch 的单条 command 转为 commands: {single_cmd}")
            return

        if isinstance(commands, str):
            single_cmd = commands.strip()
            action["commands"] = [single_cmd] if single_cmd else []
            logger.info(f"[ActionFix] 将字符串 commands 转为列表: {action['commands']}")

    def _determine_phase(self, session, iteration: int, action: Dict[str, Any], tool_result=None) -> str:
        """根据当前会话状态推断下一阶段。"""
        if action.get("tool") == "finish":
            return "conclude"

        total_steps = len(session.steps) if session else 0
        failed_steps = sum(1 for step in session.steps if not step.success) if session else 0
        current_phase = getattr(session, "phase", "plan") if session else "plan"

        if current_phase == "plan":
            return "collect"

        if current_phase == "collect":
            if total_steps >= 3 or failed_steps >= 2:
                return "verify"
            return "collect"

        if current_phase == "verify":
            if iteration >= max(4, MAX_ITERATIONS - 2):
                return "conclude"
            if tool_result is not None and tool_result.success and total_steps >= 5:
                return "conclude"
            return "verify"

        return "conclude"

    def _build_phase_hint(self, phase: str) -> str:
        """给当前轮次附加阶段提醒。"""
        hints = {
            "plan": (
                "当前阶段: plan\n"
                "- 先明确任务范围、重点证据面、可优先使用的工具\n"
                "- 本轮尽量给出低风险的起手动作"
            ),
            "collect": (
                "当前阶段: collect\n"
                "- 优先覆盖账号、进程、网络、持久化、日志中的空白证据面\n"
                "- 适合使用 shell_batch 或 mcp_tool 一次收集多项信息"
            ),
            "verify": (
                "当前阶段: verify\n"
                "- 围绕已发现异常做定向验证\n"
                "- 不要重复执行已经验证过的全量采集命令"
            ),
            "conclude": (
                "当前阶段: conclude\n"
                "- 除非缺少关键证据，否则优先 finish\n"
                "- 总结时明确 threats / suspicious / normal / advice"
            ),
        }
        return hints.get(phase, "")

    def _get_action_display(self, action: Dict[str, Any]) -> str:
        """生成步骤展示文本，避免 shell_batch 的 commands 在历史中丢失。"""
        tool = action.get("tool", "")
        if tool == "shell_batch":
            commands = action.get("commands") or []
            if isinstance(commands, list):
                clean_commands = [str(cmd).strip() for cmd in commands if str(cmd).strip()]
                if clean_commands:
                    return " ; ".join(clean_commands)
        primary = action.get("command")
        if isinstance(primary, list):
            primary = " ; ".join(str(item).strip() for item in primary if str(item).strip())
        elif primary is not None and not isinstance(primary, str):
            primary = str(primary)
        return primary or action.get("path") or action.get("url") or action.get("summary", "")

    def _normalize_for_compare(self, text: str) -> str:
        """对命令文本做轻量归一化，便于重复检测。"""
        text = (text or "").strip().lower()
        text = re.sub(r"\s+", " ", text)
        return text

    def _should_block_repeated_action(self, session, action: Dict[str, Any], command_display: str) -> Dict[str, Any] | None:
        """
        检测重复命令与失败重试过多的情况。
        命中后返回一个替代动作，让模型收到明确反馈并换策略。
        """
        if not session:
            return None

        tool = (action.get("tool") or "").strip().lower()
        if tool not in ("shell", "shell_batch", "mcp_tool"):
            return None

        normalized_command = self._normalize_for_compare(command_display)
        if not normalized_command:
            return None

        same_attempts = 0
        failed_attempts = 0
        for step in reversed(session.steps):
            if self._normalize_for_compare(step.command) != normalized_command:
                continue
            same_attempts += 1
            if not step.success:
                failed_attempts += 1

        if failed_attempts >= MAX_FAILED_COMMAND_ATTEMPTS:
            return {
                "tool": "shell",
                "command": (
                    "echo [策略提醒] 上一条命令或等价命令已连续失败多次，请不要原样重试。"
                    "请改用更小范围、更稳妥的命令，或先查看帮助后再执行。"
                ),
                "continue": True,
                "thought": f"检测到重复失败命令，已触发本地保护: {command_display[:120]}",
            }

        if same_attempts >= MAX_SAME_COMMAND_ATTEMPTS:
            return {
                "tool": "shell",
                "command": (
                    "echo [策略提醒] 同一命令已重复执行多次，请切换到验证或总结阶段，"
                    "避免继续消耗步骤和 token。"
                ),
                "continue": True,
                "thought": f"检测到重复命令，已提示模型换策略: {command_display[:120]}",
            }

        return None

    def _is_heavy_command(self, command_display: str) -> bool:
        """识别容易产生大量噪音输出的命令。"""
        normalized = self._normalize_for_compare(command_display)
        heavy_patterns = [
            "ps aux",
            "tasklist",
            "netstat -ano",
            "netstat -antp",
            "ss -an",
            "ss -tlnp",
            "find /",
            "dir /s",
            "wevtutil qe",
            "journalctl",
            "sc query",
            "schtasks /query",
        ]
        return any(pattern in normalized for pattern in heavy_patterns)

    def _review_action(self, session, action: Dict[str, Any], command_display: str) -> Dict[str, Any] | None:
        """
        本地 reviewer 层。
        在执行前基于阶段、覆盖率和命令形态做一次守门，减少偏题和高噪音动作。
        """
        if not session:
            return None

        tool = (action.get("tool") or "").strip().lower()
        phase = getattr(session, "phase", "collect")
        coverage = getattr(session, "evidence_coverage", {}) or {}
        done_count = sum(1 for value in coverage.values() if value == "done")

        if phase == "conclude" and tool != "finish":
            return {
                "tool": "shell",
                "command": (
                    "echo [Reviewer] 当前已进入 conclude 阶段。除非缺少关键证据，否则不要继续采集，"
                    "请优先整理最终结论。"
                ),
                "continue": True,
                "thought": f"reviewer 判断应优先收尾，而不是继续执行: {command_display[:120]}",
            }

        if phase == "verify" and self._is_heavy_command(command_display):
            return {
                "tool": "shell",
                "command": (
                    "echo [Reviewer] 当前处于 verify 阶段，检测到高噪音全量命令。"
                    "请缩小范围，只验证已发现的异常点。"
                ),
                "continue": True,
                "thought": f"reviewer 阻止 verify 阶段的全量高噪音命令: {command_display[:120]}",
            }

        if phase in ("collect", "verify") and done_count >= 5 and tool in ("shell", "shell_batch") and self._is_heavy_command(command_display):
            return {
                "tool": "shell",
                "command": (
                    "echo [Reviewer] 主要证据面已基本覆盖，这条命令收益较低且输出较大。"
                    "请转向定向验证或直接总结。"
                ),
                "continue": True,
                "thought": f"reviewer 认为当前命令性价比过低: {command_display[:120]}",
            }

        if tool == "finish":
            summary = (action.get("summary") or "").strip()
            if done_count < 3 and len(summary) < 80:
                return {
                    "tool": "shell",
                    "command": (
                        "echo [Reviewer] 证据覆盖仍然不足，且总结过短。"
                        "请至少补齐关键证据面或给出更具体的 finish 总结。"
                    ),
                    "continue": True,
                    "thought": "reviewer 拒绝过早 finish，原因是证据不足或总结过短",
                }

        return None

    def _infer_evidence_updates(self, task: str, action: Dict[str, Any], tool_result) -> Dict[str, str]:
        """根据任务、命令与输出粗略推断证据面覆盖情况。"""
        text_parts = [
            task or "",
            action.get("tool", "") or "",
            self._get_action_display(action),
            getattr(tool_result, "output", "") if tool_result else "",
        ]
        joined = " ".join(part if isinstance(part, str) else str(part) for part in text_parts).lower()
        updates: Dict[str, str] = {}

        mappings = {
            "accounts": ["passwd", "shadow", "whoami", "last", "net user", "useraccount", "localuser", "账号", "登录"],
            "processes": ["tasklist", "get-process", "wmic process", "ps ", "pgrep", "进程", "父进程"],
            "network": ["netstat", "ss ", "tcp", "udp", "端口", "连接", "firewall", "监听"],
            "persistence": ["crontab", "systemctl", "schtasks", "startup", "run\\", "计划任务", "启动项", "服务"],
            "logs": ["journalctl", "auth.log", "secure", "wevtutil", "win event", "日志", "event"],
            "files": ["find ", "dir ", "ls ", "system32", "authorized_keys", "tmp", "webshell", "文件"],
        }

        for key, keywords in mappings.items():
            if any(word in joined for word in keywords):
                updates[key] = "done" if getattr(tool_result, "success", False) else "partial"

        return updates

    def _finalize_report(self, task_id: str, task: str, os_type: str, steps: List[Dict], draft_summary: str = "") -> str:
        """独立调用模型生成最终总结，提高收尾稳定性。"""
        session = memory.get_session(task_id)
        finalize_prompt = build_finalize_prompt(
            task=task,
            os_type=os_type,
            phase=getattr(session, "phase", "conclude") if session else "conclude",
            evidence_coverage=getattr(session, "evidence_coverage", {}) if session else {},
            steps=steps,
            draft_summary=draft_summary or "",
        )
        messages = [{"role": "system", "content": finalize_prompt}]
        try:
            client, model, provider = self._get_client_and_model()
            logger.info(f"[Finalize] 使用模型生成最终报告: {provider} / {model}")
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.2,
                max_tokens=1800,
            )
            final_text = (response.choices[0].message.content or "").strip()
            return final_text or draft_summary or "未能生成最终报告，请查看执行步骤。"
        except Exception as e:
            logger.error(f"[Finalize] 最终报告生成失败: {e}")
            return draft_summary or f"最终总结生成失败，请结合执行步骤人工复核。错误: {e}"

    def _should_run_finalize(self, task_id: str, draft_summary: str, forced: bool = False) -> bool:
        """判断是否真的需要额外调用 finalize。"""
        if forced:
            return True

        session = memory.get_session(task_id)
        if not session:
            return True

        summary = (draft_summary or "").strip()
        done_count = sum(1 for value in session.evidence_coverage.values() if value == "done")
        has_sections = summary.count("## ") >= 3
        has_risk = "风险" in summary
        has_advice = "建议" in summary or "处置" in summary

        if not summary:
            return True
        if len(summary) < FINALIZE_MIN_SUMMARY_CHARS:
            return True
        if done_count < FINALIZE_MIN_DONE_EVIDENCE:
            return True
        if not has_sections:
            return True
        if not (has_risk and has_advice):
            return True
        return False

    def _compress_messages(self, messages: List[Dict], keep_recent: int = 10) -> List[Dict]:
        """
        上下文压缩：当消息轮次超过阈值时，将早期的历史轮次折叠成一条摘要。
        保留: system prompt(1条) + 初始任务(1条) + 最近N轮 + 压缩摘要(1条)
        """
        threshold = 2 + keep_recent * 2
        if len(messages) <= threshold:
            return messages

        system_msg = messages[0]
        task_msg = messages[1]
        recent = messages[-(keep_recent * 2):]
        old = messages[2:-(keep_recent * 2)]

        summary_lines = ["[已执行步骤摘要（早期历史）]"]
        i = 0
        while i < len(old) - 1:
            assistant_msg = old[i]
            user_msg = old[i + 1] if i + 1 < len(old) else None
            try:
                action = json.loads(assistant_msg["content"])
                tool = action.get("tool", "?")
                cmd = action.get("command") or action.get("path") or action.get("url") or ""
                result_text = user_msg["content"][:150] if user_msg else ""
                summary_lines.append(f"- [{tool}] {cmd[:80]} => {result_text}...")
            except Exception:
                pass
            i += 2

        compressed = {
            "role": "user",
            "content": "\n".join(summary_lines)
        }

        compressed_messages = [system_msg, task_msg, compressed] + list(recent)
        logger.debug(f"[上下文压缩] {len(messages)} 条 → {len(compressed_messages)} 条")
        return compressed_messages

    def _build_system_prompt(self, task: str, os_type: str = "linux") -> str:
        """构建带工具知识库的动态 System Prompt，根据 os_type 选择不同基底"""
        base_prompt = get_agent_base_prompt(os_type)
        known_tools = tool_knowledge.extract_tool_names_from_task(task)
        knowledge_hint = tool_knowledge.build_context_hint(known_tools if known_tools else None)
        mcp_hint = tool_registry.build_mcp_prompt(known_tools if known_tools else None)
        benign_hint = tool_knowledge.build_builtin_benign_hint(os_type)
        user_benign_hint = tool_knowledge.build_user_benign_hint(os_type)
        workflow_hint = build_agent_workflow_hint(task, os_type)

        parts = [base_prompt]
        if workflow_hint:
            parts.append(workflow_hint)
        if benign_hint:
            parts.append(benign_hint)
        if user_benign_hint:
            parts.append(user_benign_hint)
        if knowledge_hint:
            parts.append(knowledge_hint)
        if mcp_hint:
            parts.append(mcp_hint)
        return "".join(parts)

    def _handle_tool_learning(self, action: Dict[str, Any], tool_result, command_display: str):
        """
        处理工具学习逻辑：
        1. 如果命令失败，自动记录到知识库
        2. 如果 AI 主动上报了 learn_tool/learn_usage，更新知识库
        """
        tool = action.get("tool", "") or ""
        command_display = command_display if isinstance(command_display, str) else str(command_display)
        learn_tool = (action.get("learn_tool") or "").strip()
        learn_usage = action.get("learn_usage") or ""
        if isinstance(learn_usage, str):
            learn_usage = learn_usage.strip()

        if learn_tool and learn_usage:
            tool_knowledge.update_usage(learn_tool, learn_usage)
            logger.info(f"[ToolKnowledge] AI主动学习: {learn_tool} => {learn_usage}")

        if not tool_result.success and tool in ("shell", "shell_batch"):
            import re
            # 同时识别 Linux 路径（/root/check/whocheck）和 Windows 路径（C:\check\tool.exe）
            tool_names = re.findall(r'[/\\](\w+?)(?:\.\w+)?\s*', command_display)
            for tn in tool_names:
                if len(tn) > 3 and tn not in (
                    "bin", "usr", "root", "etc", "var", "tmp",
                    "Windows", "System32", "check", "Program",
                ):
                    tool_knowledge.record_error(
                        tool_name=tn,
                        failed_command=command_display,
                        error_output=tool_result.output[:300],
                    )
                    logger.info(f"[ToolKnowledge] 自动记录失败: {tn}")
                    break

    def run(self, task: str, task_id: str = None, os_type: str = "linux") -> Dict[str, Any]:
        """
        同步执行任务，返回完整执行报告。

        Args:
            task:     任务描述
            task_id:  可选，任务ID
            os_type:  目标系统类型 "linux" | "windows"
        """
        os_type = (os_type or "linux").lower()
        task_id = task_id or str(uuid.uuid4())[:8]
        session = memory.new_session(task_id, task)
        steps_summary = []

        logger.info(f"=== 开始执行任务 [{task_id}] [os={os_type}]: {task} ===")

        dynamic_system_prompt = self._build_system_prompt(task, os_type)
        memory.update_phase(task_id, "plan")

        for iteration in range(1, MAX_ITERATIONS + 1):
            logger.info(f"--- 第 {iteration} 轮 Agent Loop ---")

            messages = memory.build_messages(task_id, dynamic_system_prompt)
            session = memory.get_session(task_id)
            if session:
                phase_hint = self._build_phase_hint(session.phase)
                if phase_hint:
                    messages.append({"role": "user", "content": phase_hint})

            try:
                raw_response = self._call_ai(messages)
                logger.debug(f"AI 原始响应: {raw_response}")
            except Exception as e:
                logger.error(f"AI API 调用失败: {e}")
                memory.finish_session(task_id, "failed", f"AI API 错误: {e}")
                return self._build_report(task_id, steps_summary)

            action = normalize_action(parse_ai_response(raw_response), getattr(session, "phase", "collect") if session else "collect")
            
            tool = action.get("tool", "shell")
            self._normalize_shell_batch_action(action)
            thought = action.get("thought", "")
            should_continue = action.get("continue", True)
            command_display = self._get_action_display(action)

            logger.info(f"[AI thought] {thought}")
            logger.info(f"[AI action] tool={tool}, commands={action.get('commands')}, command={command_display}")

            blocked_action = self._should_block_repeated_action(memory.get_session(task_id), action, command_display)
            if blocked_action:
                logger.info(f"[ActionGuard] 阻止重复动作: {command_display}")
                action = blocked_action
                tool = action.get("tool", "shell")
                thought = action.get("thought", thought)
                should_continue = action.get("continue", True)
                command_display = self._get_action_display(action)

            reviewed_action = self._review_action(memory.get_session(task_id), action, command_display)
            if reviewed_action:
                logger.info(f"[Reviewer] 调整动作: {command_display}")
                action = reviewed_action
                tool = action.get("tool", "shell")
                thought = action.get("thought", thought)
                should_continue = action.get("continue", True)
                command_display = self._get_action_display(action)

            tool_result = dispatcher.dispatch(action)

            self._handle_tool_learning(action, tool_result, command_display)
            memory.update_evidence_coverage(task_id, self._infer_evidence_updates(task, action, tool_result))

            step = memory.record_step(
                task_id=task_id,
                step_no=iteration,
                thought=thought,
                tool=tool,
                command=command_display,
                result=tool_result.output,
                success=tool_result.success,
                status=getattr(tool_result, "status", "ok"),
                structured_summary=getattr(tool_result, "structured_summary", ""),
            )
            steps_summary.append({
                "step": iteration,
                "thought": thought,
                "tool": tool,
                "command": command_display,
                "result": tool_result.output,
                "success": tool_result.success,
                "status": getattr(tool_result, "status", "ok"),
                "note": getattr(tool_result, "note", ""),
                "structured_summary": getattr(tool_result, "structured_summary", ""),
            })

            logger.info(f"[Tool result] success={tool_result.success}: {tool_result.output[:200]}")

            next_phase = self._determine_phase(memory.get_session(task_id), iteration, action, tool_result)
            memory.update_phase(task_id, next_phase)

            if tool == "finish" or not should_continue:
                memory.update_phase(task_id, "conclude")
                if self._should_run_finalize(task_id, tool_result.output, forced=False):
                    final_answer = self._finalize_report(task_id, task, os_type, steps_summary, tool_result.output)
                else:
                    logger.info("[Finalize] 复用主循环总结，跳过额外 API 调用")
                    final_answer = tool_result.output
                memory.finish_session(task_id, "completed", final_answer)
                logger.info(f"=== 任务完成 [{task_id}] ===")
                return self._build_report(task_id, steps_summary, final_answer)

        logger.warning(f"任务 [{task_id}] 达到最大迭代次数 {MAX_ITERATIONS}，强制终止")
        memory.update_phase(task_id, "conclude")
        final_answer = self._finalize_report(task_id, task, os_type, steps_summary, f"主循环超出最大步骤限制 ({MAX_ITERATIONS} 步)，请基于已有证据收敛结论。")
        memory.finish_session(task_id, "aborted", final_answer)
        return self._build_report(task_id, steps_summary, final_answer)

    def stream_run(self, task: str, task_id: str = None, os_type: str = "linux", stop_event=None) -> Generator[Dict, None, None]:
        """
        流式执行任务，每步执行后 yield 一个事件。

        Args:
            task:        任务描述
            task_id:     可选，任务ID
            os_type:     目标系统类型 "linux" | "windows"
            stop_event:  可选，threading.Event，外部设置后任务将在下一轮循环前终止
        """
        os_type = (os_type or "linux").lower()
        task_id = task_id or str(uuid.uuid4())[:8]
        session = memory.new_session(task_id, task)
        steps_summary = []

        dynamic_system_prompt = self._build_system_prompt(task, os_type)
        memory.update_phase(task_id, "plan")

        yield {"event": "start", "task_id": task_id, "task": task, "os_type": os_type}

        for iteration in range(1, MAX_ITERATIONS + 1):

            # ── 停止检查（循环开始）────────────────────────────────
            if stop_event is not None and stop_event.is_set():
                logger.info(f"[Agent] 任务 [{task_id}] 收到停止信号，提前终止")
                memory.finish_session(task_id, "stopped", "用户手动停止任务")
                yield {"event": "stopped", "task_id": task_id, "message": "任务已被用户停止", "steps": steps_summary}
                return
            # ─────────────────────────────────────────────────────

            messages = memory.build_messages(task_id, dynamic_system_prompt)
            session = memory.get_session(task_id)
            if session:
                phase_hint = self._build_phase_hint(session.phase)
                if phase_hint:
                    messages.append({"role": "user", "content": phase_hint})

            try:
                # 传入 stop_event，AI 等待期间也能响应停止
                raw_response = self._call_ai(messages, stop_event=stop_event)
            except StopIteration:
                memory.finish_session(task_id, "stopped", "用户手动停止任务")
                yield {"event": "stopped", "task_id": task_id, "message": "任务已被用户停止（AI调用中断）", "steps": steps_summary}
                return
            except Exception as e:
                yield {"event": "error", "message": f"AI API 错误: {e}"}
                memory.finish_session(task_id, "failed", str(e))
                return

            action = normalize_action(parse_ai_response(raw_response), getattr(session, "phase", "collect") if session else "collect")
            
            tool = action.get("tool", "shell")
            self._normalize_shell_batch_action(action)
            thought = action.get("thought", "")
            should_continue = action.get("continue", True)
            command_display = self._get_action_display(action)

            # ── 停止检查（AI 解析后、工具执行前）─────────────────
            if stop_event is not None and stop_event.is_set():
                memory.finish_session(task_id, "stopped", "用户手动停止任务")
                yield {"event": "stopped", "task_id": task_id, "message": "任务已被用户停止", "steps": steps_summary}
                return
            # ─────────────────────────────────────────────────────

            yield {
                "event": "thinking",
                "step": iteration,
                "thought": thought,
                "tool": tool,
                "phase": getattr(session, "phase", "plan") if session else "plan",
                "command": action.get("commands") or command_display,
            }

            blocked_action = self._should_block_repeated_action(memory.get_session(task_id), action, command_display)
            if blocked_action:
                logger.info(f"[ActionGuard] 阻止重复动作: {command_display}")
                action = blocked_action
                tool = action.get("tool", "shell")
                thought = action.get("thought", thought)
                should_continue = action.get("continue", True)
                command_display = self._get_action_display(action)

            reviewed_action = self._review_action(memory.get_session(task_id), action, command_display)
            if reviewed_action:
                logger.info(f"[Reviewer] 调整动作: {command_display}")
                action = reviewed_action
                tool = action.get("tool", "shell")
                thought = action.get("thought", thought)
                should_continue = action.get("continue", True)
                command_display = self._get_action_display(action)

            tool_result = dispatcher.dispatch(action)

            # ── 停止检查（工具执行后）─────────────────────────────
            if stop_event is not None and stop_event.is_set():
                memory.finish_session(task_id, "stopped", "用户手动停止任务")
                yield {"event": "stopped", "task_id": task_id, "message": "任务已被用户停止", "steps": steps_summary}
                return
            # ─────────────────────────────────────────────────────

            self._handle_tool_learning(action, tool_result, command_display)
            memory.update_evidence_coverage(task_id, self._infer_evidence_updates(task, action, tool_result))

            memory.record_step(
                task_id=task_id,
                step_no=iteration,
                thought=thought,
                tool=tool,
                command=command_display,
                result=tool_result.output,
                success=tool_result.success,
                status=getattr(tool_result, "status", "ok"),
                structured_summary=getattr(tool_result, "structured_summary", ""),
            )

            steps_summary.append({
                "step": iteration,
                "thought": thought,
                "tool": tool,
                "command": command_display,
                "result": tool_result.output,
                "success": tool_result.success,
                "status": getattr(tool_result, "status", "ok"),
                "note": getattr(tool_result, "note", ""),
                "structured_summary": getattr(tool_result, "structured_summary", ""),
            })

            yield {
                "event": "step_result",
                "step": iteration,
                "tool": tool,
                "phase": getattr(memory.get_session(task_id), "phase", "plan") if memory.get_session(task_id) else "plan",
                "command": command_display,
                "result": tool_result.output,
                "success": tool_result.success,
                "status": getattr(tool_result, "status", "ok"),
                "note": getattr(tool_result, "note", ""),
                "structured_summary": getattr(tool_result, "structured_summary", ""),
            }

            next_phase = self._determine_phase(memory.get_session(task_id), iteration, action, tool_result)
            memory.update_phase(task_id, next_phase)

            if tool == "finish" or not should_continue:
                memory.update_phase(task_id, "conclude")
                if self._should_run_finalize(task_id, tool_result.output, forced=False):
                    final_answer = self._finalize_report(task_id, task, os_type, steps_summary, tool_result.output)
                else:
                    logger.info("[Finalize] 复用主循环总结，跳过额外 API 调用")
                    final_answer = tool_result.output
                memory.finish_session(task_id, "completed", final_answer)
                yield {
                    "event": "done",
                    "task_id": task_id,
                    "final_answer": final_answer,
                    "steps": steps_summary,
                }
                return

        memory.update_phase(task_id, "conclude")
        final_answer = self._finalize_report(task_id, task, os_type, steps_summary, f"主循环超出最大步骤限制 ({MAX_ITERATIONS} 步)，请基于已有证据收敛结论。")
        memory.finish_session(task_id, "aborted", final_answer)
        yield {
            "event": "done",
            "task_id": task_id,
            "final_answer": final_answer,
            "steps": steps_summary,
        }

    def _build_report(self, task_id: str, steps: List[Dict], final_answer: str = "") -> Dict:
        session = memory.get_session(task_id)
        return {
            "task_id": task_id,
            "task": session.task if session else "",
            "status": session.status if session else "unknown",
            "phase": session.phase if session else "unknown",
            "evidence_coverage": session.evidence_coverage if session else {},
            "steps": steps,
            "final_answer": final_answer,
            "duration": session.duration() if session else 0,
            "total_steps": len(steps),
        }


# 全局 Agent 实例
agent = LinuxAgent()


# ─── CLI 直接运行 ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "查看系统磁盘使用情况"
    print(f"\n🤖 AI Linux Agent 启动\n任务: {task}\n{'='*50}")

    result = agent.run(task)

    print(f"\n{'='*50}")
    print(f"✅ 任务完成 | 共 {result['total_steps']} 步 | 耗时 {result['duration']}s")
    print(f"\n最终结果:\n{result['final_answer']}")
    print(f"\n执行步骤:")
    for step in result["steps"]:
        status = "✓" if step["success"] else "✗"
        print(f"  [{step['step']}] {status} [{step['tool']}] {step['command']}")
        print(f"       思考: {step['thought'][:80]}")
        print(f"       结果: {step['result'][:150]}\n")
