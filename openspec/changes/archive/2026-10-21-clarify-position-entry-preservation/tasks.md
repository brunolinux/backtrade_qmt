# Tasks

## 1. 明确公共入场信息接口

- [x] 1.1 将 `strategy_common.normalize_positions` 改名为 `preserve_entries_for_unchanged_quantities`，保持签名、条件和返回值不变；同步公共函数文档、两个策略的导入与调用及测试引用。用 `rg` 确认源代码与测试不再引用旧名称，并运行 `.venv/Scripts/python.exe -m unittest discover -s tests` 验证。
- [x] 1.2 核对新名称的关键字调用、数量未变时恢复原入场价与时间、数量变化时保留候选信息，以及输入不变；通过相关公共状态转换测试，并确认不提供旧名称别名。

## 2. 移除 v2 冗余调用并验证回测

- [x] 2.1 删除 `strategy_momentum_v2._calc_daily_positions` 在保留持仓筛选后的入场信息修正调用及对应空注释，保留调仓后的调用和交易记录顺序；运行 v2 回测流程测试，核对权益、持仓和交易输出。
- [x] 2.2 运行完整测试、`openspec validate clarify-position-entry-preservation --strict` 和 `git diff --check`；检查差异仅涉及本变更，不覆盖工作区原有改动。
