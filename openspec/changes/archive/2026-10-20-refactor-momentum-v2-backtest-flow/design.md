# Design

## Context

动机与范围见 `proposal.md`。当前 backtest 在预处理之后，按行情日期并集遍历：先对旧持仓估值并追加权益历史，再处理止损、因子排名、持仓退出、条件补仓与调仓，最后记录快照并构造三张结果表。Position 和 Trade 已经是公共具名元组，基础计算均已有独立函数。

现有测试包含两个策略的固定六天回测、输入不变、关键字调用、交易表和 GB2312 CSV 预期。tests/test_trade_records.py 还直接查找并执行 backtest 函数体内名为 trades 的 DataFrame 赋值语句，提取结果构造时需要解除这项 v2 测试对原位置和变量名的依赖。

这是纯内部重构，主规范不需要增加或修改要求，specs 已通过 skip_specs 标记跳过。设计文档用于提前明确函数边界及顺序依赖。

## Goals / Non-Goals

**Goals:**

- backtest 保留清晰的回测编排，日内持仓转换与最终表格转换各有一个独立职责。
- 从局部名称区分持仓阶段、估值基准、配置预算、历史数列和最终 DataFrame。
- 新辅助函数读取输入，通过返回值提供新状态；复用已有函数及其边界规则。

**Non-Goals:**

- 不创建回测引擎类、统一状态对象、新模块、公共辅助接口或配置模型。
- 不修改旧策略、公共计算、记账、Position、Trade 或 CSV 导出脚本。
- 不更改日期解析规则、日志文字、异常处理、warmup、交易顺序或业务算法。
- 不合并权益历史与结果记录两个容器，不全面重命名本文件其他函数的局部变量，不清理与本次无关的导入。

## Decisions

### 1. 仅新增两个模块内私有辅助函数

| 函数 | 输入与输出 | 职责 |
| --- | --- | --- |
| `_calc_daily_positions(market_data, positions, close_marks, timestamp, equity, equity_history, params)` | 读取已预处理行情、完成估值但未处理止损的持仓、当日估值基准与权益、包含当日权益的历史及原配置；返回 `(next_positions, next_close_marks, daily_trades)` | 止损、排名、筛选、退出交易、条件开仓和调仓 |
| `_build_backtest_results(portfolio_rows, equity_rows, trade_records)` | 读取三个累计记录列表，返回 `(portfolio, equity_curve, trades)` | 按原列名、索引和 pandas 推断规则构造三张表 |

每日函数接收的 positions 是刚完成估值、尚未处理当日止损的持仓；函数自身不再次估值，也不追加权益历史。其返回类型为 `tuple[dict[str, Position], dict[str, float], list[Trade]]`，从公共模块导入已有 Trade 仅用于准确表达交易记录类型。给新增函数补充中文 Google 风格 Args/Returns，说明各状态的时点及输入只读。

采用两个函数而不是为每两三行再建一层包装，可保持调用关系直接；沿用参数字典可避免独立配置对象与重复接口迁移。每日函数虽接收七个参数，但这些值均在回测入口显式维护，暂不引入容器隐藏它们。

### 2. backtest 保留估值、历史和快照的时序

入口保持 `backtest(market_data: dict, params: dict, start_date=None)`，按以下次序运行：

1. 初始化权益、空持仓、完整价格基准、交易及结果列表；对完整输入行情进行预处理。
2. 生成全部预处理行情日期的排序并集，按现有 truthy 判断解析及应用 start_date；保留起始日之前的数据用于指标计算。
3. 每日调用 calc_equity_close，取得权益与新基准，然后将权益追加到 equity_history。
4. 调用每日持仓函数，并显式接收持仓、新基准和当日交易；按原顺序扩展累计交易。
5. 用决策后持仓和同一份当日权益构造仓位快照，追加权益行并打印原进度文本。
6. 循环完成后调用结果构造函数并返回原三表元组。

仍保留预处理完成日志、每日完成日志及其位置。返回表的列、顺序、索引名、空表结构、dtype 推断以及日期频率表现保持原转换语句的行为，不增加排序、填充或显式 dtype。空行情或 start_date 晚于全部行情时仍构造空结果表。

### 3. 每日持仓函数保留条件及中间比较基准

先用 positions 计算 `stopped_positions`；再计算 `ranked_factors`，筛出 `retained_positions`，以 stopped_positions 为旧状态做入场修正及退出交易计算。之后计算 `available_slots = params['hold_max_num'] - len(retained_positions)`。

只有 available_slots 大于零时才调用开仓、杠杆和调仓逻辑；即使开仓返回空字典，此分支仍继续计算杠杆并调仓。available_slots 为零或负数时不执行该分支。开仓仍将剩余名额作为排名扫描上限，已有持仓仍消耗扫描范围。

开仓结果命名为 new_positions 和 entry_close_marks。合并后的候选组合用于整个持仓的调仓，调仓结果命名为 rebalanced_positions；入场修正和调仓交易记录均以“合并新开仓后的持仓”为比较基准，不能误用当天最初持仓。退出交易在调仓交易之前加入 daily_trades，不对现有 set 遍历产生的同阶段交易另行排序。

