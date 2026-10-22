# Tasks

旧版两行中文日期标签已实现；以下任务跟踪本次确认的配置片段与资产金额输出，原完成标记按新验收要求重新打开。

## 1. 同日总资产与配置片段

- [x] 1.1 扩展 `LatestPositions`、读取函数及中文 docstring，提取并传递源日期的有限 `total_value`，同步构造调用和测试；验证两表末日不同仍匹配同日现金及总资产，缺列/缺值/非数值/无穷时明确失败，不补零或重算且工作簿字节不变。
- [x] 1.2 更新格式化函数、中文文档及 README，以 SIGNAL_DATE、TRADE_DATE、TARGET_QUANTITIES、TOTAL_VALUE 和中文现金/总市值替换旧布局；用精确字符串和固定日历入口测试验证日期不补零及跨年、双引号/四空格/末尾逗号、正仓位顺序、空字典七行输出、金额半入到分且两处总资产一致，以及异常时 stdout 为空。

## 2. 集成验证

- [x] 2.1 运行 `.venv/Scripts/python.exe -m unittest discover -s tests` 和 `openspec validate clarify-position-report-trade-dates --strict`，确认赋值片段、同日金额及既有日历和输入保护回归全部通过；核对文档样例与入口输出格式一致，差异未修改日历请求或用户工作簿。
