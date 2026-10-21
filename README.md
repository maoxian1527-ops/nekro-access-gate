# nekro-access-gate

> 给 [NekroAgent](https://github.com/KroMiose/nekro-agent) 的**订阅制白名单门禁**插件：
> 不在白名单里的群 / 私聊，消息直接被拦下 —— **AI 根本不启动，一个 token 都不花**。

[English](README.en.md) · 中文

---

## 为什么需要它

NekroAgent 的会话**默认是启用的**（`db_chat_channel.py` 里 `is_active` 默认 `True`）：
任何人拉一个群、加一次好友，机器人就立刻开始回答。按量计费时这笔钱很难控。

官方没有"白名单 / 订阅"功能，本插件补的正是这个缺口：

- **默认拒绝**：不在白名单 → `BLOCK_TRIGGER`（插件层直接掐断，不进模型）
- **两种档位**：`完整`（可聊天 + 用插件）/ `仅插件`（只能发视频链接、用指令，不能闲聊）
- **管理员指令**：`/wl-on`、`/wl-off`、`/wl-list`、`/wl-check`、`/wl-plugin-only`、`/wl-mode`
- **零侵入**：不改 NekroAgent 代码，镜像升级不丢；可以和会话面板的「禁用」叠加

## 效果对比

| 场景 | 没有本插件 | 装了本插件 |
|---|---|---|
| 陌生人拉个群 @ 机器人 | 直接开聊，开始烧 token | 一句话都不回（白名单外） |
| 你自己配置的付费群 | 能聊 | 能聊 ✅ |
| 只想用视频转发的群 | 能聊（浪费 token） | 设为「仅插件」：能发视频链接，聊天被拦 |
| 成本 | 不可控 | 只有白名单内的会话会调用模型 |

## 安装

1. 把 `plugin/` 目录复制到 NekroAgent 的插件工作目录，目录名建议 `access_gate`：

   ```bash
   <你的 nekro-agent>/data/plugins/workdir/access_gate/
   ├── __init__.py
   └── plugin.py
   ```

2. **把它加入已启用列表**（这一步很容易漏，漏了插件会"加载成功但不生效"）：

   编辑 `configs/nekro-agent.yaml`，在 `PLUGIN_ENABLED` 里加上插件的 key：

   ```yaml
   PLUGIN_ENABLED:
     - local_video.video_forward
     - maoxian1527-ops.access_gate     # ← 新插件必须在这里
   ```

   > key 的格式是 `<author>.<module_name>`。本插件的 `module_name` 是 `access_gate`，
   > `author` 是你在 `plugin.py` 里填的 `author`。

3. 重启容器：

   ```bash
   docker restart nekro_agent
   ```

4. 打开 WebUI → **插件管理** → 「使用授权门禁」→ **配置**，把 **管理员 QQ** 填上（必填）。

5. 自检：

   ```bash
   curl -s http://127.0.0.1:8022/plugins/maoxian1527-ops.access_gate/status
   # {"groups":0,"users":0,"admins":["123456789"],"deny_reply":false,...}
   ```

## 指令

> **写作约定**：群号前写「群」（`群949384578`），个人直接写 QQ 号（`1289606085`）。
> 带不带斜杠都认（`/wl-on 群123` = `wl-on 群123`）。

### 群

| 指令 | 作用 |
|---|---|
| `/wl-on 群123456789` | 开通这个群（并激活会话） |
| `/wl-off 群123456789` | 取消授权（并禁用会话） |
| `/wl-plugin-only 群123456789` | 设为「仅插件」：能用插件，不能闲聊 |
| `/wl-mode 群123456789 full` | 改回完整权限 |
| `/wl-check 群123456789` | 查询状态 |

### 个人

| 指令 | 作用 |
|---|---|
| `/wl-on 123456789` | 开通这个人 |
| `/wl-off 123456789` | 取消授权 |
| `/wl-plugin-only 123456789` | 设为「仅插件」 |
| `/wl-mode 123456789 full` | 改回完整权限 |
| `/wl-check 123456789` | 查询状态 |

### 通用

| 指令 | 作用 |
|---|---|
| `/wl-list` | 列出全部白名单 |

## 两种档位

| 档位 | 能做什么 | 不能做什么 |
|---|---|---|
| **完整** | 正常聊天、所有插件、所有指令 | — |
| **仅插件** | 发视频链接（交给视频插件）、所有指令类插件（导出表情等） | **跟 AI 闲聊**（直接拦下，0 token） |

> 为什么「仅插件」真的不花钱：指令类功能在插件之前就被处理掉了，视频链接由对应插件
> 直接处理，只有"纯聊天"才会走到 AI —— 而那一步被门禁拦住了。

## 配置项

| 配置 | 默认 | 说明 |
|---|---|---|
| `admins` | 空（**必填**） | 管理员 QQ，逗号分隔。只有他们能发 `/na-*`，且自己永远不受限 |
| `deny_reply` | `false` | 未授权会话是否回一句提示 |
| `deny_text` | 见配置示例 | 未授权的提示文案 |
| `plugin_only_text` | 见配置示例 | 仅插件模式下闲聊的提示文案 |
| `reply_cooldown_minutes` | `60` | 同一会话提示的最短间隔 |
| `whitelist_path` | 空 | 白名单文件位置，留空 = 插件目录下的 `whitelist.json` |

## 白名单数据

默认落在插件目录的 `whitelist.json`，结构如下（**每次消息都会重新读取，改完立即生效**）：

```json
{
  "groups": {
    "949384578": { "remark": "付费群 A", "mode": "full" }
  },
  "users": {
    "1289606085": { "remark": "个人月付", "mode": "plugin" }
  },
  "admins": []
}
```

## 建议同时打开「默认禁用」

本插件是**应用层**拦截。想在**核心层**再加一道保险，可以改两个配置项：

```yaml
# configs/nekro-agent.yaml
SESSION_GROUP_ACTIVE_DEFAULT: false
SESSION_PRIVATE_ACTIVE_DEFAULT: false
```

这样新会话创建时就是禁用状态（连插件都不会被调用），双保险。
**注意**：改完需要重启容器，且已有的会话不受影响（它们各自的 `is_active` 保持不变）。

## 常见坑

见 [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)。最常见的三个：

1. **插件加载成功但不生效** → 没加进 `PLUGIN_ENABLED`
2. **`/wl-on` 没反应，AI 却回话了** → NekroAgent 把 `/` 开头的消息当自己的指令吃掉了
3. **白名单文件写坏导致插件不加载** → YAML/JSON 折行、多行字符串

## 许可

**PolyForm Noncommercial 1.0.0** —— 免费使用、修改、分发，**禁止任何商业用途**。

## 相关项目

- [nekro-media-forward](https://github.com/maoxian1527-ops/nekro-media-forward)：抖音 / 小红书 / TikTok / B站 视频自动合并转发（和本插件是绝配：白名单负责"谁能用"，它负责"怎么用"）
