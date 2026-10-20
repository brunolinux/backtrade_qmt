# Tasks

## 1. 核对回测基线

- [x] 1.1 检查工作区并运行 `.venv/Scripts/python.exe -m unittest discover -s tests`，确认实际基线、两个策略的固定回测及 CSV 用例通过；记录当前空结果表的列、索引和 dtype，核对每日估值、历史追加及条件调仓顺序，保留已有 add-portfolio-total-value 归档及主规范差异。

## 2. 提取结果表构造

- [x] 2.1 在 strategy_momentum_v2.py 提取 `_build_backtest_results(portfolio_rows, equity_rows, trade_records)` 并接入 backtest，补充中文 Google 风格文档；以真实输入列表验证空及非空三张表的独立预期、列序、索引、dtype 和输入不变，同步 tests/test_trade_records.py 的 v2 转换用例以调用新函数，确认旧策略转换测试、完整回测及 CSV 字节验证仍通过。

## 3. 提取每日持仓决策

- [x] 3.1 提取设计中的 `_calc_daily_positions`，通过新持仓、新完整价格基准和当日 Trade 列表返回结果，补充准确类型及 Google 风格文档；用真实行情和 Position 验证满仓时 100 股不调仓、有空位但未买入时仍调至 800 股且切换收益为 200、实际开仓与退出先于调仓的顺序，以及停牌、残留及新开仓基准保留，验证所有输入只读、返回外层映射独立和重复调用结果一致。

## 4. 简化入口并明确局部名称

- [x] 4.1 在 backtest 接入每日函数并按设计表迁移局部名称，保留预处理、时间线、估值、权益历史及结果收集，更新相关文档并移除尾部过时注释块；验证原位置和关键字调用的三张固定回测表、输入保护、满仓和空位分支、使用包含当日权益的历史计算非固定杠杆、start_date 之前的完整指标历史及起始日包含规则、晚于全部行情和空行情的空表结果，日志文字与顺序保持原样。

## 5. 验证整体兼容性

- [x] 5.1 运行全套 unittest、v2 模块独立导入、`openspec validate refactor-momentum-v2-backtest-flow --strict` 及差异检查；人工核对仅新增两个私有辅助函数并调整 backtest，公开签名、默认值、配置键、Position、Trade、公共计算、旧策略、日期规则、日志和导出脚本未改变，现有主规范及其他归档差异原样保留，所有回测、空结果、CSV、分支和输入保护测试通过。
