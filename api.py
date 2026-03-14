"""
Web API 接口 - FastAPI + SSE 实时流式输出
"""
import json
import logging
import asyncio
import threading
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from agent import agent
from memory import memory
from config import (
    API_HOST, API_PORT, LOG_FILE, LOG_LEVEL,
    MODEL_PRESETS, load_model_config, save_model_config,
)
from tool_knowledge import tool_knowledge

# ─── 日志配置 ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ─── FastAPI App ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="AI Agent运维管理",
    description="通过 AI 自动执行任务的智能代理系统",
    version="1.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件（前端界面）
import os
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# 全局：管理运行中任务的停止信号  { task_id: threading.Event }
_stop_events: Dict[str, threading.Event] = {}


# ─── 请求/响应模型 ────────────────────────────────────────────────────────────

class TaskRequest(BaseModel):
    task: str
    task_id: Optional[str] = None
    os_type: str = "linux"   # "linux" | "windows"


class TaskResponse(BaseModel):
    task_id: str
    task: str
    status: str
    steps: list
    final_answer: str
    duration: float
    total_steps: int


class ModelConfigRequest(BaseModel):
    provider: str           # 预设key，如 "deepseek" / "qwen" / "custom"
    api_key: str
    base_url: str
    model: str


class PromptGenRequest(BaseModel):
    task_id: Optional[str] = None   # 基于某个任务生成提示词
    raw_text: Optional[str] = None  # 基于自由文本生成提示词
    style: str = "security"         # security / ops / debug / custom


class ChatRequest(BaseModel):
    """AI 对话请求 - 用于帮助用户完善任务描述"""
    message: str
    history: Optional[list] = []    # 对话历史 [{"role":"user/assistant","content":"..."}]
    mode: str = "refine"            # refine=完善任务 | free=自由对话


class ToolKnowledgeUpdateRequest(BaseModel):
    tool_name: str
    usage_hint: Optional[str] = None
    help_text: Optional[str] = None
    failed_command: Optional[str] = None
    error_output: Optional[str] = None
    fixed_command: Optional[str] = None


class ToolLearnRequest(BaseModel):
    """触发 AI 自主学习某个工具"""
    tool_name: str          # 工具名，如 "whocheck"
    tool_path: str          # 工具路径，如 "/root/check/whocheck"


