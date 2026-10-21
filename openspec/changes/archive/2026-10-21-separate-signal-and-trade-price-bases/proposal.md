# Proposal

## Why

现有策略用后复权价格计算交易股数、资金占用和盈亏，信号价格与真实交易价格的尺度混在同一组持仓字段中。需要显式区分两种价格口径，使实际股数与原始收盘价匹配，同时保留后复权行情上的信号与止损规则。

## What Changes

- **BREAKING**：迁移 `Position` 字段为 `sig_entry`、`sig_stop`、`sig_atr`、可选 `sig_take`、`trade_qty`、`trade_entry_time`，保留 `side`，新增来自 `raw_close` 的 `trade_raw_close`；不保留旧字段别名。
- **BREAKING**：`calc_position_size` 同时接收信号入场价和原始价，将每股止损风险换算为 `sig_atr × stop_atr_multiple × trade_raw_close / sig_entry`，并以原始价限制资金占用；同步两个策略的开仓调用及旧策略的信号传递。
- 调仓的目标股数、资金占用和预算裁仓使用原始价格；ATR 倒数权重、信号排序及止损止盈判断继续使用复权尺度。
- 开仓及调仓同时记录同一时刻的两种入场价；股数不变时保留两种原入场价和原入场时间。
- 所有估值价格基准保存原始收盘价；权益及交易盈亏直接按原始价差计算，持仓快照按原始价乘真实股数计价。
- 同步中文函数文档与测试，覆盖不同复权尺度、原始价资金限制及两种价格相等时的旧基线。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `strategy-state-transitions`：修订持仓字段、风险数量换算、双价格入场信息保护、原始价估值与结果兼容性要求，明确后复权信号和真实交易金额的边界。

## Impact

涉及 `strategy_common.py`、`portfolio_accounting.py`、两个动量策略及 `tests/` 中的持仓构造、行情样例和相关断言。行情输入需要已有的 `raw_close` 列；`update_tushare.py` 已生成该列，不新增数据依赖。`Trade`、`PortfolioRow`、`EquityRow` 及 CSV 字段结构保持现状，但真实价格与复权价格不相等时，股数、金额及收益允许按新口径变化。

不调整信号公式、ATR 倒数权重、策略分支、调仓阈值及现有停牌处理；按已确认要求直接使用原始价差，不新增分红现金、份额调整或其他企业行动记账。
