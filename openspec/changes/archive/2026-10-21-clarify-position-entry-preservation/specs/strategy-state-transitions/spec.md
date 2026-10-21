# Spec Delta

## MODIFIED Requirements

### Requirement: 计算接口命名明确返回式行为

系统 SHALL 以计算、构造、筛选、调仓或保留语义命名本次迁移的接口，移除旧的原地修改入口，不同时提供 `_inplace` 变体。公共入场信息修正接口 SHALL 命名为 `preserve_entries_for_unchanged_quantities`，接收候选持仓和当前持仓并返回修正后的新映射；旧名称 `normalize_positions` SHALL 不再提供。接口文档 SHALL 说明返回值和输入保护约定，已有纯盯市权益计算的名称及语义 SHALL 保持不变。

#### Scenario: 调用者显式接收状态

- **WHEN** 调用者通过新的估值、止损和入场修正接口处理输入
- **THEN** 调用者通过返回值取得下一状态，无需依赖函数对输入的隐式写入

#### Scenario: 入场信息修正接口使用明确名称

- **WHEN** 调用者以 `candidate_positions` 和 `current_positions` 调用 `preserve_entries_for_unchanged_quantities`，且同一标的的新旧股数相同、入场时间不同
- **THEN** 返回独立持仓映射，沿用当前持仓的入场价与时间，其他候选字段及两个输入保持不变；旧名称 `normalize_positions` 不可调用
