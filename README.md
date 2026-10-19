# 动量策略

## 调用流程

1. 执行 `update_tushare.py`, 它根据 `factor/config_etf.py` 文件存放的标的信息，从 tushare 数据库拉取日线级别的量价数据，保存到 *data/input/etf* 目录, 
2. 执行 `backtest_etf_v2.py`