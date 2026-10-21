"""使用授权门禁 (access-gate) —— 给 NekroAgent 的订阅制白名单插件。

解决的问题
----------
NekroAgent 默认「会话启用」，任何人拉一个群、加一次好友，机器人就会开始回答，
按量计费下 token 成本不可控。本插件把「能不能用」变成一个显式白名单：

* **默认拒绝**：不在白名单里的群 / 私聊，消息直接被拦下（`BLOCK_TRIGGER`），
  AI 完全不会被调用 —— 真正的零 token。
* **两种档位**：`完整`（可聊天、可用插件）与 `仅插件`（只能发视频链接 / 用指令，
  不能闲聊）。
* **管理员指令**：`/wl-on`、`/wl-off`、`/wl-list`、`/wl-check`、`/wl-plugin-only`、
  `/wl-mode`，在插件内处理，不进 AI。
* **零侵入**：不改 NekroAgent 代码，镜像升级不丢；和会话面板的「禁用」可以叠加使用。

写作约定（建议）
----------------
* 群：``/wl-on 群123456789``（群号前写「群」）
* 个人：``/wl-on 123456789``（直接写 QQ 号）

数据存放
--------
白名单是插件目录下的 ``whitelist.json``（可用配置项 ``whitelist_path`` 覆盖）。
每次消息都会重新读取，改完立即生效，不需要重启。

License: PolyForm Noncommercial 1.0.0（禁止商业用途）
"""

import json
import time
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional, Tuple

from fastapi import APIRouter
from pydantic import Field

from nekro_agent.api.plugin import ConfigBase, NekroPlugin
from nekro_agent.api.schemas import AgentCtx
from nekro_agent.api.signal import MsgSignal
from nekro_agent.services.command.base import CommandPermission
from nekro_agent.services.command.ctl import CmdCtl
from nekro_agent.services.command.schemas import Arg, CommandExecutionContext, CommandResponse

plugin = NekroPlugin(
    name="使用授权门禁",
    module_name="access_gate",
    description=(
        "订阅制门禁：按群/按人维护白名单，未授权的消息直接拦下、不触发 AI（不消耗 token）。"
        "支持「仅插件」档位与管理员 /na-* 指令。"
    ),
    version="0.1.0",
    author="maoxian1527-ops",
    url="https://github.com/maoxian1527-ops/nekro-access-gate",
    support_adapter=["onebot_v11"],
    allow_sleep=False,
)


@plugin.mount_config()
class AccessGateConfig(ConfigBase):
    """白名单门禁设置。"""

    admins: str = Field(
        default="",
        title="管理员 QQ（逗号分隔）",
        description=(
            "必填！只有这些 QQ 号可以发送 /na-* 管理指令，并且他们自己永远不受限。"
            "例如：123456789 或 123456789,987654321"
        ),
    )
    deny_reply: bool = Field(
        default=False,
        title="未授权时回复提示",
        description=(
            "关闭（默认）= 完全沉默；开启 = 给未授权的会话回一句提示，"
            "按下面的冷却时间限频，避免刷屏。"
        ),
    )
    deny_text: str = Field(
        default="本服务为订阅制，如需使用请联系管理员开通喵。",
        title="未授权提示文案",
        description="deny_reply 开启时发送的内容。",
    )
    plugin_only_text: str = Field(
        default="本会话为「仅插件」权限：可以用插件和指令，闲聊请先开通完整权限喵。",
        title="仅插件模式的提示文案",
        description="会话被设为仅插件模式时，普通聊天会收到这句提示（同一冷却时间内只提示一次）。",
    )
    reply_cooldown_minutes: int = Field(
        default=60,
        ge=1,
        le=1440,
        title="提示冷却（分钟）",
        description="同一个会话在这个时间窗口内最多收到一次提示。",
    )
    whitelist_path: str = Field(
        default="",
        title="白名单文件路径（可选）",
        description=(
            "留空 = 使用插件目录下的 whitelist.json。"
            "想放别处（例如挂载到宿主机方便编辑）就填绝对路径。"
        ),
    )


# ---------------------------------------------------------------- 数据层

_DEFAULT_FILE = Path(__file__).resolve().parent / "whitelist.json"


