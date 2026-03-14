"""
工具知识库 - 记录和学习各种 Linux 工具的使用方法

两种学习方式：
1. 被动学习：Agent 执行任务时命令失败 → 自动记录错误 → 下次注入 System Prompt
2. 主动探索：用户发起"让 AI 自学某工具" → AI 自己跑命令测试 → 把用法总结存档

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

# 工具自学任务的 System Prompt
_LEARN_SYSTEM_PROMPT = """你是一个 Linux 工具使用专家，你的任务是：**主动测试一个工具，把它的用法彻底搞清楚**。

## 工作方式
每次响应必须返回一个合法的 JSON 对象（严禁在 JSON 前后附加任何文字），格式：

```json
{
  "thought": "当前分析和下一步计划",
  "tool": "shell",
  "command": "要执行的命令",
  "continue": true
}
```

结束时：
```json
{
  "thought": "已充分了解该工具的用法",
  "tool": "finish",
  "summary": "工具使用总结",
  "usage_hints": ["用法1", "用法2", "用法3"],
  "help_summary": "对 -h 输出的精炼摘要（100字内）",
  "continue": false
}
```

## 探索策略（按顺序执行）
1. 先用 `tool_path -h` 或 `tool_path --help` 查看帮助（会失败也记录错误信息）
2. 如果 -h 失败，尝试：`tool_path help`、`tool_path -?`、`man tool_name`
3. 查看文件头部注释：`head -50 tool_path`
4. 尝试直接运行（无参数）：`tool_path` 或 `bash tool_path`
5. 根据帮助输出，用不同参数实际测试 2-3 次
6. 综合所有输出，总结出：
   - 工具的主要功能是什么
   - 正确的调用方式（命令格式）
   - 有哪些重要参数
   - 需要什么权限

## 规则
- 只返回 JSON，无任何 markdown 或其他文字
- 最多 8 步，必须在 8 步内完成并输出 finish
- 如果工具不存在，2步内确认并返回 finish（说明工具不存在）
- finish 的 usage_hints 必须是可直接复制执行的命令示例列表
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
        self._load()

    # ── 基础 CRUD ──────────────────────────────────────────────────────────────

    def _load(self):
        try:
            with open(KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
                self.knowledge = json.load(f)
            logger.info(f"[ToolKnowledge] 已加载 {len(self.knowledge)} 个工具知识")
        except FileNotFoundError:
            self.knowledge = {}
        except Exception as e:
            logger.warning(f"[ToolKnowledge] 加载失败: {e}")
            self.knowledge = {}

    def _save(self):
        try:
            with open(KNOWLEDGE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.knowledge, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[ToolKnowledge] 保存失败: {e}")

    def get(self, tool_name: str) -> Optional[dict]:
        return self.knowledge.get(tool_name)

    def list_all(self) -> List[dict]:
        result = []
        for name, rec in self.knowledge.items():
            result.append({"tool": name, **rec})
        return result

    def delete(self, tool_name: str) -> bool:
        if tool_name in self.knowledge:
            del self.knowledge[tool_name]
            self._save()
            return True
        return False

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

    def stream_learn(self, tool_name: str, tool_path: str) -> Generator[dict, None, None]:
        """
        流式执行工具自学，逐步 yield 每个步骤事件。
        用于 SSE 实时推送给前端。
        """
        from tools import dispatcher
        from config import load_model_config
        from openai import OpenAI

        task = LearnTask(tool_name, tool_path)
        self._learn_tasks[tool_name] = task

        yield {"event": "start", "tool": tool_name, "path": tool_path}

        cfg = load_model_config()
        client = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])

        messages = [
            {"role": "system", "content": _LEARN_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"请帮我彻底搞清楚这个工具的用法：\n"
                    f"- 工具名: {tool_name}\n"
                    f"- 工具路径: {tool_path}\n\n"
                    f"按照探索策略一步步测试，最终总结出它的完整用法。"
                ),
            },
        ]

        MAX_STEPS = 10
        for step_no in range(1, MAX_STEPS + 1):
            # 调用 AI
            try:
                resp = client.chat.completions.create(
                    model=cfg["model"],
                    messages=messages,
                    temperature=0.3,
                    max_tokens=1024,
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

            # 执行 shell 命令
            cmd_result_text = ""
            if tool_type == "shell" and command:
                try:
                    result = dispatcher.dispatch({"tool": "shell", "command": command})
                    cmd_result_text = result.output
                    step_info = {
                        "step": step_no,
                        "thought": thought,
                        "command": command,
                        "output": result.output[:600],
                        "success": result.success,
                    }
                    task.steps.append(step_info)
                    yield {
                        "event": "step_result",
                        "step": step_no,
                        "command": command,
                        "output": result.output[:600],
                        "success": result.success,
                    }
                except Exception as e:
                    cmd_result_text = f"执行异常: {e}"
                    yield {"event": "step_result", "step": step_no, "command": command, "output": cmd_result_text, "success": False}

            # 把结果追加到对话
            messages.append({"role": "assistant", "content": raw})
            messages.append({
                "role": "user",
                "content": f"命令执行结果：\n{cmd_result_text}\n\n请继续下一步探索，或者信息已足够则输出 finish。",
            })

        # 超出步数
        task.status = "failed"
        task.error = "超出最大探索步数"
        task.finished_at = time.time()
        yield {"event": "error", "message": "超出最大探索步数，已停止"}

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
