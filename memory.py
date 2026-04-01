"""
记忆模块 - 管理任务执行历史和 AI 对话上下文
"""
import json
import time
import logging
import os
import threading
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class StepRecord:
    """单步执行记录"""
    step_no: int
    thought: str
    tool: str
    command: str
    result: str
    success: bool
    status: str = "ok"
    structured_summary: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return asdict(self)

    def summary(self) -> str:
        """生成简洁摘要，用于向 AI 回传上下文"""
        status = "✓" if self.success else "✗"
        return (
            f"[Step {self.step_no}] {status} tool={self.tool} "
            f"cmd=`{self.command}` "
            f"result={self.result[:200]}{'...' if len(self.result) > 200 else ''}"
        )


@dataclass
class TaskSession:
    """一次任务的完整会话"""
    task_id: str
    task: str
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    steps: List[StepRecord] = field(default_factory=list)
    status: str = "running"   # running | completed | failed | aborted
    phase: str = "plan"       # plan | collect | verify | conclude
    evidence_coverage: Dict[str, str] = field(default_factory=lambda: {
        "accounts": "todo",
        "processes": "todo",
        "network": "todo",
        "persistence": "todo",
        "logs": "todo",
        "files": "todo",
    })
    final_answer: str = ""

    def add_step(self, step: StepRecord):
        self.steps.append(step)

    def finish(self, status: str, final_answer: str = ""):
        self.end_time = time.time()
        self.status = status
        self.final_answer = final_answer

    def to_dict(self) -> Dict:
        d = asdict(self)
        return d

    def duration(self) -> float:
        end = self.end_time or time.time()
        return round(end - self.start_time, 2)


