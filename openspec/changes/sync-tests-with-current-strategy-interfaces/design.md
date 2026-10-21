# Design

## Context

见 `proposal.md`。目前 `strategy_momentum_v2` 提供 `calc_daily_positions` 和 `build_backtest_results`，而部分测试仍使用旧的下划线名称。`portfolio_accounting.calc_equity_close` 已在函数内构造下一价格基准，不再提供 `build_close_marks`。现有规格要求估值返回完整价格基准并保护输入；本次不改变该契约。

## Goals / Non-Goals

**Goals:** 让测试调用现有接口，同时继续验证空/非空结果表、具名记录、交易记录、每日持仓、估值基准及输入不变性。

**Non-Goals:** 恢复旧函数别名、调整策略计算规则、改变生产接口或增加新规格。

## Decisions

1. 对两个仍存在但已改名的函数，直接更新测试调用名称，保留原断言。这样测试对应实际调用路径。另一方案是在生产模块添加旧名别名，会保留已废弃接口并掩盖测试过时问题。
2. 将 `build_close_marks` 的独立单元测试改为通过 `calc_equity_close` 构造持仓和行情来验证：当日收盘价覆盖旧值、停牌或残留键保留、输入不变、返回字典与旧字典不共享；无当日报价时仍返回独立基准。关键字参数测试保留对 `calc_equity_close` 的具名调用和完整返回值断言，删除对已移除辅助函数的重复调用。另一方案是直接断言字典解包表达式，但无法验证真实估值入口。

## Risks / Trade-offs

- [改用集成入口后，原辅助函数的任意映射合并行为不再单独可测] → 重点验证估值接口承诺的持仓价格、停牌和残留键场景。
- [只替换旧名称可能使旧断言未覆盖新行为] → 保留现有结果、重复调用及输入保护断言，并运行完整单元测试。

## Migration Plan

仅调整四份测试文件；先同步函数名，再迁移价格基准用例，最后运行 `.venv\Scripts\python.exe -m unittest discover -s tests`。如结果与既有断言不一致，先核对测试输入与当前接口契约，不以修改生产代码作为此变更的默认处理。
