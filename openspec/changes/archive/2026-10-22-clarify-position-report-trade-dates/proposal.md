# Proposal

## Why

现有仓位清单使用日期标签和逐行头寸，不便直接复制到策略配置中，也没有同时显示模拟总资产。需要将日期、目标仓位及总资产输出为 Python 赋值片段，并附现金和总市值供人工核对。

## What Changes

- **BREAKING**：输出前两行改为 `SIGNAL_DATE = dt.date(年, 月, 日)` 与 `TRADE_DATE = dt.date(年, 月, 日)`，分别取工作簿最新仓位源日期及其下一交易日，月日不补零。
- **BREAKING**：正仓位改为多行 `TARGET_QUANTITIES = { ... }` 字典，代码用双引号、四个空格缩进、整数数量及每项末尾逗号，保留原列顺序；无正仓位时保留空的多行字典。
- 字典后依次打印 `TOTAL_VALUE = 金额`、`现金: 金额`、`总市值: 金额`。总资产与现金均取 `portfolio_value` 的同一源日期；`TOTAL_VALUE` 和“总市值”使用相同的 `total_value`，该金额包含现金，所有金额固定两位小数。
- 不输出 `import datetime as dt`、代码围栏或额外说明；读取总资产失败时沿用完整摘要失败规则。
- 同步具名状态、读取及格式化函数文档、测试和 README 样例。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `portfolio-value-export`：调整控制台摘要的日期赋值、目标仓位字典和现金标签，增加同日模拟总资产输出及其失败规则。

## Impact

涉及 `print_latest_positions.py`、`tests/test_latest_positions.py` 和 README。需要从已经读取的市值表增加同日 `total_value` 的提取、校验及状态传递，无需新增日历请求、工作簿列或第三方依赖。旧 ISO 日期、中文日期标签及 `cash:` 文本的消费者需要适配新格式。
