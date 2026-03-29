# AI Security Agent

基于大语言模型的主机安全巡检系统，支持 Linux / Windows，提供任务执行、工具知识库、MCP 风格技能包、执行历史和良性白名单。

## 主要功能

- AI Agent Loop：自动思考、执行、观察、总结
- 双系统支持：Linux bash / Windows cmd、PowerShell
- SSE 流式输出：前端实时查看每一步结果
- 工具知识库：失败自动学习，也可手动补充和 AI 主动探索
- MCP 技能包：支持导入、导出、执行、卸载结构化工具能力
- 良性白名单：减少把自有服务和正常外联误判为恶意行为
- 多模型支持：兼容 OpenAI API 格式的模型服务

## 界面预览

**任务执行界面**

![任务执行界面](https://cdn.jsdmirror.com/gh/hzhsec/upload@main/20260314172605421.png)

**工具知识库学习**

![image.png](https://cdn.jsdmirror.com/gh/hzhsec/upload@main/20260329163406934.png)

**模型配置**

![模型配置](https://cdn.jsdmirror.com/gh/hzhsec/upload@main/20260315200331184.png)

## 快速开始

### 环境要求

- Python 3.10+
- 任意兼容 OpenAI API 格式的模型 API Key

### 安装

```bash
git clone https://github.com/hzhsec/AI-Security-Agent.git
cd AI-Security-Agent

python -m venv venv

# Linux / macOS
source venv/bin/activate

# Windows
venv\Scripts\activate

pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple/
```

### 启动

```bash
python api.py
```

浏览器打开 [http://localhost:8000/](http://localhost:8000/)。

### 配置模型

启动后点击右上角“模型配置”，填写：

- 提供商
- API Key
- Base URL
- Model
- 可选代理

也可以直接编辑 `model_config.json`。

## 基本使用

### 任务执行

1. 选择目标系统类型
2. 输入自然语言任务
3. 点击“执行”
4. 在前端查看流式过程和最终结论

示例任务：

- `检查系统是否存在异常登录和可疑进程`
- `检查计划任务和启动项，排查持久化后门`
- `查看最近的系统日志，是否有异常报错`

### AI 对话助手

- 任务精化：把模糊需求改成适合 Agent 执行的任务
- 自由问答：咨询命令、安全排查、运维问题

### 执行历史

- 查看历史任务和每一步执行结果
- 删除单条或批量清理
- 基于执行结果生成分析提示词

## 工具知识库

工具知识库用于解决“AI 会执行命令，但不知道某个工具具体怎么用”的问题。

支持三种方式：

- 自动学习：命令失败后记录正确用法
- AI 主动探索：指定工具名和路径，让 AI 自动学习
- 手动维护：自己补充工具路径、简介、帮助摘要、正确命令

项目默认已经内置一部分工具知识。当前 `check` 目录下有两个预置工具：

- `Linuxgun`
- `whohk`

这两个工具的常用知识已经预先整理，适合直接用于 Linux 安全巡检、应急排查和主机状态检查。

常见场景：

- 让 AI 学习 `nmap`、`dirsearch`、`whohk`
- 把网上搜到的工具说明粘贴给 AI 做参考
- 对已有知识重新探索覆盖旧结果

## MCP 技能包

项目支持把工具能力整理成 MCP 风格技能包。导入后，Agent 不再只靠 prompt 猜命令，而是可以直接调用结构化能力，例如：

- `nmap_web_scan`
- `dirsearch_quick_scan`
- `nmap_analyze_result`

### MCP 技能包能做什么

- 导入已有技能包
- 导出当前技能包
- 在前端查看已导入技能
- 执行技能
- 卸载技能

### 前端入口

打开“工具知识库”页，可以看到：

- `导入技能包`
- `导出技能包`
- `已导入的技能`
- `卸载`

### 支持的技能包格式

推荐使用 `.json` 文件。后缀不是关键，关键是内容必须是合法 JSON。

支持两种内容结构。

单个工具：

```json
{
  "tool": "dirsearch",
  "tool_path": "python dirsearch.py",
  "summary": "Web 目录扫描工具",
  "capabilities": [
    {
      "name": "dirsearch_quick_scan",
      "description": "快速目录扫描",
      "command_template": "{tool_path} -u {target} -t 20 --random-agent --quiet-mode",
      "args_schema": {
        "type": "object",
        "properties": {
          "target": { "type": "string" }
        },
        "required": ["target"]
      }
    }
  ]
}
```

整包注册表：

```json
{
  "tools": [
    {
      "tool": "dirsearch",
      "tool_path": "python dirsearch.py",
      "summary": "Web 目录扫描工具",
      "capabilities": [
        {
          "name": "dirsearch_quick_scan",
          "description": "快速目录扫描",
          "command_template": "{tool_path} -u {target} -t 20 --random-agent --quiet-mode",
          "args_schema": {
            "type": "object",
            "properties": {
              "target": { "type": "string" }
            },
            "required": ["target"]
          }
        }
      ]
    }
  ]
}
```

### 导入步骤

1. 准备一个 `.json` 技能包文件
2. 打开“工具知识库”
3. 点击“导入技能包”
4. 选择文件
5. 导入成功后，在“已导入的技能”区域查看

### 使用建议

- `tool_path` 尽量写成你本机真实可执行的形式
- Windows 下如有 `venv`，优先写解释器绝对路径
- 尽量避免中文路径；如果必须使用中文路径，建议先实测命令是否能被项目执行器正常调用

示例：

```json
{
  "tool": "dirsearch",
  "tool_path": "C:\\tools\\venv\\Scripts\\python.exe C:\\tools\\dirsearch\\dirsearch.py",
  "summary": "Web 目录扫描工具",
  "capabilities": [
    {
      "name": "dirsearch_quick_scan",
      "description": "快速目录扫描",
      "command_template": "{tool_path} -u {target} -t 20 --random-agent --quiet-mode",
      "args_schema": {
        "type": "object",
        "properties": {
          "target": { "type": "string" }
        },
        "required": ["target"]
      }
    }
  ]
}
```

### 兼容性说明

当前兼容的是“工具定义型 JSON 技能包”，不是所有第三方 MCP Server 配置都能直接导入。

可直接导入的通常是：

- 本项目导出的技能包
- 结构接近的自定义 JSON 技能包

不能直接导入的通常是：

- npm / pip 安装型 MCP Server
- 只包含 `stdio` / `command` / `args` 的客户端配置
- 某些平台专用的 manifest

## 常用接口

完整接口可在 [http://localhost:8000/docs](http://localhost:8000/docs) 查看。

常用接口：

- `GET /task/stream`：流式执行任务
- `GET /history`：查看执行历史
- `GET /tool-knowledge`：查看工具知识库
- `POST /tool-knowledge/learn`：AI 学习指定工具
- `GET /mcp/registry`：查看已导入技能
- `POST /mcp/registry/import`：导入技能包
- `GET /mcp/registry/export`：导出技能包
- `DELETE /mcp/registry/{tool_name}`：卸载技能
- `POST /mcp/execute`：直接执行某个技能

## 项目结构

```text
AI-Security-Agent/
├── api.py
├── agent.py
├── executor.py
├── tools.py
├── tool_knowledge.py
├── tool_registry.py
├── mcp_server.py
├── memory.py
├── security.py
├── config.py
├── static/
│   └── index.html
├── model_config.json
├── task_history.json
├── tool_knowledge.json
└── tool_registry.json
```

## 说明

- 默认提供 Web UI，也支持通过接口和最小 MCP Server 调用
- Windows 下尽量使用 UTF-8 和英文路径，复杂工具更稳定
- 如果页面样式或脚本没更新，先尝试 `Ctrl+F5` 强刷