def _whitelist_file() -> Path:
    custom = str(getattr(plugin.get_config(), "whitelist_path", "") or "").strip()
    return Path(custom) if custom else _DEFAULT_FILE


def _empty_data() -> Dict[str, Any]:
    return {"groups": {}, "users": {}, "admins": []}


def _load() -> Dict[str, Any]:
    path = _whitelist_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = _empty_data()
        _save(data)
        plugin.logger.info(f"白名单已初始化（空）：{path}")
        return data
    except json.JSONDecodeError as error:
        plugin.logger.error(f"白名单文件解析失败，已按空名单处理：{error}")
        return _empty_data()

    data.setdefault("groups", {})
    data.setdefault("users", {})
    data.setdefault("admins", [])
    return data


def _save(data: Dict[str, Any]) -> None:
    path = _whitelist_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------- 上下文工具


def _chat_ident(ctx: AgentCtx) -> Tuple[str, str]:
    """返回 ("group", 群号) 或 ("private", QQ号)。"""
    channel_id = str(getattr(ctx, "channel_id", "") or "")
    channel_type = str(getattr(ctx, "channel_type", "") or "")
    if channel_id.startswith("group_"):
        return "group", channel_id[len("group_"):]
    if channel_id.startswith("private_"):
        return "private", channel_id[len("private_"):]
    chat_key = str(getattr(ctx, "chat_key", "") or "")
    for prefix, kind in (("-group_", "group"), ("-private_", "private")):
        if prefix in chat_key:
            return kind, chat_key.split(prefix, 1)[1]
    return (channel_type or "unknown", channel_id)


def _sender_qq(ctx: AgentCtx) -> str:
    user = getattr(ctx, "db_user", None)
    for attr in ("platform_userid", "user_id", "username"):
        value = getattr(user, attr, None)
        if value:
            return str(value)
    return ""


def _admin_set(cfg: AccessGateConfig, data: Dict[str, Any]) -> set:
    raw = f"{cfg.admins or ''}," + ",".join(str(x) for x in data.get("admins") or [])
    return {item.strip() for item in raw.split(",") if item.strip()}


def _is_admin(sender: str, kind: str, target: str, admins: set) -> bool:
    """判断发送者是不是管理员。

    私聊场景最可靠：会话对象（private_<QQ>）就是发送者本人，直接用 channel_id 判断，
    不依赖 message / db_user 里能否取到 QQ。
    """
    if sender and sender in admins:
        return True
    return kind == "private" and target in admins


# ---------------------------------------------------------------- 指令解析

_MODE_FULL = "full"
_MODE_PLUGIN = "plugin"

_COMMAND_NAMES = ("wl-on", "wl-off", "wl-list", "wl-check", "wl-plugin-only", "wl-mode", "wl-help")

_USAGE = """用法（群号前写「群」，个人直接写 QQ 号）：
【群】/wl-on 群123456789          ← 开通这个群
      /wl-off 群123456789         ← 停掉这个群
      /wl-plugin-only 群123456789 ← 只能用插件/指令，不能闲聊
      /wl-mode 群123456789 full   ← 改回完整权限
      /wl-check 群123456789       ← 查询
【个人】/wl-on 123456789          ← 开通这个人
      /wl-off 123456789
      /wl-plugin-only 123456789
      /wl-mode 123456789 full
      /wl-check 123456789
【通用】/wl-list                  ← 列出全部"""


def _command_name(text: str) -> str:
    head = text.split()[0] if text.split() else ""
    return head[1:].lower() if head.startswith("/") else head.lower()


def _is_command(text: str) -> bool:
    return _command_name(text) in _COMMAND_NAMES


def _resolve_target(rest: List[str]) -> Tuple[str, List[str]]:
    """解析目标类型与 ID。

    约定：``群12345`` / ``群 12345`` = 群；纯数字 = 个人；``人12345`` 也认。
    """
    if not rest:
        return "private", []
    first = rest[0]
    if first in ("群", "人"):
        return ("group" if first == "群" else "private"), rest[1:]
    if first.startswith("群") and first[1:].isdigit():
        return "group", [first[1:]] + rest[1:]
    if first.startswith("人") and first[1:].isdigit():
        return "private", [first[1:]] + rest[1:]
    return "private", rest


