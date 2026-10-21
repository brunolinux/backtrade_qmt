# Proposal

## Why

`normalize_positions` 实际只在持仓数量未变且入场时间改变时恢复原入场信息，名称没有说明这一条件。v2 回测在筛选保留持仓后立即调用它，但筛选仅复用原记录，因此该调用没有效果，也增加了阅读每日决策流程的负担。

## What Changes

- **BREAKING**：将公共函数 `normalize_positions` 改名为 `preserve_entries_for_unchanged_quantities`，同步两个动量策略及测试中的调用；不保留旧名称别名。
- 移除 `strategy_momentum_v2.py` 在保留持仓筛选后的冗余调用；保留调仓后的入场信息修正。
- 确认入场信息、交易记录、权益曲线和回测输出与现有行为一致。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `strategy-state-transitions`：明确入场信息修正接口的名称，以及数量未变时保留原入场信息的调用约定。

## Impact

影响 `strategy_common.py`、`strategy_momentum.py`、`strategy_momentum_v2.py` 和直接调用公共函数的测试或外部代码。公共函数名称变化需要调用方同步迁移；位置参数顺序、关键字参数名、持仓结构和策略数值规则不变。工作区中与本提案无关的现有改动不纳入本变更。
