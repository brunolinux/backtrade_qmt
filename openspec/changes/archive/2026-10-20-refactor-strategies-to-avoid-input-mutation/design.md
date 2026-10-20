# Design

## Context

动机与范围见 `proposal.md`，行为约束见 `specs/strategy-state-transitions/spec.md`。当前四个目标模块已经分离公共工具和组合记账，但仍存在以下写入：两个 `preprocess` 替换输入字典中的 DataFrame；旧策略开仓函数原地排序 signals；公共止损函数修改嵌套持仓；交易记录函数在数量不变时恢复候选持仓的入场信息；收盘结算修改输入价格基准。

`rebalance` 对应的原调仓函数和两个保留仓位函数已经逐记录复制，不需要改变算法。`update_portfolio_info` 对 equity 的减法是数值局部重绑定，并不修改调用方。现有测试中有多处明确断言输入被修改，必须迁移到返回值断言，不能直接删除这些行为案例。已有 v2 六天回测及 CSV 测试可作为输出基线；旧策略需要增加完整合成回测基线。

## Goals / Non-Goals

**Goals:**

- 对调用方传入的行情、信号、参数、持仓及价格基准保持只读，下一状态通过返回值接收。
- 返回的持仓记录、行情及价格字典与对应输入隔离，使调用方后续编辑返回结果不会改写原输入。
- 保留当前标量持仓结构、数值口径和回测编排顺序，不把接口调整混入策略修正。

**Non-Goals:**

- 不引入冻结字典、不可变 DataFrame、账户对象或 `_inplace` 双版本接口。
- 不禁止函数修改自己创建的局部对象，回测的 append、extend 及局部字典合并可继续使用。
- 不处理任意深度的自定义可变持仓字段，当前持仓字段为数值、字符串和时间戳；不要求递归复制 object 列内任意 Python 对象。
- 不纠正现金展示、复权口径、交易盈亏算法、信号缺失处理等既有规则，不移除回测打印，也不将范围扩展到因子数据加载或 QMT。

## Decisions

### 1. 统一迁移函数名称和返回值

| 原入口 | 新入口 | 返回值与行为 |
| --- | --- | --- |
| `update_equity_close` | `calc_equity_close` | `(equity, next_close)`，不改输入 |
| `update_close_marks` | `build_close_marks` | 新的完整价格基准字典 |
| `update_stop_price` | `calc_stop_positions` | 新持仓字典及独立持仓记录 |
| `update_portfolio` | `rebalance_portfolio` | 保留现有返回新持仓的算法 |
| 两个 `update_reserve_pos` | 各自的 `select_retained_positions` | 各策略继续持有的独立持仓结果，保留各自参数和筛选规则 |
| `update_portfolio_info` | `build_portfolio_snapshot` | 原有持仓及现金行列表 |
| `update_trades` | `normalize_positions` 与 `calc_trade_records` | 分别返回修正持仓及交易记录，见决策 4 |
| 两个 `preprocess` | 名称不变 | 返回新的行情字典 |
| 旧策略 `calc_buy_pos` | 名称和返回值不变 | 使用 sorted 生成局部有序信号，继续返回新增持仓与开仓基准 |

`calc_mark_to_market_equity` 的名称、参数及返回权益的职责不变。其余已不修改输入的函数保留现有接口。

此次统一迁移仓库内调用与测试，不保留旧 `update_` 别名或修改输入的兼容封装。相比维持两套名称和行为，单一接口使输入保护约定明确；旧名称的外部调用需迁移，proposal 已标记 BREAKING。两个 `backtest` 的签名和返回三张表保持不变。

### 2. 按数据边界复制，保持局部实现简单

预处理构造新字典，每个标的在排序和去重后取得独立 DataFrame，再添加指标。使用显式 copy 保证现有数值行情与返回结果隔离，不依赖 pandas 版本是否启用写时复制。只在预处理边界复制完整历史行情，每日函数只读使用。

止损、持仓修正及持仓选择的输出采用逐记录复制：`{sym: p.copy() for sym, p in pos.items()}`，仅复制外层字典不足以保护 `stop`、`entry` 等嵌套字段。价格基准为标量映射，浅拷贝和合并足够；空仓或当日无行情时也返回独立的状态字典。快照行是标量元组，Trade 仍为现有 NamedTuple。

输入只读是接口约定，不强制所有输入对象的类型本身不可变。无需为局部排序列表、候选持仓和曲线累计禁止修改，也无需逐日深拷贝所有数据。

### 3. 估值计算返回完整下一基准

`calc_equity_close(df_all, pos, prev_close, time, prev_equity)` 从当日有行情的持仓读取一次 getv，构造 quantities 与 current_close，先调用既有 `calc_mark_to_market_equity`，再调用 `build_close_marks(current_close, prev_close)`，最后返回权益与新基准。

