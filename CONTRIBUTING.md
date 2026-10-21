# 贡献指南

感谢你愿意改进这个插件。

## 开发环境

- Python 3.11 / 3.12（NekroAgent 2.x 要求）
- 一份可运行的 NekroAgent 实例（推荐 Docker）
- 改完把 `plugin/` 覆盖到 `data/plugins/workdir/access_gate/`，然后 `docker restart nekro_agent`

## 提交流程

1. Fork → 建分支（`feat/xxx`、`fix/xxx`）
2. 改代码，确认 `python3 -m py_compile plugin/plugin.py` 通过
3. 本地实测：至少验证 `/na-list`、`/na-on`、`/na-off` 三个指令与拦截逻辑
4. 开 PR，说明：改了什么、怎么测的、有没有副作用

## 代码约定

- 单文件插件，**不要引入第三方依赖**
- 白名单读写保持"每次消息重新读文件"，保证改完即时生效
- 拦截必须用 `MsgSignal.BLOCK_TRIGGER`（不要自己发"已拦截"的消息，会刷屏）
- 任何异常都不能让消息卡死：外层捕获后放行或拦下，要在日志里写清楚

## 不要提交

- 真实的 QQ 号 / 群号 / 管理员号 / 任何凭据
- 自己的 `whitelist.json`
- 个人服务器路径

CI 会在 PR 上做语法检查与个人信息扫描，命中会直接失败。