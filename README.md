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
