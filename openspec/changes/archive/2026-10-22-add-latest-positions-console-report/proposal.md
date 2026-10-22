# Proposal

## Why

现有工作簿记录了每日目标仓位和现金，但手动查找最新日期、剔除零持仓并确定下一交易日不便于复制使用。需要一个独立控制台脚本，将最新回测状态整理为下一交易日的简洁仓位清单。

## What Changes

- 新增 `print_latest_positions.py`，默认只读 `data/output_v2/backtest_results.xlsx`，支持指定其他工作簿路径。
- 从 `portfolio_qty` 按最大日期选取最新记录，只打印大于零的标的，保留工作表列顺序、代码后缀及整数数量。
- 从 `portfolio_value` 精确匹配同一日期的 `cash`，最后输出两位小数的现金金额。
- 使用已有 Tushare 依赖查询沪深市场交易日历，首行输出源日期之后第一个交易日，格式为 `YYYY-MM-DD`；后续行固定为 `代码: 数量`，末行为 `cash: 金额`。
- 明确空表、日期歧义、非法数量、缺少同日现金和日历查询失败的错误行为；失败不输出半份清单。
- 补充中文使用说明、函数文档及不依赖实时网络的回归测试。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `portfolio-value-export`：增加从已有工作簿生成最新仓位控制台摘要的契约；既有 Excel 导出契约保持不变。

## Impact

新增独立脚本与测试，更新 README；复用 pandas、openpyxl、dotenv、tushare 及已有金额格式规则，不增加第三方依赖。沿用 `TushareToken` 和可选 `TushareIP` 配置，但不导入会更新行情的脚本。

不修改回测、Excel 结构及输入文件，不触发 QMT UI、剪贴板、下单或自动运行策略。当前工作簿的本地修改属于用户数据，本轮及后续实施均不应覆盖它。
