# Tasks

## 1. 说明回测初始化状态

- [x] 1.1 在 `strategy_momentum_v2.backtest` 的七个初始化变量附近添加简短中文分组注释，准确说明账户状态、估值价格基准、累计记录和报表原始行；核对注释与每日估值、持仓决策及结果构建的实际调用顺序一致。
- [x] 1.2 核对 `backtest` 的非注释代码和函数签名未变，保留工作区已有改动；运行 `.venv/Scripts/python.exe -m unittest discover -s tests` 与 `git diff --check` 验证。
