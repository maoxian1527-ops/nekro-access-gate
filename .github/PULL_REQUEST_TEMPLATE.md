## 改了什么

<!-- 一句话说明 -->

## 怎么测的

<!-- 例如：在测试群发 /na-on 群xxx，然后让非白名单成员发言，确认没有 AI 回复 -->

## 检查清单

- [ ] `python3 -m py_compile plugin/plugin.py` 通过
- [ ] 没有提交真实 QQ 号 / 群号 / whitelist.json
- [ ] 拦截仍使用 `MsgSignal.BLOCK_TRIGGER`（不自己发提示刷屏）