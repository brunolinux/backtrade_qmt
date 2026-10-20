# Tasks

第 1 至第 3 组为首轮记账提取的已完成记录；第 4 组为确认后的公共策略模块提取增量，以下以当前设计为准。

## 1. 锁定旧实现的兼容基线

- [x] 1.1 在 `tests/test_portfolio_accounting.py` 使用 unittest 和合成 DataFrame 固定旧入口的手算案例，覆盖多标的涨跌、空仓、零数量、带符号数量、缺少基准、未持有标的、停牌及复牌；验证迁移前旧实现通过这些案例，权益及 `prev_close` 均有独立预期值。
- [x] 1.2 在迁移前固定最小 v2 合成回测的预期 portfolio、curve 和 trades，包含开仓及后续价格变化；验证测试不访问外部行情、不写业务 CSV 且对原实现通过。

## 2. 实现通用记账函数及结算入口

- [x] 2.1 新增 `portfolio_accounting.py` 的 `calc_mark_to_market_equity` 和 `update_close_marks`，按设计采用数量、价格映射；增加测试验证纯计算重复调用结果一致、输入不变，基准更新仅影响传入快照对应的键，手算多标的权益正确。
- [x] 2.2 实现保持旧签名的 `update_equity_close`，由一次行情快照执行先计算后更新；验证第 1 组兼容案例对新入口通过，并覆盖重复日期取末值、缺失列或无效值导致的 NaN 传播。
- [x] 2.3 为三个接口补充中文 docstring，明确参数、返回值、副作用、缺行情与缺基准处理以及调用顺序；验证模块不导入策略模块，直接调用样例能产生预期权益和基准。

## 3. 迁移调用并验证集成兼容性

- [x] 3.1 在 `strategy_momentum.py` 以导入或薄封装替换本地重复盯市实现，保留旧调用签名及导入路径；验证新旧入口对相同案例的权益、基准修改及输入保护行为一致，并保留工作区已有 Trade 相关修改。
- [x] 3.2 将 v2 的盯市入口改为直接从 `portfolio_accounting` 导入，保持每日调用位置及开仓基准初始化；验证第 1.2 项固定的完整回测输出一致，接口仍返回 portfolio、curve、trades。
- [x] 3.3 执行 `python -m unittest discover -s tests`，确认记账、v2 回测和既有交易记录测试全部通过；检查差异只包含本次约定的模块、调用迁移及测试，v3 和其他业务算法未被修改。

## 4. 提取公共策略模块并复用 getv

- [x] 4.1 在 `tests/test_strategy_common.py` 固定当前公共函数的合成样例及独立预期值，覆盖行情读取、ATR、相关矩阵、数量取整、仓位规模、杠杆、止损、调仓、交易记录及组合信息；验证迁移前实现通过，输入修改边界及输出格式有明确断言，沿用现有 Trade 和 v2 回测基线。
- [x] 4.2 新增 `strategy_common.py`，迁移 `getv`、`atr`、`calc_corr_matrix`、`calc_quantity`、`calc_position_size`、`calc_leverage_by_vol`，保持签名及语义并补充模块职责说明；验证 4.1 对应数值案例对新模块通过，包含 getv 重复日期取末值及无效值返回 NaN。
- [x] 4.3 将 `Trade`、`update_stop_price`、`update_portfolio`、`update_trades`、`update_portfolio_info` 迁入公共模块，保持既有副作用并说明接口职责；验证 4.1 对应案例及既有交易记录语义通过，公共模块无需导入策略或记账模块。
- [x] 4.4 两个策略直接从 `strategy_common` 导入公共函数，保留旧公开名称的兼容出口；各自保留预处理、信号、选股、保留仓位及回测编排，消除 v2 对旧策略的直接导入；验证旧导入路径仍可调用、Trade 类型保持一致且既有固定回测输出不变。
- [x] 4.5 删除 `portfolio_accounting._read_close`，使用 `strategy_common.getv(df, time, 'close')` 构造快照；验证重复日期、无效或缺失列、停牌复牌、输入保护及单次价格读取的记账测试通过，保持先计算后推进基准。
- [x] 4.6 执行 `.venv/Scripts/python.exe -m unittest discover -s tests`，确认公共模块、记账及既有交易记录和回测测试全部通过；在新进程中分别独立导入公共模块、记账模块及两个策略，验证无循环依赖、不依赖已删除文件，并检查变更未恢复用户删除的文件或修改策略算法。
