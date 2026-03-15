# 🤖 AI Security Agent

**基于大语言模型的智能主机安全巡检系统**

[![img](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/) [![img](https://img.shields.io/badge/FastAPI-0.104%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/) [![img](https://img.shields.io/badge/License-MIT-green)](vscode-file://vscode-app/f:/WorkBuddy/resources/app/out/vs/code/electron-sandbox/workbench/LICENSE) [![img](https://img.shields.io/badge/Platform-Linux%20%7C%20Windows-lightgrey?logo=linux)](https://github.com/)

> 让 AI 帮你做安全巡检 —— 告诉它你想检查什么，剩下的交给它。



------

## 功能特性

- **AI Agent Loop** — 基于 ReAct 范式，自动规划 → 执行 → 观察 → 再规划，完成复杂多步安全任务
- **双系统支持** — 同时支持 Linux（bash）和 Windows（cmd/PowerShell），自动切换提示词与语法
- **SSE 实时流式输出** — 每一步思考、命令和结果实时推送到前端，无需等待
- **任务中途停止** — 执行中可随时点击停止按钮，Agent 完成当前步骤后立即终止
- **工具自学习** — AI 执行命令失败后自动记录错误→正确用法，下次不再踩坑
- **AI 主动探索** — 一键让 AI 自动研究一个工具的完整用法并存入知识库
- **AI 对话助手** — 用自然语言描述模糊需求，AI 帮你精化成可执行的精准指令
- **提示词生成** — 将任务执行结果一键生成安全分析/运维/故障排查提示词，可复制到任意 AI 使用
- **快捷指令面板** — 内置 30 条安全巡检常用指令，支持自定义添加，按系统类型分组
- **多模型支持** — 支持 15+ 主流提供商，UI 内一键切换，支持自定义 API 端点和代理

------

## 界面预览

**任务执行界面**

![img](https://cdn.jsdmirror.com/gh/hzhsec/upload@main/20260314172605421.png)

**工具知识库学习**

![img](https://cdn.jsdmirror.com/gh/hzhsec/upload@main/20260314172634588.png)

**模型配置**

![image.png](https://cdn.jsdmirror.com/gh/hzhsec/upload@main/20260315200331184.png)

------

## 快速开始

### 环境要求

- Python **3.10+**
- 任意兼容 OpenAI API 格式的大模型 API Key

### 1. 克隆仓库

**bash**

复制



```bash
git clone https://github.com/hzhsec/AI-Security-Agent.git
cd AI-Security-Agent
```

### 2. 安装依赖

**bash**

复制



```bash
# 推荐使用虚拟环境
python -m venv venv

# Linux / macOS
source venv/bin/activate

# Windows
venv\Scripts\activate

pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple/
```

### 3. 启动服务

**bash**

复制



```bash
python api.py
```

打开浏览器访问 **[http://localhost:8000](http://localhost:8000/)**

### 4. 配置 API Key

启动后点击右上角 **⚙ 模型配置** 按钮，在弹窗中完成配置：

1. 从提供商列表中选择你的服务商（DeepSeek、通义千问等）
2. 填写 API Key
3. 可选：填写代理地址（见下方代理配置说明）
4. 点击 **🔌 测试连接** 验证可用性
5. 点击 **保存配置** 即可，无需重启服务

也可以直接编辑 `model_config.json`（首次运行自动生成）：

**json**

复制



```json
{
  "provider": "deepseek",
  "api_key": "sk-xxxxxxxxxxxxxxxx",
  "base_url": "https://api.deepseek.com",
  "model": "deepseek-chat",
  "proxy": ""
}
```

------

## 代理配置

如果你的网络需要通过代理才能访问 API（例如访问 OpenAI、Anthropic、Gemini 等境外服务），可以在模型配置中填写代理地址。

**在 UI 中配置：**

打开 **⚙ 模型配置** 弹窗，在 **HTTP 代理** 输入框中填写代理地址，例如：

```
http://127.0.0.1:7890
```

**在配置文件中配置：**

编辑 `model_config.json`，填写 `proxy` 字段：

**json**

复制



```json
{
  "provider": "openai",
  "api_key": "sk-xxxxxxxxxxxxxxxx",
  "base_url": "https://api.openai.com/v1",
  "model": "gpt-4o-mini",
  "proxy": "http://127.0.0.1:7890"
}
```

> 代理设置对所有接口生效，包括任务执行、AI 对话、测试连接。留空则不使用代理。 支持 HTTP / HTTPS 代理格式。



------

## 使用方式

### 执行安全巡检任务

1. 在顶部选择目标系统类型（**🐧 Linux** 或 **🪟 Windows**）
2. 在输入框中用自然语言描述任务，例如：
   - `检查系统是否存在异常登录和可疑进程`
   - `扫描开放端口，检查是否有未知服务在监听`
   - `检查计划任务和启动项，排查持久化后门`
   - `查看最近的系统日志，是否有异常报错`
3. 点击 **执行** 或按 `Ctrl+Enter` 开始，前端实时展示 AI 的每一步思考和命令结果
4. 任务执行中可点击 **⏹ 停止** 随时中断，Agent 完成当前步骤后安全退出

### 快捷指令

点击主界面左侧 **快捷指令** 面板，可一键发送常用安全巡检命令。指令按 Linux / Windows 分组展示，点击即可填入输入框。支持自定义添加/删除快捷指令，数据保存在本地浏览器。

### AI 对话助手

切换到 **💬 AI 助手** 标签页，提供两种对话模式：

- **任务精化模式**：描述你的模糊想法，AI 帮你生成一条精准的 Agent 任务指令，点击"▶ 发送给 Agent 执行"可直接切换到执行页并填入任务
- **自由问答模式**：直接咨询 Linux 命令、安全运维、故障排查等专业问题

### 提示词生成

在 **执行历史** 页面查看任务详情后，可一键生成专业分析提示词，用于在 ChatGPT、Kimi 等任意 AI 产品中进行深度分析：

| 提示词风格   | 适用场景           |
| ------------ | ------------------ |
| 安全巡检分析 | 入侵检测、风险评估 |
| 运维状态分析 | 资源使用、性能瓶颈 |
| 故障排查     | 错误分析、修复方案 |
| 执行报告汇总 | 命令记录整理成报告 |

### 工具知识库

切换到 **🧠 工具知识库** 标签页：

- **自动学习**：AI 执行命令失败时，自动分析原因并将正确用法存入知识库，下次执行同类命令时自动参考，不会重蹈覆辙
- **AI 主动探索**：点击 **🤖 让AI自学工具**，输入工具名和路径，AI 会依次执行「查看帮助 → 读注释 → 试运行 → 测试参数 → 总结」，全流程自动，结果永久保存
- **重新探索**：对已有知识条目点击"🤖 重新探索"，可用最新版本覆盖旧知识
- **手动管理**：支持手动添加、补充、删除知识条目；支持一键清空全部知识库

### 数据管理

**执行历史** 页面：

- 查看所有历史任务及每步执行详情
- 勾选多条记录进行批量删除
- 删除单条记录或清除全部历史
- 一键清空所有数据（同时清除历史 + 工具知识库）

**⚙ 模型配置** 弹窗底部：

- **清空所有 API Key**：同时清除浏览器本地缓存的全部提供商 Key 和服务端配置文件中的 Key，方便交接或重置环境

------

## 项目结构

```
AI-Security-Agent/
├── api.py              # FastAPI 服务入口，SSE 流式接口
├── agent.py            # Agent 核心逻辑（ReAct Loop + 双系统 Prompt）
├── executor.py         # 命令执行器（自动适配 Linux/Windows 编码）
├── tools.py            # 工具注册与调度（shell、文件读写、HTTP请求等）
├── tool_knowledge.py   # 工具知识库（错误记录、用法总结、AI自学）
├── memory.py           # 任务记忆与历史持久化
├── security.py         # 安全校验（黑名单命令拦截）
├── config.py           # 全局配置（模型预设、超时、黑名单、端口等）
├── model_config.json   # 运行时模型配置（自动生成）
├── task_history.json   # 历史任务持久化（自动生成）
├── tool_knowledge.json # 工具知识库持久化（自动生成）
├── agent.log           # 运行日志（自动生成）
├── requirements.txt    # 依赖列表
└── static/
    └── index.html      # 前端单页应用
```

------

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

| 工具名         | 功能描述                                               |
| -------------- | ------------------------------------------------------ |
| `shell`        | 执行单条 shell 命令（Linux bash / Windows cmd 均支持） |
| `shell_batch`  | 批量执行多条命令                                       |
| `file_read`    | 读取文件内容                                           |
| `file_write`   | 写入/创建文件                                          |
| `http_request` | 发起 HTTP 请求                                         |
| `finish`       | 任务完成，输出最终结论                                 |

### 双系统 Prompt

启动任务时前端传入 `os_type=linux` 或 `os_type=windows`，Agent 自动加载对应的系统提示词：

- **Linux 模式**：bash 语法、`/etc/passwd`、crontab、SSH 日志、SUID 检测等知识
- **Windows 模式**：PowerShell/cmd 语法、注册表、计划任务、事件日志、Defender 等知识

------

## API 接口

### 执行任务（SSE 流式）

```
GET /task/stream?task=检查系统是否被入侵&os_type=linux
```

事件流格式：

**jsonc**

复制



```jsonc
// 任务开始
{ "event": "start", "task_id": "abc12345" }

// AI 思考中
{ "event": "thinking", "step": 1, "tool": "shell", "command": "ps aux", "thought": "..." }

// 步骤结果
{ "event": "step_result", "step": 1, "success": true, "result": "..." }

// 任务完成
{ "event": "done", "final_answer": "综合分析结论..." }

// 任务被手动停止
{ "event": "stopped" }
```

### 完整接口列表

| 方法     | 路径                                       | 说明                             |
| -------- | ------------------------------------------ | -------------------------------- |
| `GET`    | `/task/stream`                             | 执行任务（SSE 流式输出）         |
| `GET`    | `/task`                                    | 执行任务（同步，等待完成返回）   |
| `POST`   | `/task`                                    | 执行任务（POST Body 方式）       |
| `POST`   | `/task/stop/{task_id}`                     | 停止正在执行的任务               |
| `GET`    | `/task/running`                            | 获取当前运行中的任务列表         |
| `GET`    | `/history`                                 | 获取任务历史列表                 |
| `GET`    | `/history/{task_id}`                       | 获取指定任务详情                 |
| `GET`    | `/memory/stats`                            | 获取记忆统计信息                 |
| `DELETE` | `/memory/all`                              | 清空全部历史记忆                 |
| `DELETE` | `/memory/{task_id}`                        | 删除指定任务记忆                 |
| `GET`    | `/tool-knowledge`                          | 获取全部工具知识库               |
| `GET`    | `/tool-knowledge/{tool_name}`              | 获取指定工具知识                 |
| `POST`   | `/tool-knowledge`                          | 手动添加/更新工具知识            |
| `DELETE` | `/tool-knowledge/all`                      | 清空全部工具知识库               |
| `DELETE` | `/tool-knowledge/{tool_name}`              | 删除指定工具知识                 |
| `POST`   | `/tool-knowledge/learn`                    | 触发 AI 自学指定工具（SSE 流式） |
| `GET`    | `/tool-knowledge/learn/{tool_name}/status` | 查询工具自学状态                 |
| `GET`    | `/model/presets`                           | 获取所有模型提供商预设           |
| `GET`    | `/model/config`                            | 获取当前模型配置（脱敏）         |
| `POST`   | `/model/config`                            | 保存模型配置（支持 proxy）       |
| `DELETE` | `/model/config/key`                        | 清除服务端保存的 API Key         |
| `POST`   | `/model/test`                              | 测试 API 连接（支持 proxy）      |
| `POST`   | `/chat`                                    | AI 对话（同步）                  |
| `POST`   | `/chat/stream`                             | AI 对话（SSE 流式）              |
| `POST`   | `/prompt/generate`                         | 生成分析提示词                   |
| `GET`    | `/prompt/templates`                        | 获取提示词模板列表               |
| `GET`    | `/health`                                  | 健康检查                         |
| `GET`    | `/docs`                                    | Swagger 接口文档                 |

------

## ⚙️ 配置说明

`config.py` 中的关键参数：

| 参数                | 默认值      | 说明                        |
| ------------------- | ----------- | --------------------------- |
| `MAX_ITERATIONS`    | `40`        | 单次任务最大 Agent 循环轮次 |
| `COMMAND_TIMEOUT`   | `120`       | 命令执行超时（秒）          |
| `MAX_OUTPUT_LENGTH` | `6000`      | 命令输出最大字符数          |
| `API_HOST`          | `0.0.0.0`   | 服务监听地址                |
| `API_PORT`          | `8000`      | 服务监听端口                |
| `LOG_FILE`          | `agent.log` | 日志文件路径                |
| `LOG_LEVEL`         | `INFO`      | 日志级别                    |

### 命令安全策略

- **黑名单**（直接拒绝执行）：`rm -rf /`、`rm -rf /*`、`mkfs`、fork bomb `:(){ :|:& };:`、`dd if=/dev/zero of=/dev/sd*`、`chmod -R 777 /`、`passwd root`、`userdel root` 等毁灭性操作
- **高危警告**（记录日志但不阻止）：`shutdown`、`reboot`、`halt`、`poweroff`、`init 0/6` 等

------

## 支持的模型

支持所有兼容 OpenAI API 格式的服务，内置以下提供商预设：

| 提供商                 | 推荐模型                                    | API 文档                                                     |
| ---------------------- | ------------------------------------------- | ------------------------------------------------------------ |
| **DeepSeek**           | `deepseek-chat` / `deepseek-reasoner`       | [platform.deepseek.com](https://platform.deepseek.com/)      |
| **通义千问**           | `qwen-plus` / `qwen3-235b-a22b`             | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com/) |
| **文心一言**           | `ernie-4.5-8k` / `ernie-4.5-turbo-128k`     | [qianfan.cloud.baidu.com](https://qianfan.cloud.baidu.com/)  |
| **月之暗面 (Kimi)**    | `moonshot-v1-8k` / `kimi-k2-0520`           | [platform.moonshot.cn](https://platform.moonshot.cn/)        |
| **智谱 GLM**           | `glm-4-flash` / `glm-4-plus`                | [open.bigmodel.cn](https://open.bigmodel.cn/)                |
| **腾讯混元**           | `hunyuan-turbo` / `hunyuan-pro`             | [cloud.tencent.com/product/hunyuan](https://cloud.tencent.com/product/hunyuan) |
| **字节豆包**           | `doubao-1-5-pro-32k` / `deepseek-r1-250528` | [volcengine.com/product/ark](https://www.volcengine.com/product/ark) |
| **讯飞星火**           | `4.0Ultra` / `max-32k`                      | [console.xfyun.cn](https://console.xfyun.cn/services/bm35)   |
| **MiniMax**            | `MiniMax-M1` / `MiniMax-Text-01`            | [platform.minimaxi.com](https://platform.minimaxi.com/)      |
| **硅基流动**           | `DeepSeek-V3` / `Qwen3-235B-A22B`           | [cloud.siliconflow.cn](https://cloud.siliconflow.cn/)        |
| **OpenAI**             | `gpt-4o-mini` / `o4-mini`                   | [platform.openai.com](https://platform.openai.com/)          |
| **Anthropic (Claude)** | `claude-3-5-sonnet` / `claude-3-7-sonnet`   | [console.anthropic.com](https://console.anthropic.com/)      |
| **Google Gemini**      | `gemini-2.0-flash` / `gemini-2.5-pro`       | [aistudio.google.com](https://aistudio.google.com/)          |
| **Groq**               | `llama-3.3-70b-versatile`                   | [console.groq.com](https://console.groq.com/)                |
| **Ollama（本地）**     | `llama3.2` / `qwen2.5` / `deepseek-r1`      | [ollama.com/library](https://ollama.com/library)             |
| **自定义 API**         | 任意兼容 OpenAI 格式的服务                  | 在 UI 中填写 base_url 即可                                   |

> 🆓 **免费推荐**：通义千问（有免费额度）、智谱 GLM-4-Flash（完全免费）、Groq（免费且速度极快）、Ollama（本地离线运行，无需 Key）
>
> ⭐ **综合推荐**：DeepSeek —— 推理能力强、价格极低、对中文运维场景友好



------

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

也可以手动触发「AI 主动探索」：AI 会依次执行 `查看帮助 → 读注释 → 试运行 → 测试参数 → 总结`，全流程自动，结论永久保存，下次使用直接参考。
