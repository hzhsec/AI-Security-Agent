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
# 每个预设包含: name(显示名), base_url, model(默认), models(可选列表), key_env, docs
MODEL_PRESETS = {
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "models": [
            "deepseek-chat",
            "deepseek-reasoner",
        ],
        "key_env": "DEEPSEEK_API_KEY",
        "docs": "https://platform.deepseek.com",
    },
    "qwen": {
        "name": "通义千问 (Qwen)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "models": [
            "qwen-plus",
            "qwen-turbo",
            "qwen-max",
            "qwen-long",
            "qwen3-235b-a22b",
            "qwen3-30b-a3b",
            "qwen3-32b",
            "qwen2.5-72b-instruct",
            "qwen2.5-32b-instruct",
            "qwen2.5-14b-instruct",
            "qwen2.5-coder-32b-instruct",
        ],
        "key_env": "DASHSCOPE_API_KEY",
        "docs": "https://dashscope.console.aliyun.com",
    },
    "wenxin": {
        "name": "文心一言 (ERNIE)",
        "base_url": "https://qianfan.baidubce.com/v2",
        "model": "ernie-4.5-8k",
        "models": [
            "ernie-4.5-8k",
            "ernie-4.5-turbo-128k",
            "ernie-4.0-8k",
            "ernie-3.5-8k",
            "ernie-speed-8k",
            "ernie-speed-128k",
            "ernie-lite-8k",
            "ernie-tiny-8k",
        ],
        "key_env": "QIANFAN_API_KEY",
        "docs": "https://qianfan.cloud.baidu.com",
    },
    "moonshot": {
        "name": "月之暗面 (Kimi)",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
        "models": [
            "moonshot-v1-8k",
            "moonshot-v1-32k",
            "moonshot-v1-128k",
            "kimi-k1-5-turbo",
            "kimi-k2-0520",
        ],
        "key_env": "MOONSHOT_API_KEY",
        "docs": "https://platform.moonshot.cn",
    },
    "zhipu": {
        "name": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
        "models": [
            "glm-4-flash",
            "glm-4-flashx",
            "glm-4-air",
            "glm-4-airx",
            "glm-4",
            "glm-4-plus",
            "glm-4-long",
            "glm-z1-flash",
            "glm-z1-air",
            "glm-z1-airx",
        ],
        "key_env": "ZHIPU_API_KEY",
        "docs": "https://open.bigmodel.cn",
    },
    "hunyuan": {
        "name": "腾讯混元",
        "base_url": "https://api.hunyuan.cloud.tencent.com/v1",
        "model": "hunyuan-lite",
        "models": [
            "hunyuan-lite",
            "hunyuan-standard",
            "hunyuan-standard-256k",
            "hunyuan-pro",
            "hunyuan-turbo",
            "hunyuan-turbo-latest",
            "hunyuan-large",
            "hunyuan-code",
            "hunyuan-role",
            "hunyuan-functioncall",
        ],
        "key_env": "HUNYUAN_API_KEY",
        "docs": "https://cloud.tencent.com/product/hunyuan",
    },
    "doubao": {
        "name": "字节豆包",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "doubao-pro-32k",
        "models": [
            "doubao-pro-4k",
            "doubao-pro-32k",
            "doubao-pro-128k",
            "doubao-lite-4k",
            "doubao-lite-32k",
            "doubao-lite-128k",
            "doubao-1-5-pro-32k",
            "doubao-1-5-pro-256k",
            "doubao-1-5-lite-32k",
            "deepseek-r1-250528",
            "deepseek-v3-250324",
        ],
        "key_env": "ARK_API_KEY",
        "docs": "https://www.volcengine.com/product/ark",
    },
    "spark": {
        "name": "讯飞星火",
        "base_url": "https://spark-api-open.xf-yun.com/v1",
        "model": "lite",
        "models": [
            "lite",
            "pro",
            "pro-128k",
            "max",
            "max-32k",
            "4.0Ultra",
        ],
        "key_env": "SPARK_API_KEY",
        "docs": "https://console.xfyun.cn/services/bm35",
    },
    "minimax": {
        "name": "MiniMax",
        "base_url": "https://api.minimax.chat/v1",
        "model": "MiniMax-Text-01",
        "models": [
            "MiniMax-Text-01",
            "MiniMax-M1",
            "MiniMax-M1-mini",
            "abab6.5s-chat",
            "abab6.5g-chat",
        ],
        "key_env": "MINIMAX_API_KEY",
        "docs": "https://platform.minimaxi.com",
    },
    "siliconflow": {
        "name": "硅基流动",
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "deepseek-ai/DeepSeek-V3",
        "models": [
            "deepseek-ai/DeepSeek-V3",
            "deepseek-ai/DeepSeek-R1",
            "deepseek-ai/DeepSeek-R1-Distill-Llama-70B",
            "Qwen/Qwen3-235B-A22B",
            "Qwen/Qwen3-30B-A3B",
            "Qwen/Qwen2.5-72B-Instruct",
            "Qwen/Qwen2.5-32B-Instruct",
            "Qwen/Qwen2.5-Coder-32B-Instruct",
            "THUDM/glm-4-9b-chat",
            "meta-llama/Meta-Llama-3.1-70B-Instruct",
            "meta-llama/Meta-Llama-3.1-8B-Instruct",
            "google/gemma-2-9b-it",
            "mistralai/Mistral-7B-Instruct-v0.3",
        ],
        "key_env": "SILICONFLOW_API_KEY",
        "docs": "https://cloud.siliconflow.cn",
    },
    "openai": {
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "models": [
            "gpt-4o-mini",
            "gpt-4o",
            "gpt-4-turbo",
            "gpt-4",
            "gpt-3.5-turbo",
            "o1-mini",
            "o1-preview",
            "o1",
            "o3-mini",
            "o3",
            "o4-mini",
        ],
        "key_env": "OPENAI_API_KEY",
        "docs": "https://platform.openai.com",
    },
    "anthropic": {
        "name": "Anthropic (Claude)",
        "base_url": "https://api.anthropic.com/v1",
        "model": "claude-3-5-haiku-20241022",
        "models": [
            "claude-3-5-haiku-20241022",
            "claude-3-5-sonnet-20241022",
            "claude-3-7-sonnet-20250219",
            "claude-opus-4-5",
            "claude-sonnet-4-5",
            "claude-haiku-4-5",
        ],
        "key_env": "ANTHROPIC_API_KEY",
        "docs": "https://console.anthropic.com",
    },
    "gemini": {
        "name": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.0-flash",
        "models": [
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
            "gemini-2.5-flash-preview-05-20",
            "gemini-2.5-pro-preview-06-05",
            "gemini-1.5-flash",
            "gemini-1.5-flash-8b",
            "gemini-1.5-pro",
        ],
        "key_env": "GEMINI_API_KEY",
        "docs": "https://aistudio.google.com",
    },
    "groq": {
        "name": "Groq (超快推理)",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "models": [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "llama3-70b-8192",
            "llama3-8b-8192",
            "mixtral-8x7b-32768",
            "gemma2-9b-it",
            "deepseek-r1-distill-llama-70b",
        ],
        "key_env": "GROQ_API_KEY",
        "docs": "https://console.groq.com",
    },
    "ollama": {
        "name": "Ollama (本地)",
        "base_url": "http://localhost:11434/v1",
        "model": "llama3.2",
        "models": [
            "llama3.2",
            "llama3.1",
            "llama3",
            "qwen2.5",
            "qwen2.5-coder",
            "deepseek-r1",
            "deepseek-coder-v2",
            "mistral",
            "gemma2",
            "phi3.5",
            "codellama",
            "yi",
        ],
        "key_env": "",
        "docs": "https://ollama.com/library",
    },
    "custom": {
        "name": "自定义 API",
        "base_url": "",
        "model": "",
        "models": [],
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
    "proxy": "",          # HTTP/HTTPS 代理，如 http://127.0.0.1:7890，留空不使用
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


def make_openai_client(cfg: dict = None):
    """
    根据当前模型配置创建 OpenAI client，自动处理代理。
    cfg 为 None 时自动读取 model_config.json。
    """
    from openai import OpenAI
    import httpx

    if cfg is None:
        cfg = load_model_config()

    proxy = cfg.get("proxy", "").strip()

    if proxy:
        http_client = httpx.Client(proxy=proxy)
        return OpenAI(
            api_key=cfg["api_key"],
            base_url=cfg["base_url"],
            http_client=http_client,
        )
    else:
        return OpenAI(
            api_key=cfg["api_key"],
            base_url=cfg["base_url"],
        )

