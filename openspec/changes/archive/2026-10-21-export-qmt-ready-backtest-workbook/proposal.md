# Proposal

## Why

当前回测脚本输出三份 CSV，标的代码缺少 QMT 交易所后缀，数量表混入现金，资金结果直接使用浮点计算且没有统一到分。需要生成可直接查看和用于 QMT 数据准备的 Excel 工作簿，并在代码层明确数量与金额精度。

## What Changes

- **BREAKING**：用 `data/output_v2/backtest_results.xlsx` 替代脚本的三份 CSV 输出，工作表为 `trade`、`portfolio_value` 和 `portfolio_qty`；不再生成旧 CSV。
- **BREAKING**：导出标的列名和交易代码统一为 QMT 的 `代码.交易所` 格式，当前 ETF 范围使用 `.SZ`、`.SH`。`portfolio_qty` 删除现金列，标的数量为整数且必须为 100 的倍数。
- 市值表继续保留 `cash` 和最后一列 `total_value`；交易表将名称与代码区分为 `name` 和 `symbol`，消除当前重复的 symbol 表头。
- 权益、市值、现金、交易盈亏和报表金额在代码中统一按分四舍五入，Excel 金额显示两位小数、数量显示整数；不只依赖单元格格式。
- 原始行情价格、复权价格、ATR、信号、风险换算和权重等中间计算保留精度，不将每份价格截为两位小数。
- 拆出可独立调用的报表构造与写入逻辑；声明 Excel 引擎依赖，更新依赖锁文件、中文函数文档与相关测试。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `portfolio-value-export`：将导出契约迁移为单个 Excel 工作簿，定义 QMT 代码、无现金的整手数量表、金额格式及总资产一致性。
- `strategy-state-transitions`：明确资金结果按分记账、原始价与信号保持精度，以及货币精度与既有回测输出兼容性的边界。

## Impact

涉及 `backtest_etf_v2.py`、公共记账与持仓金额计算、两个策略的资金结果、`pyproject.toml`、`uv.lock` 及导出/记账测试。计划新增独立的报表模块和无策略依赖的金额辅助模块，避免公共策略与记账之间的循环依赖。

依赖旧 CSV 路径、裸代码列名或数量表 cash 列的下游需要迁移；回测仍返回原有三张 DataFrame，Excel 不新增权益曲线工作表。此次不计算手续费，不扩展股票、期货等市场的代码推断，不修改 QMT 实盘下单脚本，不删除已有历史 CSV 文件。
