# 动量策略

## 调用流程

1. 执行 `update_tushare.py`, 它根据 `factor/config_etf.py` 文件存放的标的信息，从 tushare 数据库拉取日线级别的量价数据，保存到 *data/input/etf* 目录, 
2. 执行 `backtest_etf_v2.py`

回测输出到 `data/output_v2/backtest_results.xlsx`，包含 `trade`（交易记录）、
`portfolio_value`（标的市值、现金和末列总资产）及 `portfolio_qty`（标的数量）三个工作表。
标的使用 QMT 代码，例如 `159650.SZ`、`518880.SH`；交易名称和代码分别为 `name`、`symbol`。
数量表不含现金，数量为整数且为 100 的倍数。实际权益、市值、现金和盈亏在代码中按分四舍五入，
Excel 显示两位小数；原始行情价格和信号计算保留精度。本次不计手续费。
脚本不再生成三份 CSV，已有历史 CSV 不删除；读取旧文件的程序需要迁移到工作簿。

## 打印最新目标仓位

执行 `python print_latest_positions.py`，只读默认工作簿；也可使用
`python print_latest_positions.py --workbook 路径/backtest_results.xlsx`。
默认文件相对脚本定位，显式相对路径按当前工作目录解析。

脚本按 `portfolio_qty` 的最大日期选择仓位，从 `portfolio_value` 匹配同日现金及总资产。
`SIGNAL_DATE` 为最新仓位源日期，`TRADE_DATE` 为该日期的下一沪深交易日，月日不补零。
`TARGET_QUANTITIES` 按原列顺序只包含正仓位，代码使用双引号、数量为整数。
随后打印模拟总资产赋值，以及供人工核对的现金和总市值，金额均保留两位小数：

```text
SIGNAL_DATE = dt.date(2026, 10, 22)
TRADE_DATE = dt.date(2026, 10, 23)
TARGET_QUANTITIES = {
    "159650.SZ": 500,
    "512800.SH": 133400,
}
TOTAL_VALUE = 239253.90
现金: 38204.90
总市值: 239253.90
```

日历查询使用已有 Tushare 依赖。请配置环境变量 `TushareToken`，可选 `TushareIP`
用于自定义接口地址；项目根目录 `.env` 中的同名配置也可使用，已有环境变量优先。
接口查询源日期后 31 个自然日，按开市标记选择最早日期，处理周末、节假日和跨年。
样例日期仅展示格式，实际结果以接口日历为准。

日期不取脚本执行当天；没有正仓位时字典保留开始与结束两行，连同日期和三行金额共七行。
`TOTAL_VALUE` 与“总市值”同取包含现金的 `total_value`，不会再次加上现金。
复制前半部分赋值片段到 Python 策略时，需要调用方已有 `import datetime as dt`；
脚本不额外输出导入语句，末尾两行中文金额是核对信息，不属于可执行配置片段。
空表、日期重复、缺少或无效的同日现金/总资产、数量不合法、认证或
日历查询失败时返回非零退出码，错误写入标准错误，不输出部分清单，也不猜测交易日。
脚本不会更新行情、改写工作簿或操作 QMT。