# ─── 路由 ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    """返回前端页面"""
    try:
        with open("static/index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse("""
        <html><body>
        <h2>AI Linux Agent API</h2>
        <p>接口文档: <a href="/docs">/docs</a></p>
        <p>快速测试: <a href="/task?task=查看磁盘空间">/task?task=查看磁盘空间</a></p>
        </body></html>
        """)


@app.get("/task")
async def run_task_get(
    task: str = Query(..., description="要执行的任务描述"),
    os_type: str = Query("linux", description="目标系统类型: linux 或 windows"),
):
    """
    GET 方式执行任务（同步，等待全部完成再返回）。
    示例: GET /task?task=查看系统CPU使用率&os_type=linux
    """
    if not task.strip():
        raise HTTPException(status_code=400, detail="task 参数不能为空")

    os_type = os_type.lower().strip()
    if os_type not in ("linux", "windows"):
        os_type = "linux"

    logger.info(f"[API] 接收到任务: {task}  [os={os_type}]")

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, agent.run, task, None, os_type)
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"[API] 任务执行异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/task")
async def run_task_post(request: TaskRequest):
    """
    POST 方式执行任务（同步）。
    Body: {"task": "安装并启动 nginx", "os_type": "linux"}
    """
    if not request.task.strip():
        raise HTTPException(status_code=400, detail="task 不能为空")

    os_type = (request.os_type or "linux").lower().strip()
    if os_type not in ("linux", "windows"):
        os_type = "linux"

    logger.info(f"[API] POST 任务: {request.task}  [os={os_type}]")

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, agent.run, request.task, request.task_id, os_type
        )
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"[API] 任务执行异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/task/stream")
async def stream_task(
    task: str = Query(..., description="要执行的任务描述"),
    os_type: str = Query("linux", description="目标系统类型: linux 或 windows"),
):
    """
    流式执行任务（SSE），实时推送每一步执行结果。
    示例: GET /task/stream?task=查看系统负载&os_type=windows
    """
    if not task.strip():
        raise HTTPException(status_code=400, detail="task 参数不能为空")

    os_type = os_type.lower().strip()
    if os_type not in ("linux", "windows"):
        os_type = "linux"

    import uuid
    task_id = str(uuid.uuid4())[:8]

    # 创建该任务的停止信号
    stop_event = threading.Event()
    _stop_events[task_id] = stop_event

    async def event_generator():
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def run_agent():
            for event in agent.stream_run(task, task_id=task_id, os_type=os_type, stop_event=stop_event):
                loop.call_soon_threadsafe(queue.put_nowait, event)
            loop.call_soon_threadsafe(queue.put_nowait, None)  # 结束信号

        loop.run_in_executor(None, run_agent)

        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            # 任务结束后清理 stop_event
            _stop_events.pop(task_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/task/stop/{task_id}")
async def stop_task(task_id: str):
    """
    停止正在执行的任务。
    向目标任务发送停止信号，任务将在当前步骤完成后终止。
    """
    if task_id not in _stop_events:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不在运行中或已结束")
    _stop_events[task_id].set()
    logger.info(f"[API] 已发送停止信号 → 任务 [{task_id}]")
    return {"ok": True, "task_id": task_id, "message": "停止信号已发送，任务将在当前步骤完成后终止"}


@app.get("/task/running")
async def list_running_tasks():
    """获取当前正在运行的任务列表"""
    return {"ok": True, "running": list(_stop_events.keys()), "count": len(_stop_events)}


@app.get("/history")
async def get_history(limit: int = Query(20, ge=1, le=100)):
    """获取任务执行历史列表"""
    sessions = memory.list_sessions(limit=limit)
    return JSONResponse(content={"sessions": sessions, "total": len(sessions)})


@app.get("/history/{task_id}")
async def get_task_detail(task_id: str):
    """获取指定任务的详细信息"""
    session = memory.get_session(task_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
    return JSONResponse(content=session.to_dict())


@app.get("/health")
async def health_check():
    """健康检查接口"""
    cfg = load_model_config()
    return {
        "status": "ok",
        "service": "AI Linux Agent",
        "version": "1.2.0",
        "model": f"{cfg.get('provider','?')} / {cfg.get('model','?')}",
    }


# ─── 记忆管理接口 ─────────────────────────────────────────────────────────────

@app.get("/memory/stats")
async def memory_stats():
    """获取记忆统计信息"""
    return JSONResponse(content=memory.stats())


@app.delete("/memory/all")
async def clear_all_memory():
    """一键清除全部记忆（内存 + 持久化文件）"""
    count = memory.clear_all()
    logger.info(f"[API] 清除全部记忆，共 {count} 条")
    return {"ok": True, "cleared": count, "message": f"已清除 {count} 条历史记忆"}


@app.delete("/memory/{task_id}")
async def clear_one_memory(task_id: str):
    """清除指定任务的记忆"""
    ok = memory.clear_session(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
    return {"ok": True, "task_id": task_id, "message": "已删除该任务记忆"}


# ─── 模型配置接口 ─────────────────────────────────────────────────────────────

@app.get("/model/presets")
async def get_model_presets():
    """获取所有模型预设列表"""
    return JSONResponse(content={"presets": MODEL_PRESETS})


@app.get("/model/config")
async def get_model_config():
    """获取当前模型配置（脱敏：api_key 只显示前8位）"""
    cfg = load_model_config()
    safe_cfg = cfg.copy()
    key = safe_cfg.get("api_key", "")
    safe_cfg["api_key_masked"] = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
    safe_cfg["api_key"] = safe_cfg["api_key_masked"]
    return JSONResponse(content=safe_cfg)


@app.post("/model/config")
async def set_model_config(request: ModelConfigRequest):
    """
    保存模型配置（切换 API 提供商）。
    之后所有任务都使用新配置，无需重启服务。
    """
    if not request.api_key.strip():
        raise HTTPException(status_code=400, detail="api_key 不能为空")
    if not request.base_url.strip():
        raise HTTPException(status_code=400, detail="base_url 不能为空")
    if not request.model.strip():
        raise HTTPException(status_code=400, detail="model 不能为空")

    cfg = {
        "provider": request.provider,
        "api_key": request.api_key,
        "base_url": request.base_url,
        "model": request.model,
    }
    save_model_config(cfg)
    logger.info(f"[API] 模型配置已更新: {request.provider} / {request.model}")
    return {
        "ok": True,
        "message": f"模型已切换到 {request.provider} / {request.model}",
        "provider": request.provider,
        "model": request.model,
    }


@app.post("/model/test")
async def test_model_connection(request: ModelConfigRequest):
    """测试模型配置是否可用（发送一条简单消息验证连通性）"""
    from openai import OpenAI
    try:
        client = OpenAI(api_key=request.api_key, base_url=request.base_url)
        resp = client.chat.completions.create(
            model=request.model,
            messages=[{"role": "user", "content": "回复数字1，不要其他内容"}],
            max_tokens=10,
            temperature=0,
        )
        reply = resp.choices[0].message.content.strip()
        return {"ok": True, "message": f"连接成功，模型回复: {reply}"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"连接失败: {str(e)}")


# ─── 提示词生成接口 ───────────────────────────────────────────────────────────

# 各类场景的提示词模板
_PROMPT_TEMPLATES = {
    "security": (
        "你是一名 Linux 主机安全专家，请对以下内容进行入侵检测分析：\n\n"
        "{content}\n\n"
        "请从以下维度逐一分析：\n"
        "1. 异常账号/权限变更\n2. 可疑进程/服务\n3. 异常网络连接\n"
        "4. 持久化后门迹象\n5. 日志异常\n6. 文件篡改\n\n"
        "最后给出：【风险等级】（高/中/低/无）和【处置建议】"
    ),
    "ops": (
        "你是一名 Linux 运维工程师，请分析以下系统信息并给出运维建议：\n\n"
        "{content}\n\n"
        "请分析：\n"
        "1. 系统资源使用情况（CPU/内存/磁盘）\n2. 服务运行状态\n"
        "3. 潜在性能瓶颈\n4. 配置优化建议\n5. 预防性维护建议"
    ),
    "debug": (
        "你是一名 Linux 故障排查专家，请分析以下错误信息并提供解决方案：\n\n"
        "{content}\n\n"
        "请提供：\n"
        "1. 问题根因分析\n2. 逐步排查步骤\n3. 具体修复命令\n"
        "4. 预防再次发生的措施"
    ),
    "summary": (
        "请将以下 Linux 命令执行记录整理成一份简洁的巡检报告：\n\n"
        "{content}\n\n"
        "报告格式：\n"
        "## 巡检摘要\n## 发现的问题\n## 正常项目\n## 建议操作"
    ),
}


@app.post("/prompt/generate")
async def generate_prompt(request: PromptGenRequest):
    """
    生成分析提示词。
    - task_id: 从指定任务的执行结果生成提示词
    - raw_text: 从自由文本生成提示词
    - style: 提示词风格 (security/ops/debug/summary)
    """
    content = ""

    # 从任务历史提取内容
    if request.task_id:
        session = memory.get_session(request.task_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"任务 {request.task_id} 不存在")
        lines = [f"任务: {session.task}\n"]
        for step in session.steps:
            lines.append(f"[Step {step.step_no}] {step.tool}: {step.command}")
            lines.append(f"结果: {step.result[:500]}")
            lines.append("---")
        if session.final_answer:
            lines.append(f"\nAI总结: {session.final_answer[:1000]}")
        content = "\n".join(lines)

    # 使用自由文本
    elif request.raw_text:
        content = request.raw_text.strip()

    else:
        raise HTTPException(status_code=400, detail="task_id 和 raw_text 至少提供一个")

    # 选择模板
    style = request.style if request.style in _PROMPT_TEMPLATES else "security"
    template = _PROMPT_TEMPLATES[style]
    prompt = template.replace("{content}", content)

    return {
        "ok": True,
        "style": style,
        "prompt": prompt,
        "char_count": len(prompt),
        "tip": "将上方 prompt 复制到任意 AI 对话框即可获得专业分析",
    }


@app.get("/prompt/templates")
async def get_prompt_templates():
    """获取所有提示词模板列表"""
    return {
        "templates": [
            {"key": "security", "name": "安全巡检分析", "desc": "入侵检测、风险评估"},
            {"key": "ops", "name": "运维状态分析", "desc": "资源使用、性能瓶颈"},
            {"key": "debug", "name": "故障排查", "desc": "错误分析、修复方案"},
            {"key": "summary", "name": "执行报告汇总", "desc": "命令记录整理成报告"},
        ]
    }


# ─── AI 对话接口（任务完善助手）────────────────────────────────────────────────

_CHAT_REFINE_SYSTEM = """你是一个 Linux 安全运维 AI Agent 的「任务描述优化助手」。
你的职责是：帮助用户把模糊的想法转化为精确、完整的 Agent 任务指令。

## 工作流程
1. 理解用户描述的目标（哪怕表达不清楚）
2. 如有关键信息缺失，提出 1-2 个最关键的问题（不要一次问太多）
3. 当信息足够时，生成一条完整的任务指令，格式：
   **✅ 推荐任务指令：**
   ```
   [完整的任务描述，可直接发送给 Agent 执行]
   ```
4. 同时附上简短说明：这条指令会让 Agent 做什么

## 风格
- 简洁直接，不废话
- 主动推断用户意图，不过度追问
- 推荐指令要尽量具体，包含工具路径、执行目标、检查重点
- 如用户直接确认，回复「好的，已发送给 Agent 执行」即可

## 常见工具路径参考
- 安全巡检脚本通常在 /root/check/ 目录
- whocheck、linuxcheckshoot 等是常见的巡检工具名
"""

_CHAT_FREE_SYSTEM = """你是一个专业的 Linux 安全运维专家，可以回答各种 Linux 系统、网络安全、运维相关的问题。
回答简洁专业，必要时提供命令示例。"""


@app.post("/chat")
async def chat_with_ai(request: ChatRequest):
    """
    AI 实时对话接口。
    mode=refine: 任务完善模式，帮用户把模糊想法变成精确任务指令
    mode=free:   自由问答模式
    """
    from openai import OpenAI

    system_prompt = _CHAT_REFINE_SYSTEM if request.mode == "refine" else _CHAT_FREE_SYSTEM

    messages = [{"role": "system", "content": system_prompt}]
    # 加入历史对话
    for turn in (request.history or []):
        role = turn.get("role", "user")
        content = turn.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    # 加入当前消息
    messages.append({"role": "user", "content": request.message})

    try:
        cfg = load_model_config()
        client = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])
        resp = client.chat.completions.create(
            model=cfg["model"],
            messages=messages,
            temperature=0.7,
            max_tokens=1024,
        )
        reply = resp.choices[0].message.content.strip()
        return {"ok": True, "reply": reply}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 对话失败: {str(e)}")


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """流式 AI 对话接口（SSE）"""
    from openai import OpenAI

    system_prompt = _CHAT_REFINE_SYSTEM if request.mode == "refine" else _CHAT_FREE_SYSTEM

    messages = [{"role": "system", "content": system_prompt}]
    for turn in (request.history or []):
        role = turn.get("role", "user")
        content = turn.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": request.message})

    async def event_gen():
        try:
            cfg = load_model_config()
            client = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])
            stream = client.chat.completions.create(
                model=cfg["model"],
                messages=messages,
                temperature=0.7,
                max_tokens=1024,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    payload = json.dumps({"token": delta.content}, ensure_ascii=False)
                    yield f"data: {payload}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─── 工具知识库接口 ───────────────────────────────────────────────────────────

@app.get("/tool-knowledge")
async def get_tool_knowledge():
    """获取全部工具知识记录"""
    items = tool_knowledge.list_all()
    return {"ok": True, "total": len(items), "items": items}


@app.get("/tool-knowledge/{tool_name}")
async def get_one_tool_knowledge(tool_name: str):
    """获取指定工具的知识记录"""
    rec = tool_knowledge.get(tool_name)
    if not rec:
        raise HTTPException(status_code=404, detail=f"工具 {tool_name} 暂无知识记录")
    return {"ok": True, "tool": tool_name, **rec}


@app.post("/tool-knowledge")
async def update_tool_knowledge(request: ToolKnowledgeUpdateRequest):
    """
    手动更新/补充工具知识（用于人工纠正或预先录入）
    """
    tool_name = request.tool_name.strip()
    if not tool_name:
        raise HTTPException(status_code=400, detail="tool_name 不能为空")

    if request.usage_hint or request.help_text:
        tool_knowledge.update_usage(tool_name, request.usage_hint or "", request.help_text or "")

    if request.failed_command:
        tool_knowledge.record_error(
            tool_name=tool_name,
            failed_command=request.failed_command,
            error_output=request.error_output or "",
            fixed_command=request.fixed_command or "",
        )

    return {"ok": True, "message": f"工具 {tool_name} 知识已更新"}


@app.delete("/tool-knowledge/{tool_name}")
async def delete_tool_knowledge(tool_name: str):
    """删除指定工具的知识记录"""
    ok = tool_knowledge.delete(tool_name)
    if not ok:
        raise HTTPException(status_code=404, detail=f"工具 {tool_name} 不存在")
    return {"ok": True, "message": f"已删除工具 {tool_name} 的知识记录"}


# ─── 工具自学接口 ─────────────────────────────────────────────────────────────

@app.post("/tool-knowledge/learn")
async def learn_tool(request: ToolLearnRequest):
    """
    触发 AI 自主学习一个工具（流式 SSE）。
    AI 会自己跑 -h、试参数、读源码注释，把用法彻底搞清楚，存入知识库。

    前端使用 EventSource 或 fetch+ReadableStream 接收流式进度。
    """
    tool_name = request.tool_name.strip()
    tool_path = request.tool_path.strip()

    if not tool_name or not tool_path:
        raise HTTPException(status_code=400, detail="tool_name 和 tool_path 不能为空")

    async def event_gen():
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def run_learn():
            try:
                for event in tool_knowledge.stream_learn(tool_name, tool_path):
                    loop.call_soon_threadsafe(queue.put_nowait, event)
            except Exception as e:
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    {"event": "error", "message": str(e)},
                )
            loop.call_soon_threadsafe(queue.put_nowait, None)

        loop.run_in_executor(None, run_learn)

        while True:
            event = await queue.get()
            if event is None:
                break
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/tool-knowledge/learn/{tool_name}/status")
async def get_learn_status(tool_name: str):
    """查询某工具自学任务的当前状态"""
    task = tool_knowledge.get_learn_task(tool_name)
    if not task:
        # 检查知识库里是否已有记录（之前学过）
        rec = tool_knowledge.get(tool_name)
        if rec and rec.get("source") == "ai_explore":
            return {
                "ok": True,
                "status": "done",
                "learned_at": rec.get("learned_at"),
                "message": "该工具已完成 AI 自学",
                "usage_hints": rec.get("usage_hints", []),
            }
        raise HTTPException(status_code=404, detail=f"工具 {tool_name} 没有进行中或已完成的自学任务")
    return {"ok": True, **task.to_dict()}


# ─── 启动入口 ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"""
╔══════════════════════════════════════════╗
║       AI Linux Agent  v1.0.0             ║
║  http://127.0.0.1:{API_PORT}                    ║
║  接口文档: http://127.0.0.1:{API_PORT}/docs    ║
╚══════════════════════════════════════════╝
    """)
    uvicorn.run(
        "api:app",
        host=API_HOST,
        port=API_PORT,
        reload=False,
        log_level=LOG_LEVEL.lower(),
    )
