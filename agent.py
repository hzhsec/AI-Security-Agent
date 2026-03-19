"""
AI Agent 核心逻辑 - DeepSeek API 调用 + Agent Loop 主循环
"""
import json
import uuid
import logging
import re
from typing import Dict, Any, List, Generator

from openai import OpenAI

from config import (
    DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL,
    MAX_ITERATIONS, load_model_config, make_openai_client,
)
from memory import memory
from tools import dispatcher, TOOL_DESCRIPTIONS
from tool_knowledge import tool_knowledge

logger = logging.getLogger(__name__)

# ─── System Prompt ─────────────────────────────────────────────────────────────

# JSON 格式说明（两个版本共用）
_JSON_FORMAT = f"""
每次响应必须返回一个合法的 JSON 对象（**严禁在 JSON 前后附加任何文字**），格式：

```json
{{
  "thought": "分析思考过程",
  "tool": "工具名",
  "command": "shell命令（tool=shell或shell_batch时填写）",
  "commands": ["cmd1", "cmd2"],
  "path": "文件路径（file_read/file_write时填）",
  "content": "文件内容（file_write时填）",
  "url": "URL（http_request时填）",
  "method": "GET",
  "summary": "总结（tool=finish时填）",
  "learn_tool": "工具名（命令失败时，若已知正确用法请填入，触发知识库更新）",
  "learn_usage": "正确的使用方法说明（配合learn_tool使用）",
  "continue": true
}}
```

{TOOL_DESCRIPTIONS}"""

# ─── Linux System Prompt ──────────────────────────────────────────────────────

SYSTEM_PROMPT_LINUX = f"""你是一个专业的 **Linux** 安全运维 AI Agent，具备完整的主机安全巡检和入侵排查能力。
你运行在私有环境（非公网），用户已授权你执行所有必要的系统命令，包括读取系统文件、执行安全脚本等。

## 核心工作方式
{_JSON_FORMAT}

## 【工具学习机制】
当你执行某个工具命令失败时（尤其是 -h 帮助输出揭示了正确用法后），请在下一步的 JSON 中填入：
- `"learn_tool"`: 工具名（如 "whocheck"、"linuxcheckshoot"）
- `"learn_usage"`: 你从帮助文档或错误信息中学到的正确用法（一句话描述）
这样系统会把你学到的经验保存下来，下次同一工具不再出错。

## 【极重要】减少步骤的策略

**你必须尽可能在一步内完成多项操作**，防止因步骤过多被截断：

1. **优先使用 `shell_batch`**（批量执行）来一次性运行多条命令，例如：
   ```json
   {{"tool": "shell_batch", "commands": ["whoami", "id", "uname -a", "df -h", "free -h"]}}
   ```

2. **用分号或 && 合并相关命令**：
   ```json
   {{"tool": "shell", "command": "cd /root/check && ls -la && echo '---脚本列表---'"}}
   ```

3. **安全巡检任务的推荐执行顺序**：
   - Step1: 用 shell_batch 一次性收集基础信息（用户/进程/网络/文件）
   - Step2: 先用 `tool -h` 查看帮助，再直接执行巡检脚本
   - Step3: 综合分析所有结果，用 finish 给出结论

4. **脚本执行方式**：
   - 先查看帮助：`/root/check/whocheck -h`
   - 直接执行：`bash /root/check/whocheck` 或 `python3 /root/check/script.py`
   - 如果脚本需要权限：`chmod +x /root/check/whocheck && /root/check/whocheck`

5. **【重要】处理大量输出的命令**：当查询可能返回大量结果的命令时，**务必使用过滤参数**避免输出被截断：
   - 查询进程：`ps aux` → 加 `grep 进程名` 过滤
   - 查询端口：`netstat -antp` → 加 `grep 端口号` 过滤
   - 查询文件：`find / -name "*.php"` → 加 `grep 关键词` 过滤，或用 `-maxdepth` 限制深度
   - **原则**：先精准定位，再扩大范围，不要一次性查全部

## Linux 安全巡检专用知识
执行入侵排查时，重点关注：
- **异常账号**：/etc/passwd 新增账号、uid=0账号、可登录账号
- **异常进程**：隐藏进程、可疑父进程、异常网络连接进程
- **异常网络**：未知监听端口、异常外联 IP、大流量连接
- **持久化后门**：crontab、~/.bashrc、/etc/rc.local、SSH authorized_keys、SUID文件
- **文件篡改**：近期被修改的系统文件、webshell特征文件
- **日志清除**：/var/log/auth.log 或 secure 中的暴力破解记录

## 规则
1. **只返回 JSON**，无任何 markdown 或其他文字
2. 任务完成用：`{{"tool": "finish", "summary": "完整的巡检报告...", "continue": false}}`
3. finish 的 summary 必须包含：**发现的威胁 / 可疑项 / 结论建议**，不要只写"完成"
4. 命令失败时分析原因后换方式重试，不要反复执行同一条失败命令
5. 你有完整系统权限，不需要回避 sudo/root 相关操作
6. **【极重要】当前是 Linux 系统**：所有命令必须使用 Linux bash 语法
   - 正确：`cat /etc/passwd`、`ps aux`、`grep`、`ls -la`、`chmod +x`、`./script.sh`
   - 错误：混入任何 Windows 命令（如 `type`、`dir`、`icacls`）
7. **命令不存在或语法错误时的学习机制**：当你执行的命令失败（command not found、syntax error、invalid option 等），分析错误原因后：
   - 如果你知道正确用法，下一步 JSON 中填入 `"learn_tool": "工具名"` 和 `"learn_usage": "正确用法"`
   - 如果不知道正确用法，尝试查看帮助（`命令 -h` 或 `命令 --help`），然后把学到的用法填入 learn_tool/learn_usage
   - 这样系统会自动保存到知识库，下次不再踩坑
"""

