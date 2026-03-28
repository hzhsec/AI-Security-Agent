"""
工具知识库 - 记录和学习各种 Linux 工具的使用方法

三种学习方式：
1. 被动学习：Agent 执行任务时命令失败 → 自动记录错误 → 下次注入 System Prompt
2. 主动探索：用户发起"让 AI 自学某工具" → AI 自己跑命令测试 → 把用法总结存档
3. 外部导入：用户先从网上搜索工具用法 → 粘贴参考资料 → AI 基于资料学习

下次遇到同一工具时，自动注入到 System Prompt，不再出错。
"""
import json
import os
import time
import logging
import re
import threading
from typing import Dict, List, Optional, Generator

logger = logging.getLogger(__name__)

KNOWLEDGE_FILE = "tool_knowledge.json"


def clean_web_content(raw_text: str) -> str:
    """
    清理从网页粘贴的杂乱内容，提取有价值的信息。

    处理的内容包括：
    - HTML 标签残留
    - 多余的空白字符和换行
    - 代码块标记
    - 常见的网页噪音
    """
    if not raw_text:
        return ""

    text = raw_text

    # 1. 移除 HTML 标签
    text = re.sub(r'<[^>]+>', '', text)

    # 2. 移除代码块标记 ```python ``` 等
    text = re.sub(r'```[\w]*', '', text)

    # 3. 移除多余空白：多个空格/换行合并为一个
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)

    # 4. 移除行首行尾空白
    lines = [line.strip() for line in text.split('\n')]
    text = '\n'.join(lines)

    # 5. 移除空行
    lines = [line for line in text.split('\n') if line.strip()]
    text = '\n'.join(lines)

    return text.strip()


def extract_commands_from_text(text: str) -> List[str]:
    """
    从文本中提取可能的命令示例。
    识别 $ 开头或代码块中的命令行。
    """
    commands = []

    # 匹配 $ 开头或 # 开头（root）的命令行
    cmd_patterns = [
        r'^[\$#]\s*(.+)',           # $ command 或 # command
        r'^>>>\s*(.+)',              # >>> command (python)
    ]

    for line in text.split('\n'):
        line = line.strip()
        for pattern in cmd_patterns:
            match = re.match(pattern, line, re.MULTILINE)
            if match:
                cmd = match.group(1).strip()
                if cmd and len(cmd) > 2:
                    commands.append(cmd)
                break

    return commands




# 工具自学任务的 System Prompt
_LEARN_SYSTEM_PROMPT = """你是一个 Linux/Windows 工具学习专家。你的任务是：分析用户提供的参考资料，验证命令是否有效，并理解每个命令**怎么使用**。

## 你的工具
- **shell**: 执行命令验证是否有效
- **file_read**: 读取文件内容（用于分析脚本源码）

## 输入信息
用户会提供：
1. 工具名称和路径
2. 参考资料（从网上搜索的使用说明，可能格式杂乱）

## 你的任务流程

### 第一步：分析参考资料 + 查看帮助
- 从资料中提取所有可能的命令用法
- 先执行 `工具路径 -h` 或 `工具路径 --help` 确认工具的完整选项
- 识别命令格式、参数、选项及其作用

### 第二步：逐一验证命令（核心！）
- **对每个提取的命令实际执行验证**
- 执行你认为可能有效的命令，记录结果
- **理解并记录这个命令的作用**：是做什么的？什么场景用？

### 第三步：整理结果（关键！）
对于每个验证成功的命令，你必须知道：
- 这个命令的作用是什么？
- 需要什么参数？
- 什么场景下使用？
- 有没有副作用？

## 输出格式
每次响应返回 JSON：

```json
{
  "thought": "你当前的分析：命令xxx的作用是xxx，验证它是否能正常运行",
  "tool": "shell" 或 "file_read" 或 "finish",
  "command": "要执行的验证命令",
  "path": "要读取的文件路径（仅 file_read 有效）",
  "note": "这个命令的作用说明（用于后续整理）",
  "continue": true
}
```

**验证命令时，thought 必须包含**：
- 命令的作用
- 你期望得到什么结果

**结束时（finish）**：
```json
{
  "thought": "已完成所有命令验证和使用分析",
  "tool": "finish",
  "summary": "工具功能简介（50字内）",
  "usage_hints": [
    "命令1 - 作用说明",
    "命令2 参数 - 作用说明",
    ...
  ],
  "help_summary": "帮助信息摘要，包括主要选项的作用",
  "continue": false
}
```

## usage_hints 格式要求
每个条目必须是：**命令 + 作用说明**，例如：
- `whocheck - 检查系统用户登录状态`
- `whocheck -a - 显示所有用户的详细信息`
- `whocheck -s - 仅显示登录名和时间`

## 重要规则
1. **必须实际执行命令验证**，不能只是纸上谈兵
2. **每个命令都要知道怎么使用**：执行后分析输出，理解命令的作用
3. **成功标准**：命令执行无报错，且有合理输出
4. **usage_hints 必须包含作用说明**，格式为"命令 - 作用"
5. **最多 30 步**，每个命令验证都算一步
6. **优先验证 -h/--help**，理解所有选项后再验证具体命令
7. **如果已有用法记录**：继续探索新的命令，不要重复已验证的
8. 只返回 JSON，不要在 JSON 前后加任何文字
"""


