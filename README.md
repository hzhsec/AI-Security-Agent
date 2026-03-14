<div align="center">

# 🤖 AI Security Agent

**基于大语言模型的智能主机安全巡检系统**

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20Windows-lightgrey?logo=linux)](https://github.com)

> 让 AI 帮你做安全巡检 —— 告诉它你想检查什么，剩下的交给它。

</div>

---

## 功能特性

- **AI Agent Loop** — 基于 ReAct 范式，自动规划 → 执行 → 观察 → 再规划，完成复杂多步安全任务
- **双系统支持** — 同时支持 Linux（bash）和 Windows（cmd/PowerShell），自动切换提示词与语法
- **SSE 实时流式输出** — 每一步思考、命令和结果实时推送到前端，无需等待
- **工具自学习** — AI 执行命令失败后自动记录错误→正确用法，下次不再踩坑
- **AI 主动探索** — 一键让 AI 自动研究一个工具的完整用法并存入知识库
- **AI 对话助手** — 用自然语言描述模糊需求，AI 帮你精化成可执行的精准指令
- **快捷指令面板** — 内置 30 条安全巡检常用指令，支持自定义添加，按系统类型分组
- **多模型支持** — DeepSeek / 通义千问 / 文心一言 / Kimi / 智谱 GLM / OpenAI，UI 内一键切换

---

## 界面预览



**任务执行界面**

![image.png](https://cdn.jsdmirror.com/gh/hzhsec/upload@main/20260314172605421.png)

**工具知识库学习**

![image.png](https://cdn.jsdmirror.com/gh/hzhsec/upload@main/20260314172634588.png)


---

##  快速开始

### 环境要求

- Python **3.10+**
- 任意兼容 OpenAI API 格式的大模型 API Key

### 1. 克隆仓库

```bash
git clone https://github.com/hzhsec/AI-Security-Agent.git
cd AI-Security-Agent
```

### 2. 安装依赖

```bash
# 推荐使用虚拟环境
python -m venv venv

# Linux / macOS
source venv/bin/activate

# Windows
venv\Scripts\activate

pip install -r requirements.txt
```

### 3. 配置 API Key

启动后在页面右上角点击 **⚙ 模型配置** 即可通过 UI 配置，无需修改文件。

或者直接编辑 `model_config.json`（首次运行会自动生成）：

```json
{
  "provider": "deepseek",
  "api_key": "sk-xxxxxxxxxxxxxxxx",
  "base_url": "https://api.deepseek.com",
  "model": "deepseek-chat"
}
```

### 4. 启动服务

```bash
python api.py
```

打开浏览器访问 **http://localhost:8000**

---

##  项目结构

```
ai-check/
├── api.py              # FastAPI 服务入口，SSE 流式接口
├── agent.py            # Agent 核心逻辑（ReAct Loop + 双系统 Prompt）
├── executor.py         # 命令执行器（自动适配 Linux/Windows 编码）
├── tools.py            # 工具注册与调度（shell、文件读写、HTTP请求等）
├── tool_knowledge.py   # 工具知识库（错误记录、用法总结、AI自学）
├── memory.py           # 任务记忆与历史持久化
├── security.py         # 安全校验（黑名单命令拦截）
├── config.py           # 配置文件（模型预设、超时、黑名单等）
├── model_config.json   # 运行时模型配置（自动生成）
├── task_history.json   # 历史任务持久化（自动生成）
├── requirements.txt    # 依赖列表
└── static/
    └── index.html      # 前端单页应用
```

---

## 核心模块说明

### Agent Loop

```
用户输入任务
     ↓
 AI 思考 (thought)
     ↓
 选择工具 + 生成命令
     ↓
 执行命令
     ↓
 观察结果 → 注入上下文
     ↓
 判断是否完成？
  ├── 否 → 回到「AI 思考」
  └── 是 → 输出最终总结 (finish)
```

Agent 每步响应均为严格 JSON，包含 `thought`（思考）、`tool`（工具）、`command`（命令）等字段，前端实时渲染每一步的执行过程。

### 工具清单

| 工具名 | 功能描述 |
|--------|---------|
| `shell` | 执行单条 shell 命令（Linux bash / Windows cmd 均支持） |
| `shell_batch` | 批量执行多条命令 |
| `file_read` | 读取文件内容 |
| `file_write` | 写入/创建文件 |
| `http_request` | 发起 HTTP 请求 |
| `finish` | 任务完成，输出最终结论 |

### 双系统 Prompt

启动任务时前端传入 `os_type=linux` 或 `os_type=windows`，Agent 自动加载对应的系统提示词：

- **Linux 模式**：bash 语法、`/etc/passwd`、crontab、SSH 日志、SUID 检测等知识
- **Windows 模式**：PowerShell/cmd 语法、注册表、计划任务、事件日志、Defender 等知识

---

## API 接口

### 执行任务（SSE 流式）

```
GET /task/stream?task=检查系统是否被入侵&os_type=linux
```

事件流格式：

```jsonc
// 任务开始
{ "event": "start", "task_id": "uuid" }

// AI 思考中
{ "event": "thinking", "step": 1, "tool": "shell", "command": "ps aux", "thought": "..." }

// 步骤结果
{ "event": "step_result", "step": 1, "success": true, "result": "..." }

// 任务完成
{ "event": "done", "final_answer": "综合分析结论..." }
```

### 其他接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/history` | 获取任务历史 |
| `DELETE` | `/memory/{task_id}` | 删除指定任务记忆 |
| `GET` | `/tool-knowledge` | 获取工具知识库 |
| `POST` | `/tool-knowledge` | 手动添加工具知识 |
| `POST` | `/tool-knowledge/learn` | 触发 AI 自学工具 |
| `GET` | `/model/config` | 获取当前模型配置 |
| `POST` | `/model/config` | 保存模型配置 |
| `POST` | `/model/test` | 测试 API 连接 |

---

## ⚙️ 配置说明

`config.py` 中的关键参数：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `MAX_ITERATIONS` | `40` | 单次任务最大 Agent 循环轮次 |
| `COMMAND_TIMEOUT` | `120` | 命令执行超时（秒） |
| `MAX_OUTPUT_LENGTH` | `6000` | 命令输出最大字符数 |
| `API_PORT` | `8000` | Web 服务监听端口 |

### 命令安全策略

- **黑名单**（直接拒绝执行）：`rm -rf /`、`mkfs`、fork bomb 等毁灭性操作
- **高危警告**（记录日志但不阻止）：`shutdown`、`reboot` 等

---

##  支持的模型

| 提供商 | 推荐模型 | API 文档 |
|--------|---------|---------|
| **DeepSeek** | `deepseek-chat` | [platform.deepseek.com](https://platform.deepseek.com) |
| **通义千问** | `qwen-plus` | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com) |
| **文心一言** | `ernie-4.5-8k` | [qianfan.cloud.baidu.com](https://qianfan.cloud.baidu.com) |
| **Kimi** | `moonshot-v1-8k` | [platform.moonshot.cn](https://platform.moonshot.cn) |
| **智谱 GLM** | `glm-4-flash` | [open.bigmodel.cn](https://open.bigmodel.cn) |
| **OpenAI** | `gpt-4o-mini` | [platform.openai.com](https://platform.openai.com) |
| **自定义** | 任意兼容 OpenAI API 的服务 | — |

> 推荐使用 **DeepSeek** —— 推理能力强、价格低、对中文运维场景友好。

---

## 工具自学习机制

```
命令执行失败
     ↓
AI 分析错误信息 + 帮助文档
     ↓
JSON 中填写 learn_tool + learn_usage
     ↓
系统自动存入知识库
     ↓
下次执行同一工具 → 知识自动注入上下文
```

也可以手动触发「AI 主动探索」：AI 会依次执行 `查看帮助 → 读注释 → 试运行 → 测试参数 → 总结`，全流程自动。

---

<div align="center">
  <sub>Built with ❤️ · Powered by LLM</sub>
</div>
