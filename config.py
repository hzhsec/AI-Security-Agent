"""
配置文件 - API Key、模型参数、系统设置
"""
import os
import json

# ─── DeepSeek API 配置（默认） ──────────────────────────────────────────────
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "your-deepseek-api-key-here")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

# ─── Agent 行为配置 ─────────────────────────────────────────────────────────
MAX_ITERATIONS = 40          # 单次任务最大循环轮次（安全巡检等复杂任务需要更多轮次）
COMMAND_TIMEOUT = 120        # 命令执行超时（秒，脚本类任务可能较慢）
MAX_OUTPUT_LENGTH = 6000     # 命令输出最大字符数（巡检输出较多，适当放大）

# ─── Web API 配置 ───────────────────────────────────────────────────────────
API_HOST = "0.0.0.0"
API_PORT = 8000

# ─── 日志配置 ────────────────────────────────────────────────────────────────
LOG_FILE = "agent.log"
LOG_LEVEL = "INFO"

# ─── 安全配置 ────────────────────────────────────────────────────────────────
# 黑名单：直接拒绝，这些是真正毁灭性操作（私用模式，仅保留最危险的）
COMMAND_BLACKLIST = [
    "rm -rf /",
    "rm -rf /*",
    "rm -rf ~",
    ":(){ :|:& };:",   # fork bomb
    "mkfs",
    "> /dev/sda",
    "> /dev/nvme",
    "dd if=/dev/zero of=/dev/sd",
    "dd if=/dev/zero of=/dev/nvme",
    "chmod -R 777 /",
    "passwd root",
    "userdel root",
]

# 高危命令：仅记录日志警告，不阻止执行（私用模式下巡检需要这些权限）
# shutdown/reboot 保留但会 warning，真正用的话用户自己清楚
DANGEROUS_COMMANDS = [
    "shutdown",
    "reboot",
    "halt",
    "poweroff",
    "init 0",
    "init 6",
]

# ─── 多模型预设配置 ──────────────────────────────────────────────────────────
# 每个预设包含: name(显示名), base_url, model, key_env(环境变量名)
MODEL_PRESETS = {
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "key_env": "DEEPSEEK_API_KEY",
        "docs": "https://platform.deepseek.com",
    },
    "qwen": {
        "name": "通义千问 (Qwen)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "key_env": "DASHSCOPE_API_KEY",
        "docs": "https://dashscope.console.aliyun.com",
    },
    "wenxin": {
        "name": "文心一言 (ERNIE)",
        "base_url": "https://qianfan.baidubce.com/v2",
        "model": "ernie-4.5-8k",
        "key_env": "QIANFAN_API_KEY",
        "docs": "https://qianfan.cloud.baidu.com",
    },
    "moonshot": {
        "name": "月之暗面 (Kimi)",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
        "key_env": "MOONSHOT_API_KEY",
        "docs": "https://platform.moonshot.cn",
    },
    "zhipu": {
        "name": "智谱 GLM (ChatGLM)",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
        "key_env": "ZHIPU_API_KEY",
        "docs": "https://open.bigmodel.cn",
    },
    "openai": {
        "name": "OpenAI (GPT)",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "key_env": "OPENAI_API_KEY",
        "docs": "https://platform.openai.com",
    },
    "custom": {
        "name": "自定义 API",
        "base_url": "",
        "model": "",
        "key_env": "",
        "docs": "",
    },
}

# ─── 运行时模型配置（持久化到 model_config.json）────────────────────────────
_MODEL_CONFIG_FILE = "model_config.json"
_DEFAULT_MODEL_CONFIG = {
    "provider": "deepseek",
    "api_key": DEEPSEEK_API_KEY,
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-chat",
}


def load_model_config() -> dict:
    """从文件加载当前模型配置，文件不存在则返回默认值"""
    try:
        with open(_MODEL_CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            # 补全缺失字段
            for k, v in _DEFAULT_MODEL_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
    except FileNotFoundError:
        return _DEFAULT_MODEL_CONFIG.copy()
    except Exception:
        return _DEFAULT_MODEL_CONFIG.copy()


def save_model_config(cfg: dict):
    """保存模型配置到文件"""
    with open(_MODEL_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

