"""
记忆模块 - 管理任务执行历史和 AI 对话上下文
"""
import json
import time
import logging
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
        self._load_history()

    # ── 会话管理 ──────────────────────────────────────────────────────────────

    def new_session(self, task_id: str, task: str) -> TaskSession:
        session = TaskSession(task_id=task_id, task=task)
        self.sessions[task_id] = session
        logger.info(f"新建任务会话: {task_id} | 任务: {task}")
        return session

    def get_session(self, task_id: str) -> Optional[TaskSession]:
        return self.sessions.get(task_id)

    def finish_session(self, task_id: str, status: str, final_answer: str = ""):
        session = self.sessions.get(task_id)
        if session:
            session.finish(status, final_answer)
            self._save_history()
            logger.info(f"任务完成: {task_id} | 状态: {status} | 耗时: {session.duration()}s")

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
    ) -> StepRecord:
        step = StepRecord(
            step_no=step_no,
            thought=thought,
            tool=tool,
            command=command,
            result=result,
            success=success,
        )
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
        session = self.sessions.get(task_id)
        messages = [{"role": "system", "content": system_prompt}]

        if session:
            # 初始任务描述
            messages.append({
                "role": "user",
                "content": f"任务: {session.task}"
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

    # ── 历史持久化 ────────────────────────────────────────────────────────────

    def _save_history(self):
        try:
            data = {tid: s.to_dict() for tid, s in self.sessions.items()}
            with open(self.persist_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存历史失败: {e}")

    def _load_history(self):
        try:
            with open(self.persist_file, "r", encoding="utf-8") as f:
                data = json.load(f)
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
        count = len(self.sessions)
        self.sessions.clear()
        self._save_history()   # 写入空文件
        logger.info(f"[Memory] 已清除全部记忆，共 {count} 条")
        return count

    def clear_session(self, task_id: str) -> bool:
        """清除指定会话，返回是否存在并删除成功"""
        if task_id in self.sessions:
            del self.sessions[task_id]
            self._save_history()
            logger.info(f"[Memory] 已删除会话: {task_id}")
            return True
        return False

    def stats(self) -> Dict:
        """返回记忆统计信息"""
        import os
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
