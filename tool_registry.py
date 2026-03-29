"""
MCP 风格工具注册中心。

当前阶段先在项目内实现“结构化能力注册 + 统一执行”，
后续如果要接标准 MCP Server，只需要把这里的能力描述映射出去即可。
"""
import json
import logging
import os
import re
import time
from copy import deepcopy
from typing import Any, Dict, List, Optional

from executor import executor

logger = logging.getLogger(__name__)

REGISTRY_FILE = "tool_registry.json"


def _slugify(value: str) -> str:
    """将文本转成适合作为能力名的标识符。"""
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9_]+", "_", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("_")


class ToolRegistry:
    """维护工具与能力定义，并提供统一执行入口。"""

    def __init__(self):
        self.registry: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        try:
            with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                self.registry = json.load(f)
            logger.info(f"[ToolRegistry] 已加载 {len(self.registry)} 个工具注册信息")
        except FileNotFoundError:
            self.registry = {}
        except Exception as e:
            logger.warning(f"[ToolRegistry] 加载失败: {e}")
            self.registry = {}

    def _save(self):
        try:
            temp_file = f"{REGISTRY_FILE}.tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.registry, f, ensure_ascii=False, indent=2)
            os.replace(temp_file, REGISTRY_FILE)
        except Exception as e:
            logger.error(f"[ToolRegistry] 保存失败: {e}")

    def list_all(self) -> List[Dict[str, Any]]:
        """返回所有工具及其能力。"""
        items = []
        for tool_name, rec in self.registry.items():
            copied = deepcopy(rec)
            copied["tool"] = tool_name
            items.append(copied)
        return items

    def get_tool(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """获取指定工具的注册信息。"""
        rec = self.registry.get((tool_name or "").strip().lower())
        return deepcopy(rec) if rec else None

    def export_all(self) -> Dict[str, Any]:
        """导出整个注册表。"""
        return {
            "version": 1,
            "exported_at": time.time(),
            "tools": self.list_all(),
        }

    def export_tool(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """导出单个工具定义。"""
        rec = self.get_tool(tool_name)
        if not rec:
            return None
        return {
            "version": 1,
            "exported_at": time.time(),
            "tool": (tool_name or "").strip().lower(),
            **rec,
        }

    def delete_tool(self, tool_name: str) -> bool:
        """删除指定工具的注册能力。"""
        normalized_name = (tool_name or "").strip().lower()
        if not normalized_name or normalized_name not in self.registry:
            return False
        del self.registry[normalized_name]
        self._save()
        logger.info(f"[ToolRegistry] 已删除工具: {normalized_name}")
        return True

    def get_capability(self, capability_name: str) -> Optional[Dict[str, Any]]:
        """按能力名查找能力定义。"""
        target = (capability_name or "").strip().lower()
        if not target:
            return None

        for tool_name, rec in self.registry.items():
            for cap in rec.get("capabilities", []):
                if (cap.get("name") or "").strip().lower() == target:
                    result = deepcopy(cap)
                    result["tool"] = tool_name
                    result["tool_path"] = rec.get("tool_path", "")
                    result["summary"] = rec.get("summary", "")
                    return result
        return None

    def register_tool(
        self,
        tool_name: str,
        tool_path: str,
        summary: str,
        capabilities: List[Dict[str, Any]],
        source: str = "manual",
    ) -> Dict[str, Any]:
        """注册或更新一个工具的能力集合。"""
        normalized_name = (tool_name or "").strip().lower()
        if not normalized_name:
            raise ValueError("tool_name 不能为空")

        rec = self.registry.setdefault(normalized_name, {
            "tool_path": "",
            "summary": "",
            "source": source,
            "updated_at": 0,
            "capabilities": [],
        })

        if tool_path:
            rec["tool_path"] = tool_path
        if summary:
            rec["summary"] = summary[:1000]
        rec["source"] = source
        rec["updated_at"] = time.time()
        rec["capabilities"] = self._normalize_capabilities(
            normalized_name,
            rec.get("tool_path", ""),
            capabilities,
        )
        self._save()

        logger.info(
            f"[ToolRegistry] 已注册工具: {normalized_name} ({len(rec['capabilities'])} 个能力)"
        )
        copied = deepcopy(rec)
        copied["tool"] = normalized_name
        return copied

    def import_data(self, data: Dict[str, Any], mode: str = "merge") -> Dict[str, Any]:
        """导入单个工具定义或整份注册表。"""
        if not isinstance(data, dict):
            return {"success": False, "message": "导入数据必须是对象"}

        # 兼容已经包装成 {"mode":"merge","data":{...}} 的文件。
        if "data" in data and isinstance(data.get("data"), dict):
            inner_mode = (data.get("mode") or mode or "merge").strip().lower()
            return self.import_data(data["data"], mode=inner_mode)

        mode = (mode or "merge").strip().lower()
        if mode not in ("merge", "replace"):
            return {"success": False, "message": "mode 仅支持 merge 或 replace"}

        if "tools" in data and isinstance(data.get("tools"), list):
            tools = data["tools"]
        else:
            tools = [data]

        imported_count = 0
        skipped_count = 0

        if mode == "replace":
            self.registry = {}

        for item in tools:
            if not isinstance(item, dict):
                skipped_count += 1
                continue

            tool_name = (item.get("tool") or "").strip().lower()
            capabilities = item.get("capabilities")
            if not tool_name or not isinstance(capabilities, list):
                skipped_count += 1
                continue

            try:
                self.register_tool(
                    tool_name=tool_name,
                    tool_path=(item.get("tool_path") or "").strip(),
                    summary=(item.get("summary") or "").strip(),
                    capabilities=capabilities,
                    source=(item.get("source") or "imported").strip() or "imported",
                )
                imported_count += 1
            except Exception as e:
                logger.warning(f"[ToolRegistry] 导入失败: {tool_name} | {e}")
                skipped_count += 1

        return {
            "success": imported_count > 0,
            "imported_count": imported_count,
            "skipped_count": skipped_count,
            "message": f"导入完成: 成功 {imported_count} 个，跳过 {skipped_count} 个",
        }

    def sync_from_knowledge_record(self, tool_name: str, knowledge_record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """根据知识库记录自动生成能力定义。"""
        if not tool_name or not knowledge_record:
            return None

        tool_path = (knowledge_record.get("tool_path") or "").strip()
        summary = (knowledge_record.get("summary") or knowledge_record.get("help_summary") or "").strip()
        usage_hints = knowledge_record.get("usage_hints", []) or []

        capabilities = self._suggest_capabilities(tool_name, tool_path, summary, usage_hints)
        if not capabilities:
            return None

        return self.register_tool(
            tool_name=tool_name,
            tool_path=tool_path,
            summary=summary or f"{tool_name} 的结构化工具能力",
            capabilities=capabilities,
            source="knowledge_sync",
        )

    def _normalize_capabilities(
        self,
        tool_name: str,
        tool_path: str,
        capabilities: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """规范化能力定义，补全默认字段。"""
        normalized = []
        for raw in capabilities:
            name = _slugify(raw.get("name") or "")
            if not name:
                continue

            args_schema = raw.get("args_schema") or {
                "type": "object",
                "properties": {},
                "required": [],
            }
            if args_schema.get("type") != "object":
                args_schema["type"] = "object"

            normalized.append({
                "name": name,
                "description": (raw.get("description") or "").strip(),
                "command_template": raw.get("command_template", ""),
                "args_schema": args_schema,
                "risk_level": raw.get("risk_level", "medium"),
                "tags": raw.get("tags", []),
                "tool": tool_name,
                "tool_path": tool_path,
            })
        return normalized

    def _suggest_capabilities(
        self,
        tool_name: str,
        tool_path: str,
        summary: str,
        usage_hints: List[str],
    ) -> List[Dict[str, Any]]:
        """按工具类型生成能力模板。"""
        name = (tool_name or "").strip().lower()
        if name == "nmap":
            return self._build_nmap_capabilities()
        return self._build_generic_capabilities(name, tool_path, summary, usage_hints)

    def _build_nmap_capabilities(self) -> List[Dict[str, Any]]:
        """为 nmap 构建一组高频、稳定的能力。"""
        return [
            {
                "name": "nmap_quick_scan",
                "description": "快速扫描目标常见开放端口，适合初步摸排。",
                "command_template": "\"{tool_path}\" -Pn -T4 -F {target}",
                "args_schema": {
                    "type": "object",
                    "properties": {
                        "target": {"type": "string", "description": "目标域名或 IP"},
                    },
                    "required": ["target"],
                },
                "risk_level": "medium",
                "tags": ["network", "recon", "quick"],
            },
            {
                "name": "nmap_service_scan",
                "description": "识别目标端口上的服务与版本信息。",
                "command_template": "\"{tool_path}\" -Pn -sV {target}",
                "args_schema": {
                    "type": "object",
                    "properties": {
                        "target": {"type": "string", "description": "目标域名或 IP"},
                    },
                    "required": ["target"],
                },
                "risk_level": "medium",
                "tags": ["network", "service", "fingerprint"],
            },
            {
                "name": "nmap_web_scan",
                "description": "针对网站常见 Web 端口进行快速扫描并识别服务。",
                "command_template": "\"{tool_path}\" -Pn -T4 -p 80,443,8080,8443 -sV {target}",
                "args_schema": {
                    "type": "object",
                    "properties": {
                        "target": {"type": "string", "description": "目标网站域名或 IP"},
                    },
                    "required": ["target"],
                },
                "risk_level": "medium",
                "tags": ["web", "network", "quick"],
            },
            {
                "name": "nmap_analyze_result",
                "description": "对扫描结果做结构化总结，提取开放端口、服务和后续建议。",
                "command_template": "",
                "args_schema": {
                    "type": "object",
                    "properties": {
                        "raw_output": {"type": "string", "description": "nmap 原始输出内容"},
                    },
                    "required": ["raw_output"],
                },
                "risk_level": "low",
                "tags": ["analysis", "report"],
            },
        ]

    def _build_generic_capabilities(
        self,
        tool_name: str,
        tool_path: str,
        summary: str,
        usage_hints: List[str],
    ) -> List[Dict[str, Any]]:
        """为非 nmap 工具生成保守能力。"""
        capabilities: List[Dict[str, Any]] = []
        if tool_path:
            capabilities.append({
                "name": f"{tool_name}_help",
                "description": f"查看 {tool_name} 帮助信息，确认可用参数。",
                "command_template": "\"{tool_path}\" -h",
                "args_schema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
                "risk_level": "low",
                "tags": ["help", "generic"],
            })

        for hint in usage_hints[:3]:
            capability = self._capability_from_usage_hint(tool_name, hint)
            if capability:
                capabilities.append(capability)

        return capabilities

    def _capability_from_usage_hint(self, tool_name: str, usage_hint: str) -> Optional[Dict[str, Any]]:
        """从“命令 - 作用”格式中提取能力。"""
        hint = (usage_hint or "").strip()
        if not hint:
            return None

        parts = re.split(r"\s+-\s+", hint, maxsplit=1)
        command_text = parts[0].strip()
        description = parts[1].strip() if len(parts) > 1 else f"{tool_name} 的常用能力"

        if command_text.startswith(tool_name):
            command_template = command_text.replace(tool_name, "{tool_path}", 1)
        elif "{tool_path}" in command_text:
            command_template = command_text
        else:
            return None

        cap_name = _slugify(f"{tool_name}_{description[:24]}")
        if not cap_name:
            return None

        return {
            "name": cap_name,
            "description": description,
            "command_template": command_template,
            "args_schema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
            "risk_level": "medium",
            "tags": ["generic", "learned"],
        }

    def build_mcp_prompt(self, tool_names: List[str] = None) -> str:
        """构建提供给 Agent 的 MCP 风格工具提示。"""
        if not self.registry:
            return ""

        targets: Dict[str, Dict[str, Any]] = {}
        if tool_names:
            for name in tool_names:
                lowered = (name or "").strip().lower()
                for tool_name, rec in self.registry.items():
                    if tool_name == lowered or tool_name in lowered or lowered in tool_name:
                        targets[tool_name] = rec
        else:
            targets = self.registry

        if not targets:
            return ""

        lines = [
            "\n## 【MCP 风格工具能力】",
            "以下能力已经结构化注册。遇到对应场景时，优先使用 tool=mcp_tool，而不是自己手写完整命令。",
            "调用格式示例：",
            '{"tool":"mcp_tool","mcp_tool":"nmap_web_scan","arguments":{"target":"example.com"},"continue":true}',
        ]

        for tool_name, rec in targets.items():
            lines.append(f"\n### 工具: {tool_name}")
            if rec.get("tool_path"):
                lines.append(f"路径: {rec['tool_path']}")
            if rec.get("summary"):
                lines.append(f"摘要: {rec['summary']}")
            for cap in rec.get("capabilities", []):
                required = cap.get("args_schema", {}).get("required", [])
                arg_text = ", ".join(required) if required else "无必填参数"
                lines.append(
                    f"- {cap.get('name')}: {cap.get('description')} | 必填参数: {arg_text}"
                )
        lines.append("")
        return "\n".join(lines)

    def execute_capability(self, capability_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """执行一个结构化能力。"""
        capability = self.get_capability(capability_name)
        if not capability:
            return {
                "success": False,
                "capability": capability_name,
                "output": f"未找到已注册能力: {capability_name}",
            }

        arguments = arguments or {}
        missing = []
        required_fields = capability.get("args_schema", {}).get("required", [])
        for field in required_fields:
            value = arguments.get(field)
            if value is None or (isinstance(value, str) and not value.strip()):
                missing.append(field)

        if missing:
            return {
                "success": False,
                "capability": capability_name,
                "output": f"缺少必填参数: {', '.join(missing)}",
            }

        if capability_name == "nmap_analyze_result":
            return {
                "success": True,
                "capability": capability_name,
                "command": "(analysis only)",
                "output": self._analyze_nmap_output(arguments.get("raw_output", "")),
            }

        command_template = capability.get("command_template", "")
        if not command_template:
            return {
                "success": False,
                "capability": capability_name,
                "output": f"能力 {capability_name} 没有可执行命令模板",
            }

        render_values = {"tool_path": capability.get("tool_path") or capability.get("tool") or ""}
        for key, value in arguments.items():
            render_values[key] = self._stringify_argument(value)

        try:
            command = command_template.format(**render_values)
        except KeyError as e:
            return {
                "success": False,
                "capability": capability_name,
                "output": f"命令模板缺少参数: {e}",
            }

        result = executor.run(command)
        return {
            "success": result.success,
            "capability": capability_name,
            "command": command,
            "output": result.output,
        }

    def _stringify_argument(self, value: Any) -> str:
        """把参数转成命令模板可用的文本。"""
        if isinstance(value, list):
            return ",".join(str(item) for item in value)
        return str(value)

    def _analyze_nmap_output(self, raw_output: str) -> str:
        """对 nmap 输出做轻量结构化总结，便于 Agent 二次推理。"""
        text = (raw_output or "").strip()
        if not text:
            return "未提供 nmap 输出，无法分析。"

        ports = []
        for line in text.splitlines():
            if re.search(r"^\d+/(tcp|udp)\s+open", line.strip(), re.IGNORECASE):
                ports.append(line.strip())

        lines = ["nmap 结果摘要："]
        if ports:
            lines.append("发现开放端口：")
            for item in ports[:20]:
                lines.append(f"- {item}")
        else:
            lines.append("未识别到标准格式的开放端口行。")

        lowered = text.lower()
        if "http" in lowered:
            lines.append("检测到 Web 相关服务，建议继续做目录、指纹和 TLS 配置检查。")
        if "ssh" in lowered:
            lines.append("检测到 SSH 服务，建议核查版本、暴露范围和弱口令风险。")
        if "ssl" in lowered or "https" in lowered:
            lines.append("检测到 TLS/HTTPS 服务，建议补充证书和协议套件检查。")

        return "\n".join(lines)


tool_registry = ToolRegistry()
