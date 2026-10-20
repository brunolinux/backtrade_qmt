# Proposal

## Why

交易记录目前通过六字段普通元组创建，字段含义依赖位置和注释，维护时容易混淆。使用具名且带类型注解的记录，可以明确字段含义，同时保留现有元组使用方式与回测输出。

## What Changes

- 定义 `Trade(NamedTuple)`，字段顺序为 `symbol`、`side`、`entry_time`、`exit_time`、`pnl`、`exit_reason`。
- 将共享函数 `update_trades` 的平仓、切换仓位两个分支改为用关键字参数创建 `Trade`，补充相关返回类型注解。
- 保留持仓 `pos` 的字典结构及现有修改、复制语义。
- 保留交易生成条件、收益计算、原因文本、交易表列名与顺序，以及 CSV 导出行为。

## Capabilities

### New Capabilities

无。本次为内部数据结构重构，不新增对外能力。

### Modified Capabilities

无。不修改行为要求，在变更元数据中设置 `skip_specs: true`。

## Impact

- 主要实施位置为 `strategy_momentum.py`，它是 v2 导入的 `update_trades` 的定义位置；其自身的旧版回测也使用此函数。
- `strategy_momentum_v2.py` 和旧版回测中的交易 DataFrame，以及 `backtest_etf_v2.py` 的交易导出是兼容性验证对象。
- 使用标准库 `typing.NamedTuple`，无新增运行依赖，兼容项目 Python 3.10 及以上版本。
- 增加针对共享交易函数与交易表转换的本地验证，不涉及行情下载或实盘操作。
