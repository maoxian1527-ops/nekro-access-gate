# 排错手册

本插件踩过的坑，按"最容易遇到"排序。

---

## 1. 插件"加载成功"但完全不生效（最常见）

**现象**：日志里有

```
插件加载成功: "使用授权门禁" by "xxx"
```

但消息照旧被 AI 回答，`/na-*` 也没反应。

**原因**：NekroAgent 的插件启用状态不在插件代码里，而在配置的 `PLUGIN_ENABLED` 名单里：

```python
# nekro_agent/services/plugin/collector.py
if plugin.key not in config.PLUGIN_ENABLED:
    plugin._is_enabled = False      # 加载成功但处于"禁用"状态
```

**修法**：编辑 `configs/nekro-agent.yaml`，在 `PLUGIN_ENABLED` 里加上 `<author>.<module_name>`：

```yaml
PLUGIN_ENABLED:
  - maoxian1527-ops.access_gate
```

然后 `docker restart nekro_agent`。

**怎么确认已启用**：访问 `/plugins/<author>.access_gate/status`，能返回 JSON 就说明生效了
（插件被禁用时路由不会挂载，会返回 404）。

---

## 2. `/wl-on` 没反应，AI 却回了一句"没看懂"

**现象**：发 `/wl-list`，机器人用 AI 口吻回答，而不是插件返回清单。

**原因**：NekroAgent 会把 `/` 开头的消息**优先交给它自己的命令系统**：

```python
# nekro_agent/adapters/interface/collector.py
if content_text and await _try_handle_command(...):
    return                      # 命令被消费，插件钩子收不到
if not db_chat_channel.is_active:
    return
```

所以纯钩子（`mount_on_user_message`）**收不到** `/` 开头的消息。

**修法（本插件已内置）**：用 `mount_command` 把 `/na-*` 注册成**原生指令**。
如果你自己写插件，也要注意这一点；或者让用户发**不带斜杠**的形式（`wl-list`）。

**排查**：日志里搜 `Command Detect`，如果出现但没有执行结果，说明命令名没注册上。

---

## 3. 白名单文件写坏 → 插件不加载 / 白名单重置

**现象**：插件加载失败（`配置文件格式错误` 或 YAML 解析异常），或白名单突然变空。

**原因**：
- 长字符串（例如手动粘进去的 Cookie）被 YAML 折行写成多行，后续用正则替换只改了第一行，
  留下缩进的"续行"，把整份配置弄坏；
- JSON 结尾多了逗号、少了引号。

**修法**：
- 编辑配置优先用 WebUI，不要手写 YAML；
- 用容器里的 PyYAML 校验：`docker exec -i <容器> /app/.venv/bin/python -c "import yaml;yaml.safe_load(open('<路径>'))"`；
- 白名单是 JSON，校验：`python3 -m json.tool whitelist.json`。

---

## 4. 目标 ID 认错（群/个人搞混）

**现象**：`/wl-on 949384578` 把群号当成 QQ 号开通了。

**原因**：群号和 QQ 号都是纯数字，无法自动区分。

**修法（本插件已内置约定）**：群必须写 `群949384578`，纯数字一律按个人处理。
指令里如果写错，插件会提示「群请写成 群949384578」。

---

## 5. 到期/续费相关

开源版本**不包含到期功能**（作者在私有部署里自行扩展）。
如果你需要到期，可以：

- 在白名单条目里自己加字段，然后在 `mount_on_user_message` 里做时间判断；
- 或者用外部定时任务（cron）定期改写 `whitelist.json` / 调用 `/wl-off`。

---

## 6. 需要临时关闭门禁

- 插件管理里停用「使用授权门禁」；
- 如果还改过 `SESSION_*_ACTIVE_DEFAULT: false`，注意核心层仍然默认禁用新会话。
---

## 7. 插件指令没反应，但官方指令却能执行（命名冲突）

**现象**：发 `/wl-on` 有效，发 `/na-on` 却表现为"开启/关闭会话"，而不是授权。

**原因**：NekroAgent 自带一组 `na_*` 命令：

```
built_in/switch.py : na_on / na_off / na_observe     ← 会话启停
built_in/info.py   : na_help / na_info
```

插件的命令如果**同名**，会被内置命令抢先（或互相覆盖），表现就是"指令执行了，但不是你要的那个"。

**修法**：给插件命令取一个不冲突的前缀。本插件用 `wl-`（whitelist）：
`wl-on`、`wl-off`、`wl-list`、`wl-check`、`wl-plugin-only`、`wl-mode`、`wl-help`。

**经验**：注册命令前先看看 `nekro_agent/services/command/built_in/` 里有哪些名字。

---

## 8. `/help` 没有帮助

NekroAgent 没有 `/help`，官方的是 **`/na_help`**。发 `/help` 会当成普通聊天交给 AI。
本插件提供了 **`/wl-help`** 输出自己的指令表。
