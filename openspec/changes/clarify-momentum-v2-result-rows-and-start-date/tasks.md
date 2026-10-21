# Tasks

## 1. 明确共享持仓快照行

- [x] 1.1 在 `strategy_common.py` 定义 `PortfolioRow`，让 `build_portfolio_snapshot` 以具名字段构造并返回该类型，更新函数类型及中文 Google 风格文档；在共享快照测试中核对属性、元组兼容性、现金行和输入不变，运行对应测试。

## 2. 统一 v2 报表行及结果表定义

- [x] 2.1 在 `strategy_momentum_v2.py` 定义 `EquityRow` 并用于 `equity_rows`，将每日快照直接追加到 `portfolio_rows`；以具名字段和 `PortfolioRow._fields`、`EquityRow._fields`、`Trade._fields` 构造三张表，更新相关文档。扩展 `tests/test_momentum_v2_backtest_flow.py` 的空表、非空表及行属性测试，核对列序、索引、dtype、数值和输入不变后运行对应测试。

## 3. 清理日期重复判断

- [x] 3.1 保留工作区现有的预处理后时间线筛选，只删除 v2 循环内重复的 `start_date` 判断；先复现字符串日期的现有失败，再运行起始日包含、指标历史、无行情及起始日晚于全部行情的测试，确认均通过且其他用户改动原样保留。

## 4. 集成验证

- [x] 4.1 运行完整 unittest、OpenSpec 严格校验和 `git diff --check`，核对两个策略的固定回测、CSV 字节输出、日志顺序及三张结果表的兼容性，并检查最终差异仅包含本变更及进入实施前已有的工作区改动。
