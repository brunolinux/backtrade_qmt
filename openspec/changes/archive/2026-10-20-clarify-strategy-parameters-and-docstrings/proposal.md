# Proposal

## Why

三个目标模块中的形参缩写、数据角色和单位不够明确，函数注释也缺少一致的参数及返回值说明。结合语义化形参名称和 Google 风格 docstring，可以让调用者从签名及文档理解正确用法，并减少对持仓角色、风险比例和候选范围的误解。

## What Changes

- 为 `strategy_common.py`、`portfolio_accounting.py` 和 `strategy_momentum_v2.py` 的全部 19 个自定义函数统一中文 Google 风格 docstring，补齐缺失的 `calc_quantity` 注释。
- **BREAKING**：按数据含义重命名形参及其局部引用，例如行情、持仓、时刻、每股价格、最小交易单位、风险比例、配置预算与候选扫描上限；对应关键字调用使用新名称，不保留旧关键字别名。
- 函数名称、参数顺序、默认值、返回结构及数值算法不变；保持现有输入保护约定、配置键、持仓字段和导出列名。
- 在文档中准确说明行情列、持仓所需字段、元组返回值、无行情处理、NaN 回退、候选扫描限制、交易记账口径和回测参数。
- 同步仓库内相关调用及测试；旧策略仅在调用公共函数需要时更新关键字调用，不扩大为旧策略全面重命名或注释重构。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `strategy-state-transitions`：增加语义明确的关键字参数调用及与签名一致的调用文档要求；保留已有状态转换、输入保护和回测兼容要求。

## Impact

- 目标文件中的 `portfolio_account.py` 按讨论指现存的 `portfolio_accounting.py`，不创建或重命名文件。
- 主要影响三个目标模块及 `tests/`；必要时迁移 `strategy_momentum.py`、`backtest_etf_v2.py` 中实际存在的关键字调用。
- 位置参数调用继续有效；使用旧形参名称的外部关键字调用者需迁移。`params` 内配置键和 `start_date` 名称保持不变。
- 不新增依赖或校验分支，不调整类型体系、Trade 字段、策略规则、输入保护方式或已归档变更。
