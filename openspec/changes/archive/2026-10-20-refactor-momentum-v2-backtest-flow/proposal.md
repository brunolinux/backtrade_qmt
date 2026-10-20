# Proposal

## Why

第二版动量策略的 backtest 同时编排回测、执行每日持仓决策和构造结果表，局部变量也混用了不同持仓阶段及列表和 DataFrame 类型。按职责提取辅助函数并明确变量含义，可以降低阅读和修改流程时误解状态的风险。

## What Changes

- 保留 backtest 为流程入口，负责预处理、日期遍历、每日估值、权益历史及结果收集。
- 在 strategy_momentum_v2.py 内提取每日持仓决策和结果表构造两个私有辅助函数，继续复用已有公共计算和记账函数。
- 按意图区分当前、止损后、保留、新开及调仓后持仓，明确配置预算、价格基准、累计记录和最终结果表的局部名称。
- 保留入口签名、配置键、预处理历史范围、每日执行顺序、条件调仓、数值结果、输出结构及输入保护，不新增公开接口或兼容性破坏。
- 为新辅助函数提供中文 Google 风格文档和行为测试，调整依赖原函数体结构的 v2 结果表测试，继续验证真实表格和 CSV。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

无。本次为纯内部重构，继续遵守现有 strategy-state-transitions 及 portfolio-value-export 规范；不改变可观察业务行为，设置 `skip_specs: true`，不生成规范差异。

## Impact

- 生产变更限于 strategy_momentum_v2.py 的 backtest、两个私有辅助函数及相关文档。
- 测试涉及每日持仓决策、结果表、固定回测和输入保护；已有 tests/test_trade_records.py 对 backtest 函数体中 DataFrame 赋值语句的查找需要为 v2 改为调用结果构造函数。
- 不修改旧策略、公共模型与计算、组合记账、CSV 导出脚本或依赖。工作区已有 add-portfolio-total-value 的归档及主规范未提交改动，本次保留这些差异。
