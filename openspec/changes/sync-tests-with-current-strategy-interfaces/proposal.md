# Proposal

## Why

当前测试仍调用已改名的策略辅助函数和已内联的价格基准构造函数，导致 75 项测试中出现 10 个错误，现有行为回归验证无法正常运行。需要让测试与当前接口一致，并继续覆盖原有关键行为。

## What Changes

- 将回测结果构造及每日持仓计算测试中的旧函数名更新为当前名称，并保留空表、具名记录、持仓计算和输入不变性断言。
- 将交易记录测试中的旧结果构造函数调用更新为当前名称。
- 将直接测试已删除的 `build_close_marks` 的用例改为通过 `calc_equity_close` 验证价格基准合并、旧键保留及输入不变性；移除关键字参数测试中对已删除函数的调用。
- 运行完整单元测试并确认没有因测试迁移而改变策略结果。仅修改测试，不恢复已删除接口或调整业务逻辑。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

无。本次仅同步测试与现有接口，不改变系统行为或规格要求，因此设置 `skip_specs: true`。

## Impact

涉及 `tests/test_momentum_v2_backtest_flow.py`、`tests/test_trade_records.py`、`tests/test_portfolio_accounting.py`、`tests/test_strategy_keywords.py`。不新增依赖，不修改生产代码及公开输出格式。