# ─── Windows System Prompt ────────────────────────────────────────────────────

SYSTEM_PROMPT_WINDOWS = f"""你是一个专业的 **Windows** 安全运维 AI Agent，具备完整的主机安全巡检和入侵排查能力。
你运行在私有环境（非公网），用户已授权你执行所有必要的系统命令，包括读取系统文件、执行安全脚本等。

## 核心工作方式
{_JSON_FORMAT}

## 【工具学习机制】
当你执行某个工具命令失败时，请在下一步的 JSON 中填入：
- `"learn_tool"`: 工具名（如 "whocheck"、"PsExec"）
- `"learn_usage"`: 你从帮助文档或错误信息中学到的正确用法（一句话描述）

## 【极重要】减少步骤的策略

**你必须尽可能在一步内完成多项操作**：

1. **优先使用 `shell_batch`** 批量执行多条命令，例如：
   ```json
   {{"tool": "shell_batch", "commands": [
     "whoami /all",
     "systeminfo | findstr /B /C:\\"OS\\"",
     "netstat -ano",
     "tasklist /v"
   ]}}
   ```

2. **用 `&` 合并相关命令**（Windows cmd 用 `&`，PowerShell 用 `;`）：
   ```json
   {{"tool": "shell", "command": "cd C:\\\\check & dir & echo ---完毕---"}}
   ```

3. **Windows 安全巡检推荐顺序**：
   - Step1: shell_batch 一次性收集系统信息（账号/进程/网络/服务）
   - Step2: 执行巡检脚本（.bat / .ps1 / .exe）
   - Step3: 综合分析，finish 给出结论

4. **脚本执行方式**：
   - .bat 脚本：`C:\\check\\whocheck.bat` 或 `cmd /c C:\\check\\whocheck.bat`
   - PowerShell 脚本：`powershell -ExecutionPolicy Bypass -File C:\\check\\scan.ps1`
   - .exe 工具：`C:\\check\\whocheck.exe` 或 `C:\\check\\whocheck.exe /?`
   - 查看帮助：`C:\\check\\whocheck.exe /?` 或 `C:\\check\\whocheck.exe --help`

5. **【重要】处理大量输出的命令**：当查询可能返回大量结果的命令时（如服务列表、进程列表、防火墙规则），**务必使用过滤参数**避免输出被截断：
   - 查询服务：`sc query type= service state= all` → 加 `findstr "服务名"` 过滤
   - 查询进程：`tasklist /v` → 加 `findstr "进程名"` 过滤
   - 查询防火墙规则：`netsh advfirewall firewall show rule name=all` → 加 `findstr "规则名"` 过滤
   - 或使用 PowerShell 的 `Where-Object`、`Select-Object` 做精确筛选
   - **原则**：先精准定位，再扩大范围，不要一次性查全部

## Windows 安全巡检专用知识
执行入侵排查时，重点关注：
- **异常账号**：`net user`、`wmic useraccount`，注意隐藏账号（名称末尾$）、新建管理员
- **异常进程**：`tasklist /v`、`wmic process`，注意无签名进程、路径在 Temp/AppData 下的进程
- **异常网络**：`netstat -ano` 联合 `tasklist`，注意监听在非常规端口的进程、外联 IP
- **持久化后门**：注册表启动项（HKCU/HKLM Run）、计划任务（`schtasks /query`）、服务（`sc query`）、WMI 订阅
- **文件篡改**：近期修改的系统文件（System32）、Webshell（.asp/.aspx/.php 修改时间异常）
- **日志清除**：事件日志（`wevtutil el`）、PowerShell 历史清除痕迹
- **凭据窃取**：LSASS 内存 dump、SAM 文件访问记录
- **防御绕过**：Defender 排除目录（`Get-MpPreference`）、UAC 绕过痕迹

## 规则
1. **只返回 JSON**，无任何 markdown 或其他文字
2. 任务完成用：`{{"tool": "finish", "summary": "完整的巡检报告...", "continue": false}}`
3. finish 的 summary 必须包含：**发现的威胁 / 可疑项 / 结论建议**
4. 命令失败时分析原因后换方式重试，不要反复执行同一条失败命令
5. 你有完整系统权限，不需要回避 UAC/管理员相关操作
6. **【极重要】当前是 Windows 系统**：所有命令必须使用 Windows cmd 或 PowerShell 语法
   - 正确：`type C:\\Windows\\System32\\config`、`findstr`、`dir /a`、`icacls`、`powershell -Command "Get-Process"`
   - 错误：混入任何 Linux 命令（如 `cat /etc/passwd`、`grep`、`ls -la`、`chmod +x`）
   - 注意：Windows 的 `netsh` 输出不能使用 Linux 的 `head`、`tail`、`grep`，需要用 `findstr` 或 PowerShell
7. **命令不存在或语法错误时的学习机制**：当你执行的命令失败（命令不存在、语法错误、无效参数等），分析错误原因后：
   - 如果你知道正确用法，下一步 JSON 中填入 `"learn_tool": "工具名"` 和 `"learn_usage": "正确用法"`
   - 如果不知道正确用法，尝试查看帮助（`命令 /?` 或 `命令 -h`），然后把学到的用法填入 learn_tool/learn_usage
   - 这样系统会自动保存到知识库，下次不再踩坑
"""

