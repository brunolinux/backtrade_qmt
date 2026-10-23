# Proposal

## Why

当前 `qmt_passorder.py` 将同一 ETF 代码的多条持仓记录相加，但用户已确认该账户的持仓快照遵循“一标的一条记录”。叠加逻辑增加理解成本，也可能掩盖异常的重复数据；直接建表并明确拒绝重复记录更符合已确认的数据约束。

## What Changes

- 初始化读取受支持 ETF 持仓时，每条有效记录直接生成对应代码的 `Holding`，不再累加既有记录。
- 若同一 ETF 代码再次出现，初始化明确报错，并且不启动定时器或提交委托；保留原有数量有效性校验和其他品种过滤规则。
- 更新模拟测试、`qmt_passorder.md`，并补充 `Holding`、`Snapshot`、`PlannedOrder` 的字段含义注释。
- 不调整目标仓位计算、委托数量规则、定时触发及回调行为。

## Capabilities

### New Capabilities

- `qmt-position-snapshot`: 规定 QMT 初始化持仓快照的单记录映射与重复代码拒绝行为。

### Modified Capabilities

无。QMT 执行能力仍在未归档的 `implement-qmt-timed-target-rebalancing` 变更中，尚不是主规格；本变更以独立的持仓快照能力记录新增的唯一性约束。

## Impact

- 预计修改 `qmt_passorder.py`、`tests/test_qmt_passorder.py`、`qmt_passorder.md`；不增加依赖，也不连接真实 QMT。
- 现有重复记录测试及说明将改为拒绝重复记录；单条持仓的买卖计划保持原行为。
- 前一变更的设计文档记录了当时的叠加决策，实施本变更时以本提案的新约束为准；保留该历史规划文件，不直接改动另一变更。