def _format_entry(kind: str, target: str, entry: Dict[str, Any]) -> str:
    label = "群" if kind == "group" else "人"
    remark = entry.get("remark") or ""
    mode = "仅插件" if entry.get("mode") == _MODE_PLUGIN else "完整"
    parts = [f"{label} {target}", mode]
    if remark:
        parts.append(remark)
    return "｜".join(parts)


async def _set_channel_active(kind: str, target_id: str, active: bool) -> str:
    """把白名单动作同步到 NekroAgent 自带的会话启停（is_active）。"""
    try:
        from nekro_agent.models.db_chat_channel import DBChatChannel

        prefix = "group_" if kind == "group" else "private_"
        channel = await DBChatChannel.get_or_none(
            adapter_key="onebot_v11", channel_id=f"{prefix}{target_id}"
        )
        if not channel:
            return (
                "\n（提示：这个会话还没出现过。等它第一次发消息后会被创建，"
                "届时再执行一次本指令即可激活。）"
            )
        await channel.set_active(active)
        return "\n✅ 已同步会话状态：" + ("已激活" if active else "已禁用")
    except Exception as error:  # noqa: BLE001 - 同步失败不影响白名单本身
        plugin.logger.warning(f"同步会话启停失败 {kind}={target_id}: {error}")
        return f"\n⚠️ 会话启停同步失败：{error}"


async def _handle_command(data: Dict[str, Any], cfg: AccessGateConfig, text: str) -> str:
    parts = text.strip().split()
    action = parts[0].lower()
    rest = parts[1:]
    if action in ("/wl-help", "/帮助"):
        return _USAGE

    def bucket(kind: str) -> Dict[str, Any]:
        return data["groups"] if kind == "group" else data["users"]

    if action == "/wl-list":
        lines = ["📋 白名单"]
        for kind, label in (("group", "群"), ("private", "人")):
            items = bucket(kind)
            lines.append(f"— {label}（{len(items)} 个）—")
            for tid, entry in sorted(items.items()):
                lines.append("  ✅ " + _format_entry(kind, tid, entry or {}))
        return "\n".join(lines)[:1900]

    if not rest:
        return _USAGE

    kind, rest = _resolve_target(rest)
    target_id = rest[0] if rest else ""
    if not target_id:
        return _USAGE
    rest = rest[1:]
    if not target_id.isdigit():
        return f"❌ 目标必须是纯数字，收到：{target_id}（群请写成「群{target_id}」）"
    label = "群" if kind == "group" else "人"

    # ---- 开通 ----
    if action == "/wl-on":
        remark = " ".join(rest).strip() or bucket(kind).get(target_id, {}).get("remark", "")
        existing_mode = bucket(kind).get(target_id, {}).get("mode", _MODE_FULL)
        bucket(kind)[target_id] = {"remark": remark, "mode": existing_mode}
        note = await _set_channel_active(kind, target_id, True)
        return f"✅ 已授权 {_format_entry(kind, target_id, bucket(kind)[target_id])}{note}"

    # ---- 取消 ----
    if action == "/wl-off":
        if bucket(kind).pop(target_id, None) is None:
            return f"❌ {label} {target_id} 本来就不在白名单"
        note = await _set_channel_active(kind, target_id, False)
        return f"🗑 已取消授权：{label} {target_id}{note}"

    # ---- 仅插件 ----
    if action == "/wl-plugin-only":
        entry = bucket(kind).get(target_id)
        if not entry:
            return f"❌ {label} {target_id} 不在白名单，请先用 /wl-on 开通"
        entry["mode"] = _MODE_PLUGIN
        return (
            f"✅ 已设为「仅插件」：{_format_entry(kind, target_id, entry)}\n"
            "（只能用插件/指令，普通聊天不会触发 AI）"
        )

    # ---- 档位切换 ----
    if action == "/wl-mode":
        entry = bucket(kind).get(target_id)
        if not entry:
            return f"❌ {label} {target_id} 不在白名单，请先用 /wl-on 开通"
        arg = (rest[0].lower() if rest else "")
        if arg in ("plugin", "仅插件", "插件"):
            entry["mode"] = _MODE_PLUGIN
        elif arg in ("full", "完整", "聊天", "all"):
            entry["mode"] = _MODE_FULL
        else:
            return (
                f"当前：{_format_entry(kind, target_id, entry)}\n"
                "用法：/wl-mode <ID> plugin  ← 仅插件\n"
                "      /wl-mode <ID> full    ← 完整权限"
            )
        return f"✅ 已切换：{_format_entry(kind, target_id, entry)}"

    # ---- 查询 ----
    if action == "/wl-check":
        entry = bucket(kind).get(target_id)
        if not entry:
            return f"❌ {label} {target_id} 不在白名单"
        return f"✅ 在白名单：{_format_entry(kind, target_id, entry)}"

    return _USAGE


