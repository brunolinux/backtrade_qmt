# Tasks

## 1. 同步策略函数调用

- [x] 1.1 将 `tests/test_momentum_v2_backtest_flow.py` 中的旧函数调用更新为 `calc_daily_positions` 与 `build_backtest_results`，运行该文件的单元测试并确认原有结果表、持仓及输入保护断言通过。
- [x] 1.2 将 `tests/test_trade_records.py` 中的旧结果构造函数调用更新为 `build_backtest_results`，运行该文件的单元测试并确认空、非空交易表断言通过。

## 2. 通过估值入口验证价格基准

- [x] 2.1 将 `tests/test_portfolio_accounting.py` 中依赖 `build_close_marks` 的测试改为调用 `calc_equity_close`，覆盖当日覆盖、残留/停牌键、无当日报价和输入不变性，运行该文件的单元测试确认通过。
- [x] 2.2 移除 `tests/test_strategy_keywords.py` 中对已删除函数的调用，保留具名调用、完整基准和输入保护断言，运行该文件的单元测试确认通过。

## 3. 集成检查

- [x] 3.1 运行 `.venv\Scripts\python.exe -m unittest discover -s tests`，确认全部测试通过且不再有对三个旧函数名的引用。
