# Proposal

## Why

回测导出的资产价值表只有各标的市值和现金，缺少可直接用于后续收益率分析的每日总资产金额。增加汇总列，便于保存和使用组合价值序列。

## What Changes

- 在 `backtest_etf_v2.py` 的 `portfolio_val` 中追加 `total_value` 列，表示当日所有标的市值与现金之和。
- 将新增列随现有 `data/output_v2/portfolio_value.csv` 一同导出。
- 保留原有标的、现金、日期索引及输出编码；本次不增加收益率列。

## Capabilities

### New Capabilities

- `portfolio-value-export`: 回测资产价值表导出每日组合总资产金额。

### Modified Capabilities

无。

## Impact

影响 `backtest_etf_v2.py` 的资产价值导出与 CSV 列结构，新增一列。无新增依赖，不改动策略、交易或数量表。用户提到的 `backtest_v2.py` 不存在，按项目实际入口 `backtest_etf_v2.py` 规划。