# ---------------------------------------------------------------- 消息钩子

_REPLY_AT: Dict[str, float] = {}


async def _reply_once(ctx: AgentCtx, kind: str, target: str, cfg: AccessGateConfig, text: str) -> None:
    """按冷却时间给提示（同一会话每 reply_cooldown_minutes 分钟最多一次）。"""
    key = f"{kind}_{target}"
    now = time.time()
    if now - _REPLY_AT.get(key, 0) < max(60, cfg.reply_cooldown_minutes * 60):
        return
    _REPLY_AT[key] = now
    try:
        await ctx.send_text(text)
    except Exception as error:  # noqa: BLE001
        plugin.logger.warning(f"发送提示失败: {error}")


@plugin.mount_on_user_message()
async def access_gate(ctx: AgentCtx, _message: Any = None) -> Optional[MsgSignal]:
    """未授权 / 仅插件会话的普通消息一律 BLOCK_TRIGGER（不触发 AI）。"""
    try:
        if str(getattr(ctx, "adapter_key", "")) != "onebot_v11":
            return None

        cfg = plugin.get_config()
        data = _load()
        admins = _admin_set(cfg, data)
        if not admins:
            plugin.logger.warning("未配置管理员 QQ（插件配置里的 admins），门禁将拒绝所有会话")

        kind, target = _chat_ident(ctx)
        sender = _sender_qq(ctx)
        text = str(getattr(_message, "content", "") or "").strip()
        admin = _is_admin(sender, kind, target, admins)

        # 1) 管理员指令（不进 AI）
        if _is_command(text):
            if admin:
                try:
                    reply = await _handle_command(data, cfg, text)
                    _save(data)
                except Exception as error:  # noqa: BLE001
                    plugin.logger.exception(f"门禁指令执行失败: {error}")
                    reply = f"⚠️ 指令执行失败：{error}"
                await ctx.send_text(reply)
            return MsgSignal.BLOCK_TRIGGER

        # 2) 管理员本人永远放行
        if admin:
            return None

        # 3) 白名单判定
        entry = (data["groups"] if kind == "group" else data["users"]).get(target)
        if entry:
            if entry.get("mode") == _MODE_PLUGIN:
                # 仅插件：带链接的消息放行（交给视频等插件），其它一律拦下
                if "http" in text.lower():
                    return None
                plugin.logger.info(f"仅插件会话拦截闲聊: {kind}={target}")
                if cfg.deny_reply:
                    await _reply_once(ctx, kind, target, cfg, cfg.plugin_only_text)
                return MsgSignal.BLOCK_TRIGGER
            return None

        # 4) 未授权：拦下（可选提示）
        plugin.logger.warning(f"拦截未授权 {kind}={target} sender={sender or '?'}")
        if cfg.deny_reply:
            await _reply_once(ctx, kind, target, cfg, cfg.deny_text)
        return MsgSignal.BLOCK_TRIGGER
    except Exception as error:  # noqa: BLE001 - 门禁自身异常时不要拦住所有人
        plugin.logger.exception(f"门禁检查异常，本次放行: {error}")
        return None


# ---------------------------------------------------------------- 原生指令（/na-*）
# 说明：NekroAgent 会把 "/xxx" 开头的消息优先当它自己的指令处理，插件钩子收不到；
# 所以用 mount_command 注册成真正的指令，才能响应 /wl-on、/wl-list 等。


def _cmd_is_admin(context: "CommandExecutionContext") -> bool:
    try:
        cfg = plugin.get_config()
        data = _load()
        return str(getattr(context, "user_id", "") or "") in _admin_set(cfg, data)
    except Exception:  # noqa: BLE001
        return False


