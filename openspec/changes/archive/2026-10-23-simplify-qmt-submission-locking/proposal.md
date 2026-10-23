# Proposal

## Why

`qmt_passorder.py` 曾在委托登记和回调查询时额外获取 `state.lock`，容易让人误以为锁在等待异步委托完成。该简化已经按讨论写入工作区，需要把边界、行为不变的依据及验证要求记录为独立变更。

## What Changes

- 委托提交时直接登记一次性委托标识，回调直接按标识查询；移除围绕 `attempts` 的额外加锁。
- 保留 `refresh` 对并发或重入定时调用的防护，以及卖出、买入阶段的仅一次标志。
- 保留先登记后调用 `passorder`、单笔失败继续和回调只报告结果的行为；用现有测试验证。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

无。委托提交次数、执行时序和回报过滤规则不变，因此设置 `skip_specs: true`。

## Impact

涉及 `qmt_passorder.py` 的 `_submit` 与 `_callback_order` 状态访问，以及 `tests/test_qmt_passorder.py` 中已有的定时器重入、同步回调和不重试测试。无新增依赖或对外接口变更，不触发真实委托。
