# Proposal

## Why

`strategy_momentum_v2.backtest` 开头连续初始化七个状态和结果列表，目前缺少说明，读者难以迅速分清哪些值跨交易日传递、哪些值只为最终报表累计。补充简短注释可使估值和持仓决策的数据流更清楚。

## What Changes

- 在 `backtest` 的初始化区域按账户状态、估值价格基准、累计交易与权益历史、报表原始行分组添加中文注释。
- 注释说明 `equity` 在每轮估值前表示上次权益，`positions` 是上一轮决策后的持仓，`close_marks` 为下次盯市估值所用价格；说明权益历史参与杠杆计算，报表行在循环结束后转换为三张结果表。
- 仅调整注释，不修改变量名、计算顺序、回测输出或配置。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

无。本次属于代码注释完善，不改变规范级行为；变更元数据设置 `skip_specs: true`。

## Impact

仅涉及 `strategy_momentum_v2.py` 的 `backtest` 函数初始化区域。现有工作区有其他未提交改动，实施时应保留其内容。
