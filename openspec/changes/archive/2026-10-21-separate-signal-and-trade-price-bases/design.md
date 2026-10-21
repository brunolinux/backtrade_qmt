# Design

## Context

动机和范围见 `proposal.md`，行为契约见 `specs/strategy-state-transitions/spec.md`。现有两个策略共用不可变 `Position` 和公共风险、调仓、交易及快照函数。`update_tushare._process_raw_data` 在复权前保存 `raw_close`，再以 `adj_factor` 乘 OHLC；数据加载保留全部列，策略预处理复制并排序去重行情，因此无需改变数据下载或加载流程。

当前数量和金额计算都使用 `close`；旧策略还将价格和 ATR 放入五元素信号元组后交给开仓函数，v2 在开仓函数中直接读行情。现有规格中的字段和无条件数值兼容要求需要随本次行为变更修订。工作区现有的 v2 注释调整需保留。

## Goals / Non-Goals

**Goals:** 建立两种价格各自明确的数据流，保持不可变输入和返回新状态的接口约定，并用不相等的价格样例证明数量和金额未混用复权尺度。

**Non-Goals:** 新增复权行情列名、调整信号算法或 ATR 权重算法、改造调仓控制流、增加价格缺失回退、增加企业行动记账或修改导出字段。

## Decisions

### 1. 持仓保留扁平不可变结构

继续使用 `NamedTuple`，字段按以下顺序声明；生产调用优先使用关键字构造：

| 字段 | 类型与角色 |
|---|---|
| `side` | int，保留方向 |
| `trade_entry_time` | Timestamp，对应交易入场时刻，替代 entry_time |
| `trade_qty` | int，带符号实际股数，替代 qty |
| `trade_raw_close` | float，同一入场/调仓时刻 raw_close，必填 |
| `sig_entry` | float，入场/调仓时复权 close |
| `sig_atr` | float，建仓时复权 ATR |
| `sig_stop` | float，复权止损价 |
| `sig_take` | float 或 None，复权止盈价，默认 None |

`trade_raw_close` 是交易成本基准，不是每日最新估值价；日常估值更新价格基准字典，不改写此入场字段。各状态函数仅读取字段并以 `_replace` 返回新记录。不保留旧字段、旧字典记录或旧构造参数别名。

相比引入两层嵌套持仓结构，前缀方案满足已确认命名，且能复用现有不可变记录的处理方式。`Trade.entry_time` 等报表字段继续保持原名，由新持仓字段映射而来。

### 2. 原始价格贯通两条开仓路径

v2 的 `calc_buy_pos` 从同一行情和时刻读取 `close`、`atr`、`raw_close`，分别用于信号字段、数量换算和原始价基准。

旧策略的信号元组在现有五个元素末尾追加原始收盘价，结构为 `(symbol, side, strength, sig_entry, sig_atr, trade_raw_close)`；生产信号及直接构造信号的测试一起迁移。信号强度和排序键位置保持原状。相比额外传入整份行情，这种方式保留现有信号到开仓的调用边界，且两种价格来自同一条候选行情。

两条路径都用 raw_close 初始化开仓返回的价格基准；预处理保留该列，不从 close 合成。数量计算的有效输入约定为有限正的信号价和原始价；此变更不扩展为全面行情校验。读值仍复用 getv 的重复索引及 NaN 行为，不引入复权价回退。

### 3. 风险距离先换算，再计算实际股数

`calc_position_size` 签名迁移为 `(equity, sig_atr, sig_entry, trade_raw_close, stop_atr_multiple, max_trade_risk_ratio)`，不保留旧 `atr_value`、`price` 关键字。公式为：

```text
price_scale = trade_raw_close / sig_entry
risk_per_share = sig_atr * stop_atr_multiple * price_scale
risk_amount = equity * max_trade_risk_ratio
shares = round_to_lot(risk_amount / risk_per_share, 100)
若 shares * trade_raw_close > equity:
    shares = round_to_lot(equity / trade_raw_close, 100)
```

保留每股风险非正时返回 0 的分支和现有交易单位取整函数。使用两种价的比率即可得到换算尺度，无需让公共数量函数依赖行情表或额外的 adj_factor 参数；仅替换资金上限分母无法同时纠正风险预算。

### 4. 调仓只转换金额和股数的尺度

总风险及权重继续按 `sig_atr` 倒数计算；不按原始 ATR 重新加权。`target_qty` 使用当日 raw_close，之后保留原阈值和零仓过滤逻辑。可交易候选记录同时写入当日 sig_entry、trade_raw_close 和 trade_entry_time；预算检查和裁仓分母使用该原始价格。停牌记录保持原值，并沿用其 trade_raw_close 计算既有资金占用。

调仓函数保留既有“先刷新候选入场信息”的行为，调用方随后通过 `preserve_entries_for_unchanged_quantities` 修正：股数相同且时间不同时，三个入场字段一起恢复旧值，信号止损、ATR、止盈等其他候选字段保留。相比在调仓过程中提前恢复成本基准，这样避免用历史入场价替代当日价参与资金检查。

### 5. 记账链路统一保存原始价格

- `calc_equity_close` 用 trade_qty 构造数量映射，从 raw_close 读取当日价格；prev_close、current_close、next_close 和策略内 close_marks 均为原始价。纯 `calc_mark_to_market_equity` 的字典入参及价差公式不变，文档明确这里传入原始价。
- `calc_trade_records` 对退出及切换仓位均使用 `旧 trade_qty × (当日 raw_close - 旧 trade_raw_close)`，保留全部旧股数的统计口径和跳过条件。导出的 entry_time 从 trade_entry_time 读取。
- `build_portfolio_snapshot` 使用 `trade_qty × 当日 raw_close` 计算市值，现金仍按权益扣减；沿用现有停牌行、未持有行及输出结构。

不对原始价差再次应用复权因子，也不新增分红现金或份额变更处理。信号止损和止盈始终读取 close 并比较 sig_ 字段，不能随金额计算一起批量替换成 raw_close。

### 6. 用两类行情验证迁移

所有测试的持仓构造、属性、替换和信号元组同步新结构；需要交易价格的旧合成行情显式提供 `raw_close=close`，以保留原数值基线。增加 raw_close 与 close 不同的样例，分别验证风险换算、资金上限、调仓权重、预算裁仓、双价格入场保护、原始价盯市、交易盈亏和快照。为两个回测入口覆盖从开仓到输出的不同价格样例，并保留重复调用及输入不变性断言。

## Risks / Trade-offs

- [只改目标股数而遗漏金额路径会再次混用尺度] → 开仓基准、调仓资金、盯市、交易和快照逐项验收，不相等价格测试覆盖每条路径。
- [旧字段替换误伤 Trade、行情列或导出字段] → 按对象迁移引用，保持输出结构断言及旧基线。
- [无条件照搬历史数值断言掩盖真实数量变化] → 仅将相等价格样例作为旧数值基线，双价格样例使用独立可手算预期值。
- [数据文件或外部调用未提供 raw_close/新字段] → 将输入及构造变更标为 BREAKING，更新函数文档和仓库调用；不静默回退或保留双接口。

## Migration Plan

先同步持仓结构、两个策略的信号和开仓数据传递以及测试构造，再分别完成风险数量、调仓入场信息、原始价记账的行为和对应测试。各阶段更新相应函数文档，最后运行完整单元测试，核对相等价格基线和双价格端到端结果。无需数据下载升级或报表迁移；新旧 Position 构造不能混用，回退需连同调用方整体恢复。
