"""
命令执行模块 - subprocess 封装 + 超时控制 + 输出截断
支持 Linux bash 和 Windows cmd/PowerShell 两种执行环境。
"""
import subprocess
import logging
import platform
import sys
from typing import Tuple

from config import COMMAND_TIMEOUT, MAX_OUTPUT_LENGTH
from security import security, SecurityError

logger = logging.getLogger(__name__)

# ─── 平台检测 ─────────────────────────────────────────────────────────────────

IS_WINDOWS = platform.system().lower() == "windows"

# Windows 下优先用 UTF-8 读取输出；
# 若目标机器是远端 Windows（通过 SSH/代理执行），编码通常也是 cp936(GBK)。
# 这里检测当前运行平台的默认编码作为 fallback。
_DEFAULT_ENCODING = "utf-8"
_FALLBACK_ENCODING = "gbk" if IS_WINDOWS else "utf-8"


class ExecutionResult:
    """命令执行结果"""

    def __init__(self, stdout: str, stderr: str, returncode: int, command: str):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.command = command
        self.success = returncode == 0

    @property
    def output(self) -> str:
        """合并 stdout + stderr 返回给 AI"""
        parts = []
        if self.stdout.strip():
            parts.append(self.stdout.strip())
        if self.stderr.strip():
            parts.append(f"[stderr] {self.stderr.strip()}")
        combined = "\n".join(parts) if parts else "(无输出)"
        if len(combined) > MAX_OUTPUT_LENGTH:
            combined = combined[:MAX_OUTPUT_LENGTH] + f"\n... [输出已截断，共 {len(combined)} 字符]"
        return combined

    def __repr__(self):
        return f"ExecutionResult(cmd={self.command!r}, rc={self.returncode}, success={self.success})"


class CommandExecutor:
    """
    通用命令执行器，自动适配 Linux / Windows 两种环境。

    - Linux: shell=True，使用 /bin/sh（bash 兼容）
    - Windows: shell=True，使用 cmd.exe；编码自动尝试 UTF-8 → GBK
    - 调用 security.check_command() 做安全过滤
    - 支持超时控制，所有执行都记录日志
    """

    def __init__(self, timeout: int = COMMAND_TIMEOUT):
        self.timeout = timeout

    def _decode_output(self, raw_bytes: bytes) -> str:
        """
        智能解码命令输出，依次尝试：UTF-8 → GBK → latin-1（兜底不乱码）
        """
        for enc in ("utf-8", "gbk", "latin-1"):
            try:
                return raw_bytes.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return raw_bytes.decode("latin-1", errors="replace")

    def run(self, command: str) -> ExecutionResult:
        """
        执行 shell 命令。
        返回 ExecutionResult，不抛异常（安全拦截除外）。
        """
        # ── 安全检查 ──────────────────────────────────────────────────────────
        try:
            command = security.check_command(command)
        except SecurityError as e:
            logger.warning(f"命令被拦截: {command} | 原因: {e}")
            return ExecutionResult(
                stdout="",
                stderr=f"[安全拦截] {e}",
                returncode=-1,
                command=command,
            )

        logger.info(f"执行命令 [{'win' if IS_WINDOWS else 'linux'}]: {command}")

        # ── 实际执行 ──────────────────────────────────────────────────────────
        try:
            if IS_WINDOWS:
                # Windows：使用 cmd.exe，以字节方式读取后手动解码，避免编码问题
                proc = subprocess.run(
                    command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=self.timeout,
                    # 不指定 text/encoding，拿原始字节自行解码
                )
                stdout = self._decode_output(proc.stdout)
                stderr = self._decode_output(proc.stderr)
            else:
                # Linux：直接用 utf-8
                proc = subprocess.run(
                    command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=self.timeout,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                stdout = proc.stdout
                stderr = proc.stderr

            result = ExecutionResult(
                stdout=stdout,
                stderr=stderr,
                returncode=proc.returncode,
                command=command,
            )
            if result.success:
                logger.info(f"命令成功 (rc=0): {command}")
            else:
                logger.warning(f"命令失败 (rc={proc.returncode}): {command}\n{result.output[:300]}")
            return result

        except subprocess.TimeoutExpired:
            msg = f"命令超时（>{self.timeout}s）: {command}"
            logger.error(msg)
            return ExecutionResult(
                stdout="",
                stderr=f"[超时] 命令执行超过 {self.timeout} 秒，已强制终止",
                returncode=-2,
                command=command,
            )

        except Exception as e:
            msg = f"命令执行异常: {command} | {e}"
            logger.error(msg)
            return ExecutionResult(
                stdout="",
                stderr=f"[执行错误] {e}",
                returncode=-3,
                command=command,
            )


# 全局执行器实例
executor = CommandExecutor()
