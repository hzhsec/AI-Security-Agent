"""
安全控制模块 - 命令黑名单过滤 + 危险命令拦截
"""
import re
import logging
from config import COMMAND_BLACKLIST, DANGEROUS_COMMANDS

logger = logging.getLogger(__name__)


class SecurityError(Exception):
    """命令被安全策略拦截时抛出"""
    pass


class SecurityManager:
    """
    安全管理器：
    1. 黑名单过滤 - 直接拒绝危险命令
    2. 危险命令标记 - 记录日志，但仍执行（可配置为拒绝）
    3. 路径遍历检测 - 防止访问敏感目录
    """

    # 敏感路径，禁止写操作
    SENSITIVE_PATHS = [
        "/etc/passwd", "/etc/shadow", "/etc/sudoers",
        "/boot", "/sys", "/proc",
    ]

    # 允许访问的路径前缀（白名单模式，可选开启）
    ALLOWED_PATHS = ["/tmp", "/home", "/var/log", "/opt"]

    def __init__(self, strict_mode: bool = False):
        """
        strict_mode=True: 危险命令也直接拒绝
        strict_mode=False: 危险命令仅记录警告，继续执行
        """
        self.strict_mode = strict_mode

    def check_command(self, command: str) -> str:
        """
        检查命令安全性，返回清理后的命令。
        如果命令不安全则抛出 SecurityError。
        """
        command = command.strip()

        if not command:
            raise SecurityError("命令为空")

        # 1. 黑名单检查（大小写不敏感）
        cmd_lower = command.lower()
        for pattern in COMMAND_BLACKLIST:
            if pattern.lower() in cmd_lower:
                msg = f"[SECURITY BLOCKED] 命令包含黑名单模式: '{pattern}' | 命令: {command}"
                logger.warning(msg)
                raise SecurityError(f"命令被安全策略拦截（黑名单匹配: {pattern}）")

        # 2. 危险命令检查（仅记录 warning，不阻止）
        for pattern in DANGEROUS_COMMANDS:
            if cmd_lower.startswith(pattern.lower()) or f" {pattern.lower()}" in cmd_lower:
                if self.strict_mode:
                    raise SecurityError(f"严格模式下拒绝危险命令: {pattern}")
                else:
                    logger.warning(f"[SECURITY WARNING] 高危命令被执行（已放行）: {command}")

        logger.info(f"[SECURITY OK] 命令通过安全检查: {command}")
        return command

    def check_file_path(self, path: str, write_mode: bool = False) -> str:
        """检查文件路径安全性"""
        path = path.strip()

        # 防止路径遍历
        if ".." in path:
            raise SecurityError(f"路径包含 '..' 遍历: {path}")

        # 只在写操作时检查最敏感的路径（读操作允许，巡检需要读系统文件）
        if write_mode:
            write_blacklist = ["/etc/passwd", "/etc/shadow", "/etc/sudoers", "/boot/"]
            for sensitive in write_blacklist:
                if path.startswith(sensitive):
                    raise SecurityError(f"禁止写入高危敏感路径: {path}")

        return path

    def sanitize_url(self, url: str) -> str:
        """检查 HTTP 请求 URL 安全性（防止 SSRF）"""
        import urllib.parse
        parsed = urllib.parse.urlparse(url)

        # 只允许 http/https
        if parsed.scheme not in ("http", "https"):
            raise SecurityError(f"不允许的 URL scheme: {parsed.scheme}")

        # 阻断内网地址（简单版 SSRF 防护）
        blocked_hosts = ["localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254"]
        if parsed.hostname in blocked_hosts:
            raise SecurityError(f"禁止访问内网地址: {parsed.hostname}")

        return url


# 全局安全管理器实例
security = SecurityManager(strict_mode=False)
