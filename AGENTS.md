## 1. 项目概述 Project Context

本项目是 Python 语言的ETF量化回测，数据源采用 tushare，数据处理使用 pandas + numpy, 可视化使用 matplotlib, 实盘使用 qmt，回测框架是自研的

## 2. 目录结构 & 职责

- `factor/`: 因子目录
- `update_tushare.py`: 日频数据更新脚本
- `backtest_etf_v2.py`: 回测脚本，加载数据，根据模型计算信号，选择标的，将买入标的和数目存放在对应文件中
- `strategy_momentum_v2.py` + `strage_momentum.py`: 动量模型
- `data`: 数据存放目录, `input` 子目录存放原始数据, `output_v2` 子目录存放输出目录