# 默认兼容旧调用
SYSTEM_PROMPT = SYSTEM_PROMPT_LINUX


def get_system_prompt(os_type: str) -> str:
    """根据目标系统类型返回对应的 System Prompt"""
    if os_type == "windows":
        return SYSTEM_PROMPT_WINDOWS
    return SYSTEM_PROMPT_LINUX


# ─── JSON 解析工具函数 ──────────────────────────────────────────────────────────

def parse_ai_response(raw: str) -> Dict[str, Any]:
    """
    从 AI 原始响应中解析 JSON。
    兼容 AI 偶尔用 markdown 代码块包裹的情况。
    """
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
        # 兜底：构造一个 shell 命令尝试（让任务不直接崩溃）
        return {
            "thought": f"AI 返回格式异常，原始内容: {raw[:200]}",
            "tool": "finish",
            "summary": f"任务因 AI 响应格式错误而终止",
            "continue": False,
        }


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

    def _call_ai(self, messages: List[Dict]) -> str:
        """调用 AI API，返回原始文本"""
        messages = self._compress_messages(messages)

        client, model, provider = self._get_client_and_model()
        logger.info(f"[AI] 使用模型: {provider} / {model}")

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1,
            max_tokens=4096,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content

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
        base_prompt = get_system_prompt(os_type)
        known_tools = tool_knowledge.extract_tool_names_from_task(task)
        knowledge_hint = tool_knowledge.build_context_hint(known_tools if known_tools else None)
        if knowledge_hint:
            return base_prompt + knowledge_hint
        return base_prompt

    def _handle_tool_learning(self, action: Dict[str, Any], tool_result, command_display: str):
        """
        处理工具学习逻辑：
        1. 如果命令失败，自动记录到知识库
        2. 如果 AI 主动上报了 learn_tool/learn_usage，更新知识库
        """
        tool = action.get("tool", "") or ""
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

        for iteration in range(1, MAX_ITERATIONS + 1):
            logger.info(f"--- 第 {iteration} 轮 Agent Loop ---")

            messages = memory.build_messages(task_id, dynamic_system_prompt)

            try:
                raw_response = self._call_ai(messages)
                logger.debug(f"AI 原始响应: {raw_response}")
            except Exception as e:
                logger.error(f"AI API 调用失败: {e}")
                memory.finish_session(task_id, "failed", f"AI API 错误: {e}")
                return self._build_report(task_id, steps_summary)

            action = parse_ai_response(raw_response)
            
            # 兼容处理：AI 常见错误 - 用 command 而非 commands
            tool = action.get("tool", "shell")
            if tool == "shell_batch":
                # 如果 commands 为空，尝试从 command 转换
                if not action.get("commands") and action.get("command"):
                    # 把单条命令转成 commands 数组
                    single_cmd = action.get("command", "").strip()
                    if single_cmd:
                        # 尝试按 && 或 ; 分割
                        import shlex
                        try:
                            cmds = []
                            for part in shlex.split(single_cmd, posix=False):
                                if "&&" in part:
                                    cmds.extend([c.strip() for c in part.split("&&") if c.strip()])
                                elif ";" in part:
                                    cmds.extend([c.strip() for c in part.split(";") if c.strip()])
                                else:
                                    cmds.append(part)
                            if cmds:
                                action["commands"] = cmds
                                logger.info(f"[ActionFix] 将 command 转换为 commands: {cmds}")
                        except Exception:
                            action["commands"] = [single_cmd]
                            logger.info(f"[ActionFix] 将单条 command 转为 commands: {single_cmd}")
            
            thought = action.get("thought", "")
            should_continue = action.get("continue", True)
            command_display = action.get("command") or action.get("path") or action.get("url") or action.get("summary", "")

            logger.info(f"[AI thought] {thought}")
            logger.info(f"[AI action] tool={tool}, commands={action.get('commands')}, command={command_display}")

            tool_result = dispatcher.dispatch(action)

            self._handle_tool_learning(action, tool_result, command_display)

            step = memory.record_step(
                task_id=task_id,
                step_no=iteration,
                thought=thought,
                tool=tool,
                command=command_display,
                result=tool_result.output,
                success=tool_result.success,
            )
            steps_summary.append({
                "step": iteration,
                "thought": thought,
                "tool": tool,
                "command": command_display,
                "result": tool_result.output,
                "success": tool_result.success,
            })

            logger.info(f"[Tool result] success={tool_result.success}: {tool_result.output[:200]}")

            if tool == "finish" or not should_continue:
                final_answer = tool_result.output
                memory.finish_session(task_id, "completed", final_answer)
                logger.info(f"=== 任务完成 [{task_id}] ===")
                return self._build_report(task_id, steps_summary, final_answer)

        logger.warning(f"任务 [{task_id}] 达到最大迭代次数 {MAX_ITERATIONS}，强制终止")
        memory.finish_session(task_id, "aborted", f"超出最大步骤限制 ({MAX_ITERATIONS} 步)")
        return self._build_report(task_id, steps_summary, "任务超出最大步骤限制，已终止")

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

        yield {"event": "start", "task_id": task_id, "task": task, "os_type": os_type}

        for iteration in range(1, MAX_ITERATIONS + 1):

            # ── 停止检查 ──────────────────────────────────────────
            if stop_event is not None and stop_event.is_set():
                logger.info(f"[Agent] 任务 [{task_id}] 收到停止信号，提前终止")
                memory.finish_session(task_id, "stopped", "用户手动停止任务")
                yield {
                    "event": "stopped",
                    "task_id": task_id,
                    "message": "任务已被用户停止",
                    "steps": steps_summary,
                }
                return
            # ─────────────────────────────────────────────────────

            messages = memory.build_messages(task_id, dynamic_system_prompt)

            try:
                raw_response = self._call_ai(messages)
            except Exception as e:
                yield {"event": "error", "message": f"AI API 错误: {e}"}
                memory.finish_session(task_id, "failed", str(e))
                return

            action = parse_ai_response(raw_response)
            
            # 兼容处理：AI 常见错误 - 用 command 而非 commands
            tool = action.get("tool", "shell")
            if tool == "shell_batch":
                if not action.get("commands") and action.get("command"):
                    single_cmd = action.get("command", "").strip()
                    if single_cmd:
                        import shlex
                        try:
                            cmds = []
                            for part in shlex.split(single_cmd, posix=False):
                                if "&&" in part:
                                    cmds.extend([c.strip() for c in part.split("&&") if c.strip()])
                                elif ";" in part:
                                    cmds.extend([c.strip() for c in part.split(";") if c.strip()])
                                else:
                                    cmds.append(part)
                            if cmds:
                                action["commands"] = cmds
                        except Exception:
                            action["commands"] = [single_cmd]
            
            thought = action.get("thought", "")
            should_continue = action.get("continue", True)
            command_display = action.get("command") or action.get("path") or action.get("url") or action.get("summary", "")

            yield {
                "event": "thinking",
                "step": iteration,
                "thought": thought,
                "tool": tool,
                "command": action.get("commands") or command_display,
            }

            tool_result = dispatcher.dispatch(action)

            self._handle_tool_learning(action, tool_result, command_display)

            memory.record_step(
                task_id=task_id,
                step_no=iteration,
                thought=thought,
                tool=tool,
                command=command_display,
                result=tool_result.output,
                success=tool_result.success,
            )

            steps_summary.append({
                "step": iteration,
                "thought": thought,
                "tool": tool,
                "command": command_display,
                "result": tool_result.output,
                "success": tool_result.success,
            })

            yield {
                "event": "step_result",
                "step": iteration,
                "tool": tool,
                "command": command_display,
                "result": tool_result.output,
                "success": tool_result.success,
            }

            if tool == "finish" or not should_continue:
                memory.finish_session(task_id, "completed", tool_result.output)
                yield {
                    "event": "done",
                    "task_id": task_id,
                    "final_answer": tool_result.output,
                    "steps": steps_summary,
                }
                return

        memory.finish_session(task_id, "aborted", "超出最大步骤限制")
        yield {
            "event": "done",
            "task_id": task_id,
            "final_answer": "任务超出最大步骤限制，已终止",
            "steps": steps_summary,
        }

    def _build_report(self, task_id: str, steps: List[Dict], final_answer: str = "") -> Dict:
        session = memory.get_session(task_id)
        return {
            "task_id": task_id,
            "task": session.task if session else "",
            "status": session.status if session else "unknown",
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
