# Proposal

## Why

`qmt_passorder.py` 的四处结构体字段注释已经乱码，难以判断持仓、账户快照和计划委托的数据含义。文件字节虽可按 GB2312 严格往返，编码声明、使用说明与测试仍写作 GBK，需要与要求的 GB2312 格式一致。

## What Changes

- 重写 `Holding`、`Snapshot`、`PlannedOrder` 附近四处乱码注释，准确说明字段含义；修正 `_snapshot` 中误称持仓会累加的文档字符串。
- 将脚本编码声明改为 `gb2312`，保证整个文件可严格按 GB2312 解码、编码及导入。
- 同步更新 `qmt_passorder.md` 的编码说明，以及脚本兼容性测试中的编码断言。
- 保持下单、去重、持仓快照和回调行为不变。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

无。仅修复源文件注释及其编码说明，不改变交易行为；设置 `skip_specs: true`。

## Impact

涉及 `qmt_passorder.py`、`qmt_passorder.md` 和 `tests/test_qmt_passorder.py`。不增加依赖，不触发真实委托。现有待归档的 QMT 调仓规格使用 GBK 这一兼容范围；实施时需验证 GB2312 文件仍可由 GBK 解码，并保留交易测试结果。