class LearnTask:
    """工具自学任务状态"""
    def __init__(self, tool_name: str, tool_path: str):
        self.tool_name = tool_name
        self.tool_path = tool_path
        self.status = "running"   # running / done / failed
        self.steps = []
        self.result = None
        self.error = None
        self.started_at = time.time()
        self.finished_at = None

    def to_dict(self):
        return {
            "tool_name": self.tool_name,
            "tool_path": self.tool_path,
            "status": self.status,
            "steps": self.steps,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed": round((self.finished_at or time.time()) - self.started_at, 1),
        }


class ToolKnowledge:
    """
    工具知识库：
    - 每个工具名对应一条知识记录
    - 包含：正确用法示例、已知错误及解决方案、帮助文本摘要
    - 支持 AI 主动探索学习
    """

    def __init__(self):
        self.knowledge: Dict[str, dict] = {}
        # 正在进行中的自学任务 {tool_name: LearnTask}
        self._learn_tasks: Dict[str, LearnTask] = {}
        self._lock = threading.RLock()
        self._load()

    # ── 基础 CRUD ──────────────────────────────────────────────────────────────

    def _load(self):
        try:
            with open(KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            with self._lock:
                self.knowledge = data
            logger.info(f"[ToolKnowledge] 已加载 {len(self.knowledge)} 个工具知识")
        except FileNotFoundError:
            with self._lock:
                self.knowledge = {}
        except Exception as e:
            logger.warning(f"[ToolKnowledge] 加载失败: {e}")
            with self._lock:
                self.knowledge = {}

    def _save(self):
        try:
            with self._lock:
                temp_file = f"{KNOWLEDGE_FILE}.tmp"
                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(self.knowledge, f, ensure_ascii=False, indent=2)
                os.replace(temp_file, KNOWLEDGE_FILE)
        except Exception as e:
            logger.error(f"[ToolKnowledge] 保存失败: {e}")

    def get(self, tool_name: str) -> Optional[dict]:
        with self._lock:
            return self.knowledge.get(tool_name)

    def list_all(self) -> List[dict]:
        result = []
        with self._lock:
            for name, rec in self.knowledge.items():
                result.append({"tool": name, **rec})
        return result

    def delete(self, tool_name: str) -> bool:
        with self._lock:
            if tool_name in self.knowledge:
                del self.knowledge[tool_name]
                self._save()
                return True
            return False

    # ── 导入/导出 ─────────────────────────────────────────────────────────────

    def export_all(self) -> dict:
        """
        导出整个知识库为JSON格式。
        包含所有工具的用法、帮助信息、错误记录等。
        """
        return {
            "version": "1.0",
            "exported_at": time.time(),
            "tool_count": len(self.knowledge),
            "tools": self.knowledge
        }

    def export_tool(self, tool_name: str) -> Optional[dict]:
        """
        导出单个工具的知识。
        """
        rec = self.knowledge.get(tool_name)
        if not rec:
            return None
        return {
            "version": "1.0",
            "exported_at": time.time(),
            "tool": tool_name,
            **rec
        }

    def import_tool(self, tool_data: dict, mode: str = "merge") -> dict:
        """
        导入工具知识。

        参数:
            tool_data: 工具数据（可以是单个工具或包含多个工具的格式）
            mode: 导入模式
                - "merge": 合并（已存在则合并用法，不重复）
                - "replace": 替换（完全覆盖已有记录）

        返回:
            导入结果摘要
        """
        imported_count = 0
        skipped_count = 0

        # 支持两种格式：单个工具 或 多个工具（导出格式）
        if "tools" in tool_data:
            # 导出格式：{version, exported_at, tool_count, tools: {...}}
            tools_dict = tool_data["tools"]
        elif "tool" in tool_data and "usage_hints" in tool_data:
            # 单个工具格式
            tools_dict = {tool_data["tool"]: tool_data}
        else:
            return {"success": False, "message": "无效的导入格式"}

        for tool_name, rec in tools_dict.items():
            if not tool_name or not isinstance(rec, dict):
                continue

            if mode == "replace":
                # 完全替换
                self.knowledge[tool_name] = rec
                imported_count += 1
            else:
                # 合并模式
                existing = self.knowledge.get(tool_name)
                if existing:
                    # 合并 usage_hints（去重）
                    existing_hints = set(existing.get("usage_hints", []))
                    for hint in rec.get("usage_hints", []):
                        if hint and hint not in existing_hints:
                            existing.setdefault("usage_hints", []).append(hint)
                            existing_hints.add(hint)
                    # 合并 errors
                    existing.setdefault("errors", []).extend(rec.get("errors", []))
                    # 更新其他字段
                    for k, v in rec.items():
                        if k not in ("usage_hints", "errors", "tool") and v:
                            existing[k] = v
                    existing["updated_at"] = time.time()
                else:
                    self.knowledge[tool_name] = rec
                    imported_count += 1

        self._save()
        return {
            "success": True,
            "imported_count": imported_count,
            "skipped_count": skipped_count,
            "message": f"导入成功: {imported_count} 个工具"
        }

    # ── 被动学习接口 ───────────────────────────────────────────────────────────

    def record_error(self, tool_name: str, failed_command: str, error_output: str, fixed_command: str = ""):
        """记录命令失败情况"""
        rec = self.knowledge.setdefault(tool_name, {
            "tool": tool_name,
            "usage_hints": [],
            "errors": [],
            "updated_at": 0,
        })
        rec["errors"].append({
            "failed_command": failed_command,
            "error_output": error_output[:500],
            "fixed_command": fixed_command,
            "timestamp": time.time(),
        })
        rec["errors"] = rec["errors"][-10:]
        rec["updated_at"] = time.time()
        self._save()
        logger.info(f"[ToolKnowledge] 记录错误: {tool_name} | {failed_command}")

    def update_usage(self, tool_name: str, usage_hint: str, help_text: str = ""):
        """更新工具正确用法"""
        rec = self.knowledge.setdefault(tool_name, {
            "tool": tool_name,
            "usage_hints": [],
            "errors": [],
            "updated_at": 0,
        })
        if usage_hint and usage_hint not in rec["usage_hints"]:
            rec["usage_hints"].append(usage_hint)
            rec["usage_hints"] = rec["usage_hints"][-5:]
        if help_text:
            rec["help_summary"] = help_text[:800]
        rec["updated_at"] = time.time()
        self._save()
        logger.info(f"[ToolKnowledge] 更新用法: {tool_name}")

    def update_tool_path(self, tool_name: str, new_path: str) -> bool:
        """
        更新工具路径，并同步替换已记录用法中的旧路径前缀。
        仅替换完全匹配的旧路径文本，不改动命令参数说明。
        """
        with self._lock:
            rec = self.knowledge.get(tool_name)
            if not rec:
                return False

            old_path = (rec.get("tool_path") or "").strip()
            new_path = (new_path or "").strip()
            rec["tool_path"] = new_path

            if old_path and new_path and old_path != new_path:
                rec["usage_hints"] = [
                    hint.replace(old_path, new_path) if isinstance(hint, str) else hint
                    for hint in rec.get("usage_hints", [])
                ]

                for err in rec.get("errors", []):
                    if isinstance(err.get("failed_command"), str):
                        err["failed_command"] = err["failed_command"].replace(old_path, new_path)
                    if isinstance(err.get("fixed_command"), str):
                        err["fixed_command"] = err["fixed_command"].replace(old_path, new_path)

                if isinstance(rec.get("help_summary"), str):
                    rec["help_summary"] = rec["help_summary"].replace(old_path, new_path)
                if isinstance(rec.get("summary"), str):
                    rec["summary"] = rec["summary"].replace(old_path, new_path)

            rec["updated_at"] = time.time()
            self._save()
            return True

    # ── 外部参考资料导入 ─────────────────────────────────────────────────────────

    def import_web_reference(self, tool_name: str, raw_content: str) -> dict:
        """
        导入用户从网上搜索并粘贴的参考资料。

        处理流程：
        1. 清理杂乱的网页内容（HTML标签、多余空白等）
        2. 提取可能的命令示例
        3. 存储到知识库作为参考资料

        返回：处理结果摘要
        """
        # 清理内容
        cleaned = clean_web_content(raw_content)

        # 提取命令
        extracted_cmds = extract_commands_from_text(cleaned)

        # 获取或创建记录
        rec = self.knowledge.setdefault(tool_name, {
            "tool": tool_name,
            "usage_hints": [],
            "errors": [],
            "updated_at": 0,
        })

        # 存储原始参考资料（用于后续AI学习）
        rec["web_reference"] = {
            "raw": raw_content[:5000],      # 原始内容（保留格式）
            "cleaned": cleaned[:3000],      # 清理后内容
            "extracted_commands": extracted_cmds,  # 提取的命令
            "imported_at": time.time(),
        }

        # 如果提取到命令，也加入 usage_hints
        for cmd in extracted_cmds:
            if cmd and cmd not in rec.get("usage_hints", []):
                rec.setdefault("usage_hints", []).append(cmd)

        rec["updated_at"] = time.time()
        self._save()

        logger.info(f"[ToolKnowledge] 导入参考资料: {tool_name} ({len(extracted_cmds)} 条命令)")

        return {
            "tool_name": tool_name,
            "cleaned_length": len(cleaned),
            "extracted_commands_count": len(extracted_cmds),
            "commands": extracted_cmds[:5],  # 返回前5条
            "message": f"已导入参考资料，提取到 {len(extracted_cmds)} 条命令示例",
        }

    def get_web_reference(self, tool_name: str) -> Optional[dict]:
        """获取工具的参考资料"""
        rec = self.knowledge.get(tool_name)
        if rec:
            return rec.get("web_reference")
        return None

    def clear_web_reference(self, tool_name: str) -> bool:
        """清除工具的参考资料"""
        rec = self.knowledge.get(tool_name)
        if rec and "web_reference" in rec:
            del rec["web_reference"]
            self._save()
            return True
        return False

    # ── 主动探索学习 ───────────────────────────────────────────────────────────

    def start_learn(self, tool_name: str, tool_path: str) -> LearnTask:
        """
        启动一个工具自学任务（在后台线程中执行）。
        AI 自己跑命令探索工具用法，结束后自动存入知识库。
        """
        task = LearnTask(tool_name, tool_path)
        self._learn_tasks[tool_name] = task

        thread = threading.Thread(
            target=self._run_learn_task,
            args=(task,),
            daemon=True,
        )
        thread.start()
        logger.info(f"[ToolKnowledge] 启动工具自学: {tool_name} @ {tool_path}")
        return task

    def get_learn_task(self, tool_name: str) -> Optional[LearnTask]:
        return self._learn_tasks.get(tool_name)

    def stream_learn(self, tool_name: str, tool_path: str, web_reference: str = None) -> Generator[dict, None, None]:
        """
        流式执行工具自学，逐步 yield 每个步骤事件。
        用于 SSE 实时推送给前端。

        参数:
            tool_name: 工具名称
            tool_path: 工具路径
            web_reference: 可选的参考资料内容（从网上搜索后粘贴的）
        """
        from tools import dispatcher
        from config import load_model_config
        from openai import OpenAI

        task = LearnTask(tool_name, tool_path)
        self._learn_tasks[tool_name] = task

        yield {"event": "start", "tool": tool_name, "path": tool_path}

        cfg = load_model_config()
        client = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])

        # 构建初始用户消息，包含参考资料（如果有）
        user_msg_parts = [
            f"请帮我验证并学习这个工具的正确用法：",
            f"- 工具名: {tool_name}",
            f"- 工具路径: {tool_path}",
            "",
        ]

        # 检查是否有参考资料
        # 优先使用用户这次给的资料，没有的话就直接 -h 探索（不用旧资料）
        ref_content = web_reference

        # 检查知识库是否已有该工具的用法（用于继续学习）
        existing_usage = ""
        existing_rec = self.knowledge.get(tool_name)
        if existing_rec and existing_rec.get("usage_hints"):
            existing_usage = "已记录的用法:\n" + "\n".join(f"  - {h}" for h in existing_rec["usage_hints"])

        if ref_content:
            # 用户给了资料，用用户的
            user_msg_parts.extend([
                "## 参考资料（请基于这些资料验证命令是否有效）：",
                ref_content[:3000],  # 限制长度
                "",
                "## 你的任务：",
                "1. 从资料中提取可能有效的命令",
                "2. **逐一执行验证**，记录每个命令的执行结果",
                "3. 最终输出验证成功的命令列表",
            ])
        else:
            # 用户没给资料，直接执行 -h 查看帮助
            # 如果已有用法记录，告诉AI继续探索新的
            if existing_usage:
                user_msg_parts.extend([
                    "## 继续学习：",
                    existing_usage,
                    "",
                    "## 你的任务：",
                    "1. **先执行 `工具路径 -h` 或 `工具路径 --help` 查看帮助**",
                    "2. 基于帮助信息，尝试探索新的用法（不要重复已记录的）",
                    "3. 验证新发现的命令，记录有效的用法",
                ])
            else:
                user_msg_parts.extend([
                    "## 没有提供参考资料，请自行探索：",
                    "1. **先执行 `工具路径 -h` 或 `工具路径 --help` 查看帮助**，这是最重要的第一步",
                    "2. 仔细阅读帮助信息，了解工具有哪些选项和用法",
                    "3. 然后尝试运行工具的各种用法",
                    "4. 记录哪些命令有效",
                ])

        user_msg_parts.append("")

        messages = [
            {"role": "system", "content": _LEARN_SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(user_msg_parts)},
        ]

        MAX_STEPS = 30  # 增加步数，因为需要验证多个命令
        for step_no in range(1, MAX_STEPS + 1):
            # 调用 AI
            try:
                resp = client.chat.completions.create(
                    model=cfg["model"],
                    messages=messages,
                    temperature=0.3,
                    max_tokens=2048,  # 增大，避免输出被截断
                )
                raw = resp.choices[0].message.content.strip()
            except Exception as e:
                task.status = "failed"
                task.error = str(e)
                task.finished_at = time.time()
                yield {"event": "error", "message": f"AI 调用失败: {e}"}
                return

            # 解析 JSON
            action = self._parse_json(raw)
            thought = action.get("thought", "")
            tool_type = action.get("tool", "shell")
            command = action.get("command", "")
            file_path = action.get("path", "")

            yield {
                "event": "thinking",
                "step": step_no,
                "thought": thought,
                "tool": tool_type,
                "command": command,
            }

            # 结束
            if tool_type == "finish" or not action.get("continue", True):
                summary = action.get("summary", "")
                usage_hints = action.get("usage_hints", [])
                help_summary = action.get("help_summary", "")

                # 存入知识库
                self._save_learn_result(tool_name, tool_path, summary, usage_hints, help_summary, task.steps)

                task.status = "done"
                task.result = summary
                task.finished_at = time.time()

                yield {
                    "event": "done",
                    "tool": tool_name,
                    "summary": summary,
                    "usage_hints": usage_hints,
                    "help_summary": help_summary,
                }
                return

            # 执行命令（shell 或 file_read）
            cmd_result_text = ""
            if tool_type == "shell" and command:
                try:
                    result = dispatcher.dispatch({"tool": "shell", "command": command})
                    cmd_result_text = result.output
                    step_info = {
                        "step": step_no,
                        "thought": thought,
                        "tool": "shell",
                        "command": command,
                        "output": result.output[:1000],
                        "success": result.success,
                    }
                    task.steps.append(step_info)
                    yield {
                        "event": "step_result",
                        "step": step_no,
                        "tool": "shell",
                        "command": command,
                        "output": result.output[:1000],
                        "success": result.success,
                    }
                except Exception as e:
                    cmd_result_text = f"执行异常: {e}"
                    yield {"event": "step_result", "step": step_no, "tool": "shell", "command": command, "output": cmd_result_text, "success": False}

            elif tool_type == "file_read" and file_path:
                try:
                    # 确保路径安全，防止读取敏感文件
                    safe_path = os.path.abspath(file_path)
                    # 限制读取大小
                    with open(safe_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()[:5000]  # 最多读取 5000 字符
                    cmd_result_text = f"文件内容 ({safe_path}):\n{content}"
                    step_info = {
                        "step": step_no,
                        "thought": thought,
                        "tool": "file_read",
                        "path": safe_path,
                        "output": cmd_result_text[:1000],
                        "success": True,
                    }
                    task.steps.append(step_info)
                    yield {
                        "event": "step_result",
                        "step": step_no,
                        "tool": "file_read",
                        "path": safe_path,
                        "output": cmd_result_text[:1000],
                        "success": True,
                    }
                except Exception as e:
                    cmd_result_text = f"读取文件失败: {e}"
                    yield {"event": "step_result", "step": step_no, "tool": "file_read", "path": file_path, "output": cmd_result_text, "success": False}

            # 把结果追加到对话
            messages.append({"role": "assistant", "content": raw})
            
            # 根据工具类型生成不同的反馈
            if tool_type == "file_read":
                feedback = f"文件读取结果：\n{cmd_result_text}\n\n请分析文件内容，继续下一步探索，或者信息已足够则输出 finish。"
            else:
                feedback = f"命令执行结果：\n{cmd_result_text}\n\n请继续下一步探索，或者信息已足够则输出 finish。"

            messages.append({"role": "user", "content": feedback})

        # 超出最大步数，尝试让AI做一个总结
        task.status = "done"  # 改为 done，因为有结果了
        task.finished_at = time.time()
        yield {
            "event": "timeout",
            "message": f"已达到最大步数 ({MAX_STEPS} 步)，正在请求 AI 生成总结...",
            "steps_completed": MAX_STEPS
        }

        # 发送最后一个请求，让AI总结目前验证过的命令
        try:
            messages.append({
                "role": "user",
                "content": "已达到验证步数上限。请根据目前已验证的结果，直接输出 finish 格式的总结，包括：summary（工具简介）、usage_hints（目前验证成功的命令列表）、help_summary（帮助信息摘要）。"
            })
            resp = client.chat.completions.create(
                model=cfg["model"],
                messages=messages,
                temperature=0.3,
                max_tokens=1024,
            )
            raw = resp.choices[0].message.content.strip()
            action = self._parse_json(raw)

            if action.get("tool") == "finish":
                summary = action.get("summary", "（无总结）")
                usage_hints = action.get("usage_hints", [])
                help_summary = action.get("help_summary", "")

                # 保存结果
                self._save_learn_result(tool_name, tool_path, summary, usage_hints, help_summary, task.steps)
                task.result = summary

                yield {
                    "event": "done",
                    "tool": tool_name,
                    "summary": summary,
                    "usage_hints": usage_hints,
                    "help_summary": help_summary,
                    "note": "已达到最大步数，这是 AI 根据已验证结果生成的总结",
                }
                return
        except Exception as e:
            yield {"event": "error", "message": f"生成总结失败: {e}"}

        # 如果还是失败
        task.status = "failed"
        task.error = "超出最大探索步数"
        yield {"event": "error", "message": "超出最大探索步数，且生成总结失败"}

    def _run_learn_task(self, task: LearnTask):
        """在后台线程中运行（非流式，供异步调用）"""
        for event in self.stream_learn(task.tool_name, task.tool_path):
            pass  # 消费完生成器，结果已经存入知识库

    def _parse_json(self, raw: str) -> dict:
        """从 AI 响应中提取 JSON"""
        raw = raw.strip()
        # 去掉 markdown 代码块
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        try:
            return json.loads(raw)
        except Exception:
            # 尝试提取第一个 {...}
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group())
                except Exception:
                    pass
            return {"thought": raw, "tool": "shell", "command": "", "continue": False}

    def _save_learn_result(
        self,
        tool_name: str,
        tool_path: str,
        summary: str,
        usage_hints: List[str],
        help_summary: str,
        steps: List[dict],
    ):
        """将 AI 探索结果存入知识库"""
        rec = self.knowledge.setdefault(tool_name, {
            "tool": tool_name,
            "usage_hints": [],
            "errors": [],
            "updated_at": 0,
        })
        rec["tool_path"] = tool_path
        rec["help_summary"] = help_summary or summary[:300]
        rec["summary"] = summary[:1000]

        # 合并用法提示（去重）
        existing = set(rec.get("usage_hints", []))
        for hint in usage_hints:
            if hint and hint not in existing:
                rec["usage_hints"].append(hint)
                existing.add(hint)
        rec["usage_hints"] = rec["usage_hints"][-8:]

        # 记录学习历史
        rec["learned_at"] = time.time()
        rec["learn_steps"] = len(steps)
        rec["updated_at"] = time.time()
        rec["source"] = "ai_explore"  # 标记来源为 AI 主动探索

        self._save()
        logger.info(f"[ToolKnowledge] 自学完成，已存档: {tool_name} ({len(usage_hints)} 条用法)")

    # ── System Prompt 注入 ─────────────────────────────────────────────────────

    def build_context_hint(self, tool_names: List[str] = None) -> str:
        """构建注入到 System Prompt 的知识上下文"""
        if not self.knowledge:
            return ""

        targets = {}
        if tool_names:
            for name in tool_names:
                for k, v in self.knowledge.items():
                    if k in name or name in k or k == name:
                        targets[k] = v
        else:
            targets = self.knowledge

        if not targets:
            return ""

        lines = ["\n## 【工具使用经验库】（从历史错误和主动学习中积累）"]
        for tool_name, rec in targets.items():
            source_tag = "🧠 AI探索" if rec.get("source") == "ai_explore" else "📝 经验积累"
            lines.append(f"\n### 工具: {tool_name}  [{source_tag}]")
            if rec.get("tool_path"):
                lines.append(f"路径: {rec['tool_path']}")
            if rec.get("help_summary"):
                lines.append(f"功能摘要: {rec['help_summary']}")
            if rec.get("usage_hints"):
                lines.append("✅ 正确用法:")
                for hint in rec["usage_hints"]:
                    lines.append(f"  - {hint}")
            if rec.get("errors"):
                lines.append("⚠️ 已知错误及修正:")
                for err in rec["errors"][-3:]:
                    lines.append(f"  ✗ 失败: {err['failed_command']}")
                    if err.get("error_output"):
                        lines.append(f"    错误: {err['error_output'][:150]}")
                    if err.get("fixed_command"):
                        lines.append(f"  ✓ 正确: {err['fixed_command']}")
        lines.append("")
        return "\n".join(lines)

    def extract_tool_names_from_task(self, task: str) -> List[str]:
        """从任务描述中提取已知的工具名"""
        found = []
        task_lower = task.lower()
        for tool_name in self.knowledge:
            if tool_name.lower() in task_lower:
                found.append(tool_name)
        return found


# 全局实例
tool_knowledge = ToolKnowledge()
