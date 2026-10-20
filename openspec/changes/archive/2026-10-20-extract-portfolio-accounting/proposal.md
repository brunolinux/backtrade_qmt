# Proposal

## Why

两个动量策略共享的行情读取、指标、仓位管理及交易记录逻辑集中在旧策略文件中，导致 v2 依赖旧策略；首轮提取记账模块后，`_read_close` 又重复了 `getv` 的读取逻辑。将记账与状态推进分离，并将策略公共部分提取到独立文件，可明确职责、消除重复读取实现和策略间的直接依赖。

## What Changes

- 新增根目录模块 `portfolio_accounting.py`，提供无副作用的盯市权益计算、估值基准更新和统一收盘结算入口。
- v2 直接从通用模块导入收盘结算入口，保留先盯市、再执行策略和调仓的现有顺序。
- `strategy_momentum.py` 保留原 `update_equity_close` 导入路径、参数和返回值，通过委托复用通用实现。
- 新增 `strategy_common.py`，提取两个策略共享的行情读取、指标、数量计算、仓位管理及交易记录函数，并承载公共 `Trade` 类型；两个策略直接导入公共实现，保留旧公开名称的导入兼容性。
- `portfolio_accounting.py` 删除 `_read_close`，改用 `strategy_common.getv` 构造当日价格快照，保持先计算权益、再更新基准的顺序。
- 保持现有价格列、缺行情处理、缺失基准回退、开仓基准初始化及输出结构，增加针对副作用与数值兼容性的验证。
- 各策略保留自己的预处理、信号、选股、保留仓位及回测编排，不增加费用、分红或现金账本模型；不恢复用户已删除的 `momentum_util.py` 和 `momentum_v3.py`。

## Capabilities

### New Capabilities

无。本次为保持业务行为的内部重构，变更元数据设置 `skip_specs: true`。

### Modified Capabilities

无。验收约束记录在设计及任务中，不创建 delta spec。

## Impact

- 计划新增 `portfolio_accounting.py` 与 `tests/test_portfolio_accounting.py`。
- 首轮记账提取已经完成；后续计划新增 `strategy_common.py` 与 `tests/test_strategy_common.py`，调整两个策略的公共函数定义、导入和兼容出口，以及记账模块的价格读取依赖。
- 回测入口、选股及仓位算法、CSV 结构和现有外部调用签名保持兼容，不新增第三方依赖。
- 工作区已有 `strategy_momentum.py` 修改及交易记录测试，实施时需保留并运行相关回归检查。
