# Design

## Context

见 [proposal.md](proposal.md) 的 Why。`build_portfolio_snapshot` 当前输出四元组，v2 回测另行追加二元组，`_build_backtest_results` 按位置解释并手写三组列名。`Trade` 已是 `NamedTuple`。现有测试固定了空表的列、索引及 dtype，也固定了六天回测、起始日包含规则和输出日志。当前未提交的日期筛选改动须在实施时保留，并去掉其遗留的循环判断。

## Goals / Non-Goals

**Goals:**

- 让报表行的字段名成为构造和列顺序的单一来源，同时保留 pandas 对数值和空表的现有推断结果。
- 保持回测每日估值、决策、记录及最终转换的先后顺序；起始日期仅在预处理后的时间线上应用一次。

**Non-Goals:**

- 不修改公开 `backtest` 签名、业务算法、CSV 导出代码或返回表结构。
- 不把 `equity_history` 与用于输出的权益行合并，也不新增回测状态类。

## Decisions

### 1. 用 `NamedTuple` 表达两类报表行

在 `strategy_common.py` 定义 `PortfolioRow(datetime, symbol, quantity, value)`，由共享的 `build_portfolio_snapshot` 通过字段名构造并返回 `list[PortfolioRow]`；在 `strategy_momentum_v2.py` 定义仅供 v2 使用的 `EquityRow(datetime, equity)`，由每日循环追加到 `equity_rows`。两者均为元组子类，可供现有按位置处理的调用方和 pandas 读取；共享类型放在快照生成函数所在模块，避免反向依赖。

选择 `NamedTuple` 而非字典或 `dataclass`：本项目已有 `Position`、`Trade` 的不可变具名记录，且可直接提供稳定字段顺序，不需要逐行转字典。`equity_history` 仍保持纯数值列表，供杠杆计算。

### 2. 结果构造只负责表结构，不重复维护字段列表

`_build_backtest_results` 分别用 `PortfolioRow._fields`、`EquityRow._fields`、`Trade._fields` 传给 `DataFrame(columns=...)`；日期列仍显式设为索引，返回顺序仍为持仓、权益、交易。显式传入列名对空列表不可缺少，并保留原空表索引类型和列顺序。函数保留三个累计列表参数及独立构表职责；已有普通元组列表仍可按相同位置被转换，但回测本身生成具名行。

相比在函数内保留三组字符串常量，字段变化只需修改记录类型即可同步列名；相比直接从非空首行推断，空表也有确定结构。输出列名仍是兼容性契约，不应任意动态变化。

### 3. 保留预处理后的日期筛选，删除逐日重复判断

沿用现有 `if start_date` 真值判定，将其解析为 `Timestamp` 后筛选已排序的 `timeline`；循环仅处理筛选结果，不再将 `Timestamp` 与原始字符串 `start_date` 比较。筛选不得移到 `preprocess` 之前，以保留指标所需的早期行情。此处不引入新的日期搜索依赖或改变空值、非法日期的现有入口约定。

## Risks / Trade-offs

- [快照行改为元组子类，极少数依赖精确 `type(row) is tuple` 的调用方可能受影响] → 保持字段数量、顺序和值不变，并覆盖共享快照及两个策略的现有用例；本次目标是提供具名字段。
- [pandas 对空记录或混合数值的类型推断可能变化] → 对空、非空结果逐表使用 `assert_frame_equal` 核对列、索引、dtype 和值，并复核 CSV 字节兼容性。
- [当前工作区含用户未提交的日期筛选改动] → 实施时只移除其重复判断，保留其余用户改动，先复现再修复字符串日期测试。

## Migration Plan

无持久数据迁移。先更新共享快照行和 v2 内部行类型，再调整结果构造和日期循环，最后运行针对性及完整回归测试；若出现兼容问题，可单独回退本次代码改动而不触及输入数据。
