# nekro-access-gate

> A **subscription whitelist gate** plugin for [NekroAgent](https://github.com/KroMiose/nekro-agent):
> messages from groups / private chats that are not whitelisted are dropped before the AI is
> even started — **zero token cost**.

[中文](README.md) · English

---

## Why

NekroAgent creates chat channels **enabled by default** (`is_active` defaults to `True`),
so anyone who adds the bot to a group can immediately start consuming tokens.
There is no built-in whitelist / subscription feature — this plugin adds one:

- **Deny by default**: anything not in the whitelist gets `BLOCK_TRIGGER` (the model is never called)
- **Two tiers**: `full` (chat + plugins) and `plugin-only` (may send media links and use commands,
  but plain chatting is blocked)
- **Admin commands**: `/na-on`, `/na-off`, `/na-list`, `/na-check`, `/na-plugin-only`, `/na-mode`
- **No core patches**: survives image upgrades, and can be combined with the WebUI "disable channel" toggle

## Install

1. Copy `plugin/` into your NekroAgent plugin workdir as `access_gate`:

   ```bash
   <nekro-agent>/data/plugins/workdir/access_gate/
   ├── __init__.py
   └── plugin.py
   ```

2. **Add the plugin to `PLUGIN_ENABLED`** (easy to miss — otherwise it loads but stays disabled):

   ```yaml
   # configs/nekro-agent.yaml
   PLUGIN_ENABLED:
     - maoxian1527-ops.access_gate     # <author>.<module_name>
   ```

3. `docker restart nekro_agent`

4. In the WebUI → Plugins → **使用授权门禁** → config → fill in **admins** (required).

5. Verify:

   ```bash
   curl -s http://127.0.0.1:8022/plugins/maoxian1527-ops.access_gate/status
   ```

## Commands

Groups are prefixed with `群`, individuals are bare QQ numbers. A leading `/` is optional.

| Command | Meaning |
|---|---|
| `/na-on 群123456789` | Authorize a group (and activate the channel) |
| `/na-on 123456789` | Authorize a private user |
| `/na-off <target>` | Revoke (and disable the channel) |
| `/na-plugin-only <target>` | Plugin-only tier: plugins/commands allowed, chatting blocked |
| `/na-mode <target> full` | Back to full access |
| `/na-check <target>` | Show status of one target |
| `/na-list` | List the whole whitelist |

## Tiers

| Tier | Allowed | Blocked |
|---|---|---|
| `full` | Chat, all plugins, all commands | — |
| `plugin-only` | Media links (handled by other plugins), command-based plugins | **AI chatting** (no token spent) |

## Config

| Key | Default | Description |
|---|---|---|
| `admins` | empty (**required**) | Comma-separated admin QQ numbers |
| `deny_reply` | `false` | Reply with a hint when unauthorized |
| `deny_text` | — | Hint text for unauthorized chats |
| `plugin_only_text` | — | Hint text when chatting in plugin-only mode |
| `reply_cooldown_minutes` | `60` | Minimum interval between hints |
| `whitelist_path` | empty | Whitelist file location (default: `whitelist.json` next to the plugin) |

## Whitelist file

```json
{
  "groups": { "949384578": { "remark": "paid group", "mode": "full" } },
  "users":  { "1289606085": { "remark": "monthly user", "mode": "plugin" } },
  "admins": []
}
```

Re-read on every message — edit it and it takes effect immediately.

## Extra safety: default-disabled channels

```yaml
# configs/nekro-agent.yaml
SESSION_GROUP_ACTIVE_DEFAULT: false
SESSION_PRIVATE_ACTIVE_DEFAULT: false
```

New channels are then created **disabled**, so even the plugin is not invoked. Requires a restart;
existing channels keep their current state.

## Troubleshooting

See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) — the three most common pitfalls.

## License

**PolyForm Noncommercial 1.0.0** — free to use, modify and share, **commercial use prohibited**.