`build_close_marks` 返回 `{**prev_close, **current_close}`。仅返回当日价格会丢失停牌标的基准，因此保留无行情持仓及旧残留键，与现有内容语义一致。缺少基准时仍使用当日价作为盈亏起点；NaN 传播、重复日期取末值、浮点累加顺序保持不变。

不再向调用方原有基准写入；重复使用相同输入计算得到相同结果。跨日期或跨调用的状态推进由调用方显式接收，不增加按日去重机制。

### 4. 拆开持仓修正和交易记录计算

新增 `normalize_positions(new_pos, old_pos) -> dict`，先复制所有候选持仓记录。对于新旧共有标的，严格保留旧逻辑的判断顺序：入场时间相同则不修正；否则若数量相同，返回记录恢复旧 entry_time 和 entry；其余候选记录保持原值。该函数不访问行情、不计算盈亏、不生成记录，也不修改任一输入。

新增 `calc_trade_records(df_all, time, new_pos, old_pos) -> list[Trade]`，只读计算记录，保留旧平仓及切换仓位计算规则。零数量、同日平仓、相同入场时间、数量不变等原跳过条件保留；输入未预先修正时，数量不变仍不生成记录。

旧算法的切换仓位盈亏使用原持仓全部数量，本次继续保留，不改为新增或减仓数量。入场修正同时用于退出筛选和调仓两个阶段，不能仅迁移其中一个调用点。相比返回 `(trades, positions)` 的混合函数，该拆分使记录计算与持仓状态分别有单一返回职责。

### 5. 回测显式接收每步结果

两个 backtest 预处理阶段改为局部 `df_all = preprocess(df_all, ...)`。每日顺序保持为：

```text
calc_equity_close -> calc_stop_positions -> strategy selection
    -> normalize_positions -> calc_trade_records -> accept positions
    -> build new entries -> rebalance_portfolio
    -> normalize_positions -> calc_trade_records -> accept positions
    -> build_portfolio_snapshot
```

每次用原状态和候选状态生成修正结果及交易记录后，再将局部 pos 绑定为新持仓。收盘基准通过 `equity, prev_close = calc_equity_close(...)` 接收，开仓价仍按原规则初始化到回测局部基准。局部 `pos.update`、`prev_close.update` 和 `trades.extend` 可以保留，前提是这些容器属于本次回测而非调用方输入。

保持信号、止损、持仓数量、相关约束、波动率杠杆和调仓执行时点。对外输出仍为 portfolio、curve、trades；不要求调用方接收内部行情，也不改变 `backtest_etf_v2.py` 的导出接口。

### 6. 用输入快照和迁移前结果共同验收

测试分两类：输入保护断言和数值兼容断言。每个修改过输入的旧案例仍保留其业务预期，但改为断言返回结果正确、输入未变；补充编辑返回对象后原输入仍未变、相同输入重复调用结果相同的检查。

覆盖两种预处理、旧信号排序、空仓、缺行情、缺基准、停牌后复牌、重复日期及无效行情；价格读取次数沿用现有测试的可观测行为。交易记录用例保持空表、零股、同日、数量不变恢复入场、加减仓及完整平仓分支。

在实施改动前固定旧策略完整合成回测预期，沿用 v2 固定表格；两个回测均重复使用相同原始行情及 params 执行，检查输入行情、原始 DataFrame 引用和参数保持不变，输出表与基线一致。测试不下载行情、不连接 QMT，CSV 测试仅使用临时目录。

## Risks / Trade-offs

- [改名破坏旧导入]：同步迁移目标模块、测试及仓库内引用，文档列出一对一映射；不保留修改输入的旧版本。
- [仅拷贝外层字典造成嵌套写入]：逐持仓记录复制，测试修改返回记录后的原输入；DataFrame 在预处理边界显式复制。
- [拆分交易函数丢失入场修正]：两个状态接受阶段都先修正再计算记录，通过未改股数场景和后续平仓盈亏验证。
- [无行情时丢失基准]：返回完整字典而非当日价格子集，测试停牌复牌和残留键。
- [预处理复制增加内存]：只在预处理时隔离历史行情，不在每个交易日复制历史数据；保持当前标量持仓结构。
- [旧测试依赖副作用]：替换为新状态断言且保留业务预期，禁止通过删除分支测试使测试表面通过。

## Migration Plan

1. 以实施开始时工作区为基准，保留 `portfolio_accounting.py` 的用户文档调整，先保存两种策略回测及交易数值基线。
2. 实现并验证估值、预处理、止损和交易拆分的新接口，随后同步迁移调用处及依赖副作用的测试。
3. 完成其余 `update_` 命名迁移，运行 `.venv/Scripts/python.exe -m unittest discover -s tests` 及 OpenSpec 校验，检查目标旧函数名称无运行时引用。
4. 本次无需数据迁移或外部发布。如需回退，以本变更的独立提交或文件差异恢复旧接口与调用，不覆盖用户原有文档调整，也不修改已归档变更。
