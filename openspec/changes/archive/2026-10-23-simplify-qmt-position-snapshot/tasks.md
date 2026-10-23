# Tasks

## 1. 单记录持仓快照

- [x] 1.1 将 `tests/test_qmt_passorder.py` 的重复记录场景改为期望初始化失败，验证错误包含代码、定时器与委托均未发生；先运行定向测试确认因当前叠加行为而失败。
- [x] 1.2 修改 `qmt_passorder.py` 的 `_snapshot()`：校验后直接构建 `Holding`，受支持 ETF 代码重复时抛出明确错误；运行定向测试确认正常单条、无记录、非法数量、不同代码及重复记录场景均通过。
- [x] 1.3 更新 `qmt_passorder.md` 的快照说明，从“合并同代码”改为“一代码一记录，重复则整次初始化失败”；对照测试及文档核实行为一致。

## 2. 数据结构注释

- [x] 2.1 给 `Holding`、`Snapshot`、`PlannedOrder` 添加简短字段语义与单位注释，明确 `Snapshot.holdings` 仍是可变字典；检查 GBK 解码、Python 3.6 语法及注释与实际字段一致。

## 3. 集成验证

- [x] 3.1 运行 `.venv/Scripts/python.exe -m unittest discover -s tests` 与 `openspec validate simplify-qmt-position-snapshot --strict`，审阅差异，确认仅影响快照重复记录处理及说明，保留其他用户工作区修改。

## Workflow follow-up

- 若归档，先处理 `implement-qmt-timed-target-rebalancing`，再处理本变更，以保留规划的先后关系。
