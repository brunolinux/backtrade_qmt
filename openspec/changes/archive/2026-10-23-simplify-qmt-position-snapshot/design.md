# Design

## Context

动机见 `proposal.md`。当前 `_snapshot()` 在读取 `POSITION` 记录时过滤非目标 ETF 代码，验证 `m_nVolume` 与 `m_nCanUseVolume`，然后以 `holdings.get(code, Holding(0, 0))` 为基础累加。`tests/test_qmt_passorder.py` 中的重复记录测试明确锁定了叠加行为，`qmt_passorder.md` 也写着合并同一代码。

前一变更 `implement-qmt-timed-target-rebalancing` 已完成实施但未归档；其设计文档记录旧的叠加决定，主规格中尚不存在 QMT 执行能力。本变更以单独的快照约束能力记录用户新确认的不变量，避免误将未归档能力当成已有主规格修改。

## Goals / Non-Goals

**Goals:**
- 让一个受支持 ETF 代码只对应一个实际持仓记录；异常重复时阻止整次调仓。
- 保持正常单条记录、无记录、非法数量和非目标品种的现有处理。
- 用短注释明确三个 `namedtuple` 的字段含义和数量单位。

**Non-Goals:**
- 不推断重复记录的来源，也不对不同账户或股东账户分组。
- 不重写计划计算、定时调度、回调或买卖顺序。

## Decisions

### 1. 校验后直接赋值，重复则失败

保留 `_snapshot()` 当前代码范围过滤与数量校验。对于通过校验的受支持 ETF，先检查 `code in holdings`；已有记录时抛出带该代码的 `ValueError`，否则直接设置 `holdings[code] = Holding(total, usable)`。用现有 `after_init()` 的异常边界统一打印原因、保持 `ready=False`，不注册定时器。相比简单覆盖，显式失败能暴露违背用户确认的不变量，也不会因记录顺序改变交易计划。

### 2. 用现有模拟环境验证外部结果

把当前“重复记录相加”的测试改为“重复记录导致初始化失败”，检查错误包含代码、无定时器、无委托；用单条记录及多个不同代码的测试验证正常计划仍由原始持仓数生成。现有非法数量、无持仓买入、卖出约束及全量模拟测试继续保留。

### 3. 注释描述语义，不扩大数据模型保证

在 `Holding`、`Snapshot`、`PlannedOrder` 定义旁添加短注释：`Holding.total/available` 是实际/可卖份数；`Snapshot.balance/available/market_value` 是总资产/可用资金/持仓市值，`holdings` 是代码到 `Holding` 的映射；`PlannedOrder.code/operation/quantity` 是代码、买卖操作号和委托份数。`Snapshot` 含有可变字典，因此不称整个对象为不可变。

## Risks / Trade-offs

- 客户端如果意外返回同代码多条记录 → 策略停止当日调仓并报告代码；用户需核对账户数据，避免在不清楚含义时重复或不足下单。
- 前一变更的历史设计描述叠加 → 以本变更新约束作为后续实现依据；归档时保留各自范围，不回写历史设计。

## Migration Plan

1. 在 `qmt_passorder.py` 改造快照构建并补字段注释，更新模拟测试和 `qmt_passorder.md`。
2. 运行定向测试、现有全量测试及 OpenSpec 严格校验；不连接真实客户端。
3. 后续归档先处理未归档的前一变更，再归档本变更，使主规格的历史顺序清晰。