async def _run_cmd(context: "CommandExecutionContext", text: str) -> "CommandResponse":
    if not _cmd_is_admin(context):
        return CmdCtl.failed("🚫 只有管理员可以使用这个指令喵。")
    try:
        cfg = plugin.get_config()
        data = _load()
        reply = await _handle_command(data, cfg, text)
        _save(data)
        return CmdCtl.success(reply)
    except Exception as error:  # noqa: BLE001
        plugin.logger.exception(f"指令执行失败 {text!r}: {error}")
        return CmdCtl.failed(f"⚠️ 执行失败：{error}")


@plugin.mount_command(
    name="wl-on",
    description="开通白名单并激活会话",
    permission=CommandPermission.PUBLIC,
    usage="/wl-on <群号或QQ号>（群请写 群123456）",
    category="授权管理",
)
async def na_on_command(
    context: "CommandExecutionContext",
    target: Annotated[str, Arg("群号（群123456）或 QQ 号", positional=True)],
) -> "CommandResponse":
    return await _run_cmd(context, f"/wl-on {target}")


@plugin.mount_command(
    name="wl-off",
    description="取消白名单授权并禁用会话",
    permission=CommandPermission.PUBLIC,
    usage="/wl-off <群号或QQ号>",
    category="授权管理",
)
async def na_off_command(
    context: "CommandExecutionContext",
    target: Annotated[str, Arg("群号（群123456）或 QQ 号", positional=True)],
) -> "CommandResponse":
    return await _run_cmd(context, f"/wl-off {target}")


@plugin.mount_command(
    name="wl-plugin-only",
    description="设为仅插件模式：可用插件与指令，但不能闲聊",
    permission=CommandPermission.PUBLIC,
    usage="/wl-plugin-only <群号或QQ号>",
    category="授权管理",
)
async def na_plugin_only_command(
    context: "CommandExecutionContext",
    target: Annotated[str, Arg("群号（群123456）或 QQ 号", positional=True)],
) -> "CommandResponse":
    return await _run_cmd(context, f"/wl-plugin-only {target}")


@plugin.mount_command(
    name="wl-mode",
    description="切换会话档位：plugin=仅插件 / full=完整权限",
    permission=CommandPermission.PUBLIC,
    usage="/wl-mode <群号或QQ号> <plugin|full>",
    category="授权管理",
)
async def na_mode_command(
    context: "CommandExecutionContext",
    target: Annotated[str, Arg("群号（群123456）或 QQ 号", positional=True)],
    mode: Annotated[str, Arg("plugin 或 full", positional=True)] = "plugin",
) -> "CommandResponse":
    return await _run_cmd(context, f"/wl-mode {target} {mode}")


@plugin.mount_command(
    name="wl-check",
    description="查询某个群/人的授权状态",
    permission=CommandPermission.PUBLIC,
    usage="/wl-check <群号或QQ号>",
    category="授权管理",
)
async def na_check_command(
    context: "CommandExecutionContext",
    target: Annotated[str, Arg("群号（群123456）或 QQ 号", positional=True)],
) -> "CommandResponse":
    return await _run_cmd(context, f"/wl-check {target}")


@plugin.mount_command(
    name="wl-list",
    description="列出全部白名单",
    permission=CommandPermission.PUBLIC,
    usage="/wl-list",
    category="授权管理",
)
async def na_list_command(context: "CommandExecutionContext") -> "CommandResponse":
    return await _run_cmd(context, "/wl-list")


# ---------------------------------------------------------------- 自检接口


@plugin.mount_router()
def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/status")
    async def gate_status():
        cfg = plugin.get_config()
        data = _load()
        return {
            "groups": len(data.get("groups") or {}),
            "users": len(data.get("users") or {}),
            "admins": sorted(_admin_set(cfg, data)),
            "whitelist_file": str(_whitelist_file()),
            "deny_reply": cfg.deny_reply,
            "commands": list(_COMMAND_NAMES),
        }

    return router

@plugin.mount_command(
    name="wl-help",
    description="显示白名单门禁的全部指令用法",
    permission=CommandPermission.PUBLIC,
    usage="/wl-help",
    category="授权管理",
)
async def wl_help_command(context: "CommandExecutionContext") -> "CommandResponse":
    return await _run_cmd(context, "/wl-help")
