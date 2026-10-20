# portfolio-value-export Specification

## Purpose

为回测资产价值导出提供每日组合总资产金额，使用户能够在保留各标的市值及现金明细的同时，直接读取完整组合价值序列，用于后续收益率计算、结果核对与分析。

## Requirements

### Requirement: 每日总资产金额

系统 SHALL 在每日资产价值表中追加 `total_value` 列，数值为当日全部标的市值与现金之和；该列表示金额。

#### Scenario: 同时持有标的与现金
- **WHEN** 当日两个标的市值分别为 1000 和 2000，现金为 500
- **THEN** 当日 `total_value` 为 3500

#### Scenario: 全现金持仓
- **WHEN** 当日所有标的市值为 0，现金为 185000
- **THEN** 当日 `total_value` 为 185000

### Requirement: 保存总资产列并保留现有数据

系统 SHALL 将 `total_value` 作为最后一列保存到 `data/output_v2/portfolio_value.csv`，保留原有标的列、现金列、日期索引及 GB2312 编码，不改变数量表输出。

#### Scenario: 导出每日资产价值
- **WHEN** 回测结果完成资产价值 CSV 导出
- **THEN** CSV 的最后一列名为 `total_value`，各日期值与资产价值表一致，原有明细列及日期索引保持不变

#### Scenario: 数量表保持原样
- **WHEN** 同次回测导出 `portfolio_qty.csv`
- **THEN** 数量表保持原有输出，不包含新增的 `total_value` 列