class Memory:
    """
    任务记忆系统：
    - 维护当前任务的对话历史（发送给 AI 的 messages）
    - 记录所有步骤执行情况
    - 支持会话持久化（写入 JSON 日志文件）
    """

    def __init__(self, persist_file: str = "task_history.json"):
        self.persist_file = persist_file
        self.sessions: Dict[str, TaskSession] = {}
        self._lock = threading.RLock()
        self._load_history()

    # ── 会话管理 ──────────────────────────────────────────────────────────────

    def new_session(self, task_id: str, task: str) -> TaskSession:
        session = TaskSession(task_id=task_id, task=task)
        with self._lock:
            self.sessions[task_id] = session
        logger.info(f"新建任务会话: {task_id} | 任务: {task}")
        return session

    def get_session(self, task_id: str) -> Optional[TaskSession]:
        with self._lock:
            return self.sessions.get(task_id)

    def finish_session(self, task_id: str, status: str, final_answer: str = ""):
        with self._lock:
            session = self.sessions.get(task_id)
            if session:
                session.finish(status, final_answer)
                self._save_history()
                logger.info(f"任务完成: {task_id} | 状态: {status} | 耗时: {session.duration()}s")

    def update_phase(self, task_id: str, phase: str):
        """更新任务当前阶段。"""
        with self._lock:
            session = self.sessions.get(task_id)
            if not session:
                return
            phase = (phase or "").strip().lower()
            if phase and session.phase != phase:
                session.phase = phase
                logger.info(f"[Memory] 任务阶段更新: {task_id} -> {phase}")

    def update_evidence_coverage(self, task_id: str, updates: Dict[str, str]):
        """更新证据面覆盖状态。"""
        with self._lock:
            session = self.sessions.get(task_id)
            if not session or not updates:
                return
            for key, value in updates.items():
                if key in session.evidence_coverage and value:
                    session.evidence_coverage[key] = value

    # ── 步骤记录 ──────────────────────────────────────────────────────────────

    def record_step(
        self,
        task_id: str,
        step_no: int,
        thought: str,
        tool: str,
        command: str,
        result: str,
        success: bool,
        status: str = "ok",
        structured_summary: str = "",
    ) -> StepRecord:
        step = StepRecord(
            step_no=step_no,
            thought=thought,
            tool=tool,
            command=command,
            result=result,
            success=success,
            status=status,
            structured_summary=structured_summary,
        )
        with self._lock:
            session = self.sessions.get(task_id)
            if session:
                session.add_step(step)
        return step

    # ── AI 消息历史构建 ───────────────────────────────────────────────────────

    def build_messages(self, task_id: str, system_prompt: str) -> List[Dict]:
        """
        构建发送给 AI 的完整 messages 列表。
        包含 system prompt + 当前任务 + 历史步骤上下文。
        """
        with self._lock:
            session = self.sessions.get(task_id)
        messages = [{"role": "system", "content": system_prompt}]

        if session:
            # 初始任务描述
            messages.append({
                "role": "user",
                "content": f"任务: {session.task}"
            })

            snapshot = self._build_session_snapshot(session)
            if snapshot:
                messages.append({
                    "role": "user",
                    "content": snapshot
                })

            # 历史步骤作为 assistant/user 对话轮次
            for step in session.steps:
                # AI 上一步的决策
                messages.append({
                    "role": "assistant",
                    "content": json.dumps({
                        "thought": step.thought,
                        "tool": step.tool,
                        "command": step.command,
                    }, ensure_ascii=False)
                })
                # 系统执行结果反馈给 AI
                messages.append({
                    "role": "user",
                    "content": f"执行结果 (step {step.step_no}, {'成功' if step.success else '失败'}):\n{step.result}"
                })

        return messages

    def _build_session_snapshot(self, session: TaskSession) -> str:
        """构建任务状态快照，帮助 AI 在长流程中保持阶段感。"""
        if not session.steps:
            return (
                "当前状态快照:\n"
                "- 这是第 1 轮执行\n"
                "- 尚无历史结果，请先做低风险信息收集\n"
                "- 优先一次收集账号、进程、网络、持久化、关键日志相关证据\n"
                "- 如果存在结构化工具能力，优先使用结构化能力"
            )

        total_steps = len(session.steps)
        success_steps = sum(1 for step in session.steps if step.success)
        failed_steps = total_steps - success_steps
        recent_steps = session.steps[-4:]

        lines = [
            "当前状态快照:",
            f"- 已执行轮次: {total_steps}",
            f"- 当前阶段: {session.phase}",
            f"- 成功步骤: {success_steps}",
            f"- 失败步骤: {failed_steps}",
        ]
        lines.append("- 证据面覆盖:")
        for key, value in session.evidence_coverage.items():
            lines.append(f"  - {key}: {value}")

        recent_failures = [
            step for step in reversed(session.steps)
            if not step.success and step.command
        ][:2]
        if recent_failures:
            lines.append("- 最近失败命令:")
            for step in recent_failures:
                lines.append(
                    f"  - step {step.step_no}: [{step.tool}] {step.command[:120]}"
                )

        lines.append("- 最近关键观察:")
        for step in recent_steps:
            status = "成功" if step.success else "失败"
            result = (step.result or "").replace("\r", " ").replace("\n", " ")
            result = result[:180] + ("..." if len(result) > 180 else "")
            lines.append(
                f"  - step {step.step_no} | {status} | {step.tool} | {step.command[:100]}"
            )
            lines.append(f"    输出摘要: {result}")

        if total_steps >= 6:
            lines.append("- 决策提醒: 若核心证据已足够，请优先汇总结论，避免重复采集")
        else:
            lines.append("- 决策提醒: 优先补齐账号、进程、网络、持久化、日志中尚未覆盖的证据面")

        phase_advice = {
            "plan": "- 阶段要求: 先明确检查范围与优先证据面，再进入采集",
            "collect": "- 阶段要求: 优先广覆盖采集，避免过早下结论",
            "verify": "- 阶段要求: 围绕已发现的异常做定向验证，不再重复全量扫描",
            "conclude": "- 阶段要求: 以收敛结论为主，尽快输出 threats / suspicious / normal / advice",
        }
        if session.phase in phase_advice:
            lines.append(phase_advice[session.phase])

        return "\n".join(lines)

    # ── 历史持久化 ────────────────────────────────────────────────────────────

    def _save_history(self):
        try:
            with self._lock:
                data = {tid: s.to_dict() for tid, s in self.sessions.items()}
                temp_file = f"{self.persist_file}.tmp"
                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(temp_file, self.persist_file)
        except Exception as e:
            logger.error(f"保存历史失败: {e}")

    def _load_history(self):
        try:
            with open(self.persist_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if not content:
                # 空文件，正常跳过，顺便修复成合法 JSON
                with open(self.persist_file, "w", encoding="utf-8") as f:
                    f.write("{}")
                return
            data = json.loads(content)
            with self._lock:
                for tid, d in data.items():
                    steps = [StepRecord(**s) for s in d.pop("steps", [])]
                    session = TaskSession(**d)
                    session.steps = steps
                    self.sessions[tid] = session
            logger.info(f"加载历史会话 {len(self.sessions)} 条")
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning(f"加载历史失败: {e}")

    def list_sessions(self, limit: int = 20) -> List[Dict]:
        """返回最近的会话列表摘要"""
        with self._lock:
            sessions = sorted(
                self.sessions.values(),
                key=lambda s: s.start_time,
                reverse=True
            )[:limit]
        return [
            {
                "task_id": s.task_id,
                "task": s.task,
                "status": s.status,
                "steps": len(s.steps),
                "duration": s.duration(),
                "start_time": s.start_time,
            }
            for s in sessions
        ]

    # ── 记忆清除 ──────────────────────────────────────────────────────────────

    def clear_all(self) -> int:
        """清除全部会话记忆（内存 + 持久化文件），返回清除条数"""
        with self._lock:
            count = len(self.sessions)
            self.sessions.clear()
            self._save_history()   # 写入空文件
        logger.info(f"[Memory] 已清除全部记忆，共 {count} 条")
        return count

    def clear_session(self, task_id: str) -> bool:
        """清除指定会话，返回是否存在并删除成功"""
        with self._lock:
            if task_id in self.sessions:
                del self.sessions[task_id]
                self._save_history()
                logger.info(f"[Memory] 已删除会话: {task_id}")
                return True
            return False

    def stats(self) -> Dict:
        """返回记忆统计信息"""
        with self._lock:
            total = len(self.sessions)
            completed = sum(1 for s in self.sessions.values() if s.status == "completed")
            failed = sum(1 for s in self.sessions.values() if s.status in ("failed", "aborted"))
        file_size = 0
        try:
            file_size = os.path.getsize(self.persist_file)
        except Exception:
            pass
        return {
            "total_sessions": total,
            "completed": completed,
            "failed": failed,
            "running": total - completed - failed,
            "persist_file": self.persist_file,
            "file_size_kb": round(file_size / 1024, 2),
        }


# 全局记忆实例
memory = Memory()