新基准以 close_marks 的浅副本为起点，合入全部 entry_close_marks；保留停牌、残留键及即使后续因调仓被移除的新开仓标的基准，不按最终持仓过滤。所有分支返回新外层持仓字典及独立价格基准字典，允许共享不可变 Position；不修改行情、输入持仓、价格基准、配置或 equity_history。

现有 normalize_positions 在部分阶段可能没有实际修正，本次仍保留调用，避免把流程抽取扩展成算法简化。

### 4. 固定局部命名与数据角色

| 原名称 | 目标名称与含义 |
| --- | --- |
| 覆盖原 market_data 的结果 | processed_market_data，含指标的行情 |
| pos | positions，入口持有并按日接收的新持仓 |
| prev_close | close_marks，完整估值价格基准 |
| t | timestamp，当前计算时刻 |
| sorted_factor | ranked_factors，降序因子序列 |
| reserve_pos | retained_positions，继续持有的仓位 |
| num_add | available_slots，剩余持仓名额，不是实际买入数 |
| 买入阶段的 cur_pos / cur_close | new_positions / entry_close_marks，新开仓与对应买入价基准 |
| 合并新旧持仓后的组合 | candidate_positions，供整体调仓的候选组合 |
| 调仓阶段的 cur_pos | rebalanced_positions，调仓及修正后的组合 |
| lev / real_equity | leverage / allocation_budget，目标杠杆及权益乘杠杆后的配置预算 |
| equity_hist | equity_history，供波动率计算的纯权益序列 |
| df_portfolio / cur_portfolio | portfolio_rows / daily_portfolio_rows，累计及当日快照行 |
| curve | 累计时 equity_rows，最终表为 equity_curve |
| trades | 累计时 trade_records，单日为 daily_trades，最终表为 trades |

equity 继续表示账户总权益，不改称市值；外部 backtest 元组第二项仍是同一权益表，调用方可以继续以 curve 接收。仅删除随抽取失去上下文的 backtest 尾部旧注释调试块，不扩展到其他函数的清理。

### 5. 用可观察结果保护分支和顺序

沿用原固定回测和 CSV 预期，补充直接执行两个私有函数的测试。每日函数测试使用真实计算函数及可手算的输入，至少区分：

- 持仓已满：单只 A 有 100 股、入场 10、当日价 12、ATR 1、旧止损 8、止损倍数 2、排名在保留范围、最大持仓数 1。即使权益为 10000，仍保留 100 股且止损为 10，不发生调仓交易。
- 有空位但未买入：相同持仓和行情，最大持仓数为 2、排名只有已持有的 A、杠杆固定为 1。扫描跳过 A 后仍调仓，配置预算 10000 时为 800 股、入场价为 12，并按原 100 股产生收益 200 的切换记录；完整价格基准保持既有键。
- 实际开仓、退出及再次调仓：保留原候选扫描上限、退出先于调仓的记录顺序、买入价基准合并及最终零股数处理，验证输入对象不变及重复调用一致。

入口层补充或保留真实回测用例，验证当前权益先进入历史再用于杠杆、预处理完整历史而输出受 start_date 过滤、满仓及无新增买入两类路径。优先验证独立数值与最终持仓，不以断言内部调用次数代替业务行为。

结果构造测试验证空及非空三张表的内容、列序、索引和 dtype，并确认输入列表不变；tests/test_trade_records.py 的 v2 转换用例直接调用新结果构造函数，旧策略的现有转换验证保持有效，不要求旧策略采用新结构。现有交易 CSV 字节验证继续执行，导出脚本不改动。

## Risks / Trade-offs

- [提取时将条件调仓误改为每日调仓]：分别验证满仓不调仓和有空位但没有新开仓仍调仓的独立数值。
- [权益历史或交易比较基准偏移]：入口保留估值后立即追加历史，每日函数明确各阶段的旧状态，保留完整回测及交易预期。
- [局部 update 泄漏到输入]：合并新状态前创建字典，验证输入行情、持仓、基准、参数和历史均不变。
- [测试锁定原函数体结构]：v2 结果构造测试调用新函数并比较实际表，不再搜索原赋值位置。
- [空表或 CSV dtype 发生变化]：沿用原 DataFrame 构造参数及空表预期，不加入显式 dtype、自动排序或填充。
- [本次与已有归档差异混合]：实施开始时核对工作区，保持 add-portfolio-total-value 的归档及主规范内容原样，不将其当成本次修改。

## Migration Plan

1. 应用开始时核对工作区并运行现有测试；当前上次验证为 66 个用例，实施时以实际结果为准。
2. 提取结果构造函数并迁移其测试，保持旧策略和导出测试有效。
3. 提取每日持仓函数、补充分支及输入保护测试，在入口接入并按表重命名局部变量。
4. 验证完整回测、日期边界、空结果、新关键字和位置调用、文档与类型，运行全套测试及 OpenSpec 严格校验。
5. 无依赖、数据或公开接口迁移；回退时恢复本次 v2 代码和测试差异即可，不移动已归档的其他变更或修改主规范。
