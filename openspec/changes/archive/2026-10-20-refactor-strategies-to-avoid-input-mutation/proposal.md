# Proposal

## Why

策略预处理、止损、记账和交易记录函数会修改调用方传入的对象，使同一份行情或持仓难以安全复用；`update_` 命名也不能明确区分计算与状态推进。统一为不修改输入、显式返回新结果的接口，可以让回测编排清楚地接收状态，并便于验证重复计算及结果兼容性。

## What Changes

- 两个策略的 `preprocess` 返回独立的行情字典及处理后的 DataFrame，旧策略的 `calc_buy_pos` 使用非原地排序，两个 `backtest` 保持调用方行情和参数不变。
- **BREAKING**：`update_equity_close` 改为 `calc_equity_close`，返回 `(equity, next_close)`；`update_close_marks` 改为返回新价格基准的 `build_close_marks`。保留 `calc_mark_to_market_equity` 的名称及纯计算职责。
- **BREAKING**：`update_stop_price` 改为返回新持仓的 `calc_stop_positions`；其他 `update_` 入口分别改为 `rebalance_portfolio`、`select_retained_positions`、`build_portfolio_snapshot`。
- **BREAKING**：将 `update_trades` 拆为返回修正持仓的 `normalize_positions` 和只返回交易记录的 `calc_trade_records`，同步迁移两个策略及测试。
- 不保留原地修改兼容入口，不新增 `_inplace` 版本；保留原持仓规则、价格口径、盈亏计算、交易表及回测输出。

## Capabilities

### New Capabilities

- `strategy-state-transitions`：策略计算及状态转换不修改输入，显式返回下一状态，并保持现有回测数值和输出格式。

### Modified Capabilities

无。当前没有已发布的相关主规范。本次改变函数返回值和可观察的输入修改行为，创建 delta spec，不使用 `skip_specs`。

## Impact

- 实施涉及 `portfolio_accounting.py`、`strategy_common.py`、`strategy_momentum.py`、`strategy_momentum_v2.py` 及 `tests/` 中对应测试。
- `backtest_etf_v2.py` 调用的 `backtest` 签名、返回三张表及 CSV 格式保持不变；旧内部函数名称的外部调用者需迁移。
- 不新增依赖，不恢复已删除模块，不修改数据下载、QMT 接口和已归档变更。
- 当前工作区 `portfolio_accounting.py` 有文档调整，实施需保留用户修改。
