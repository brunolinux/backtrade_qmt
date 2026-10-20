# Tasks

## 1. 交易记录模型与共享函数

- [x] 1.1 在 `strategy_momentum.py` 定义六字段 `Trade(NamedTuple)` 并说明字段含义，在 `update_trades` 的平仓和切换仓位分支以关键字构造记录，补充 `list[Trade]` 返回注解；检查差异，确认字段顺序、原有条件、收益计算、原因文本及 `pos` 字典操作保持不变。
- [x] 1.2 使用标准库 `unittest` 在 `tests/test_trade_records.py` 添加本地回归验证：用固定行情和持仓验证止盈、止损与切换仓位生成记录的六字段完整值及具名属性访问，覆盖同日、零数量跳过及数量不变时入场信息恢复；执行 `python -m unittest discover -s tests -v` 并确认通过，无需行情下载。

## 2. 调用方与导出兼容性

- [x] 2.1 在同一本地测试文件覆盖两个回测调用方现有交易 DataFrame 转换方式，检查空记录和非空记录的六列名称、顺序及值；用临时文件验证现有 GB2312 CSV 导出的交易内容与普通元组基准一致，运行 `python -m unittest discover -s tests -v` 确认通过。
- [x] 2.2 执行 `python -m py_compile strategy_momentum.py strategy_momentum_v2.py backtest_etf_v2.py`、`openspec validate refactor-trade-records-to-namedtuple --strict`，并复核最终差异，确认本变更仅包含交易记录重构及其验证，没有持仓类型或输出格式改动。
