# Design

## Context

动机和范围见 `proposal.md`。当前三个目标文件包含 19 个自定义函数：公共模块 11 个、记账模块 3 个、v2 策略 5 个。`calc_quantity` 无 docstring，其余注释混用简略摘要、裸参数列表和段落说明。现有主规范已经要求输入不变、显式返回状态和回测数值兼容，本次只增加调用语义和文档要求。

仓库不存在 `portfolio_account.py`，本次指 `portfolio_accounting.py`。相关策略入口及测试中的调用主要使用位置参数；已发现的 `backtest(..., start_date=...)` 保留名称，两个估值测试转发 `**kwargs`。公共函数被旧策略导入，因此修改后仍需验证两个策略。工作区目前干净。

Google 风格依据：[Google Python Style Guide，3.8.3 Functions and Methods](https://google.github.io/styleguide/pyguide.html#383-functions-and-methods)。本次只采用函数 docstring 结构，不将范围扩大到导入方式、代码格式、类型注解或其他风格规则。

## Goals / Non-Goals

**Goals:**

- 从签名区分行情、持仓角色、时刻、每股价格、交易单位、预算和风险比例。
- 让中文 docstring 的 Args 与实际签名一致，Returns 足以指导调用者接收结果。
- 新关键字调用得到可手算的预期值，原位置调用和已有默认值保持兼容，数值结果及输入保护不变。

**Non-Goals:**

- 不修改函数名称、参数位置、默认值、返回值结构、配置键、行情列或持仓字段，不提供旧关键字兼容别名。
- 不给输入增加新校验，不纠正候选扫描、调仓、盈亏或无行情展示算法。
- 不全面重写局部变量或旧策略注释；仅在避免形参重命名冲突或保持说明一致时调整相关局部名称。
- 不扩展 Trade 类注释范围，不引入新的类型体系、文档依赖、格式化工具或持久化的纯文档测试。

## Decisions

### 1. 采用明确的逐函数形参映射

下表列出最终形参顺序。只替换名称，现有默认值和类型注解随对应参数保留；函数名称不变。

| 模块及函数 | 目标形参列表 |
| --- | --- |
| 公共 `getv` | `dataframe, index_label, column` |
| 公共 `calc_quantity` | `quantity, lot_size` |
| 公共 `atr` | `price_data, window` |
| 公共 `calc_corr_matrix` | `market_data, price_column` |
| 公共 `calc_position_size` | `equity, atr_value, price, stop_atr_multiple, max_trade_risk_ratio` |
| 公共 `calc_leverage_by_vol` | `equity_history, volatility_window, periods_per_year, target_annual_volatility, min_leverage, max_leverage` |
| 公共 `calc_stop_positions` | `market_data, positions, timestamp, stop_atr_multiple` |
| 公共 `rebalance_portfolio` | `market_data, positions, timestamp, allocation_budget, quantity_change_threshold_ratio` |
| 公共 `normalize_positions` | `candidate_positions, current_positions` |
| 公共 `calc_trade_records` | `market_data, timestamp, candidate_positions, current_positions` |
| 公共 `build_portfolio_snapshot` | `market_data, positions, timestamp, equity` |
| 记账 `calc_mark_to_market_equity` | `quantities, current_close, prev_close, prev_equity`，名称保持不变 |
| 记账 `build_close_marks` | `current_close, prev_close`，名称保持不变 |
| 记账 `calc_equity_close` | `market_data, positions, prev_close, timestamp, prev_equity` |
| v2 `preprocess` | `market_data, atr_window, short_window, long_window, volatility_window` |
| v2 `rank_factor` | `market_data, timestamp, factor_column` |
| v2 `select_retained_positions` | `market_data, positions, ranked_factors, timestamp, retention_rank_limit` |
| v2 `calc_buy_pos` | `market_data, held_positions, ranked_factors, timestamp, equity, candidate_limit, stop_atr_multiple, max_trade_risk_ratio` |
| v2 `backtest` | `market_data, params, start_date` |

`getv` 支持任意兼容的索引标签，使用 index_label，避免将其误限制为时间戳。其他 timestamp 表示与行情索引兼容的当前计算时刻，不增加强制类型校验。

`candidate_positions` 和 `current_positions` 表示转换前后角色，不代表昨天和今天；v2 的 `held_positions` 专指排除重复买入的现有持仓。`allocation_budget` 是总权益乘杠杆后的配置资金，并非另一个账户权益值。`quantity_change_threshold_ratio` 是相对当前股数的调仓阈值，与现有 `pos_change_threshold` 配置键对应。

`candidate_limit` 限制扫描排名的数量，扫描到已持有标的也消耗该范围，不保证生成相同数量的新增持仓。`retention_rank_limit` 是允许保留的排名范围，不是目标持仓数。采用明确角色和单位，优于只把缩写展开成仍然含混的词。

### 2. 在词法作用域内重命名，保持数据协议

同步修改每个函数中的形参引用、需要的局部引用，以及实际存在的关键字调用，避免全文替换字符串。尤其不得改写 `params['atr_stop']`、`params['max_risk_per_trade']`、`params['window_vol']`、`params['pos_change_threshold']`、持仓的 qty/entry/stop 等字段或表格列名。

v2 backtest 接收新 market_data，但仍用原 params 键向公共函数传值。旧策略只在存在旧关键字调用时迁移该调用；其自定义函数签名和注释不在本次 19 个目标函数之内。函数导入名称、模块依赖和 Trade 类型均不变。

新名称是唯一支持的关键字参数，旧关键字不保留 **kwargs 兼容分支。位置调用不受影响。该选择减少双重名字维护成本，但外部调用者需按映射迁移，已在 proposal 标记 BREAKING。

### 3. 统一 Google 风格的中文函数 docstring

对全部 19 个函数使用三双引号、首行简洁摘要、摘要后空行及中文说明；多行 Args/Returns 的说明采用一致的四空格悬挂缩进。Args 使用最终形参名；类型注解不足以表达类型时，在描述中补充。Returns 说明返回类型、结构及含义，返回元组时先说明这是一个元组，再解释各元素；不把元组误写成多个独立返回值。

该批公共接口统一写 Args 和 Returns，便于审阅。Raises 仅在实现存在调用者需要处理的接口异常时使用；对违反文档前提才触发的 KeyError、ZeroDivisionError 等不机械列举，不增加运行时校验。getv 的读取和转换失败被捕获返回 NaN，不写对应 Raises。

说明调用者需要知道的输入只读、返回副本、必需行情列或持仓字段，以及已有边界行为。内部循环和临时变量的细节仍留在代码行注释，不堆入 docstring。

### 4. 按模块明确需要纠正和补充的语义

| 模块 | 文档重点 |
| --- | --- |
| `strategy_common.py` | 补充 getv 的重复日期与 NaN 行为、calc_quantity 向零截断的交易单位取整、ATR 窗口及首段 NaN、相关矩阵使用对数收益率、仓位风险比例与每股价格、年化杠杆暖启动、持仓修正和既有交易记录口径 |
| `portfolio_accounting.py` | 新旧价格基准含义、完整字典保留停牌及残留键、缺基准回退、同一份价格快照、权益元组与输入保护 |
| `strategy_momentum_v2.py` | high/low/close 与指标列的依赖、排名 Series 降序约定、保留排名边界、候选扫描而非新增数量承诺、必需配置键及三张返回表 |

所有风险比例以小数形式解释，例如 0.02 表示 2%；ATR 倍数与价格值分开说明。不要将权益误称为持仓市值，也不要将每股价格写成每手价格。backtest 文档列出其实际读取的配置键，保留代码中的现有键名，并描述返回表索引及列，而非新增配置机制。

### 5. 通过真实关键字调用和现有回归验证

现有 tests 中的固定数值、完整回测和输入保护案例继续保留。新增必要的真实调用用例，使用新关键字执行数量、风险仓位、预算调仓、候选修正、估值、因子列选择及 v2 候选扫描，断言独立预期值和输入不变；这些测试保护外部可调用接口，不以仅反射签名代替真实执行。

位置调用和默认参数沿用现有案例，并补齐受改名影响的必要默认值用例；不为每个形参写一条重复的镜像测试。一次性检查全部 19 个 docstring 的参数覆盖、摘要、Args/Returns 和签名一致性，人工复核单位及边界语义；不引入只检查固定文案的长期测试。

可在实施前后对签名默认值及去除 docstring、按作用域统一变量名后的 AST 进行对照，辅助确认仅参数和文档变更，字面配置键及计算语句不变；不以 AST 检查替代真实数值回归。

## Risks / Trade-offs

- [外部旧关键字失效]：提供最终逐函数映射，明确 BREAKING，同步仓库内调用，不引入旧名兼容层。
- [机械替换改变配置或持仓字段]：限定词法作用域，检查字符串键及默认值，并运行已有回测和输入保护测试。
- [文档承诺与实际算法不一致]：依据现存实现描述 candidate_limit、NaN、暖启动和全量持仓盈亏口径，不顺带修正算法。
- [文档过长或重复类型信息]：摘要只表达职责，Args/Returns 保留调用所需信息，避免解释循环实现或重复已有充分类型注解。
- [过度扩大旧策略改造范围]：旧策略仅更新实际受影响的关键字调用，其自定义签名和文档保持不变。

## Migration Plan

1. 在实施开始时检查工作区及现有测试，固定默认值、配置字段、数值结果和输入保护基线。
2. 按三个模块分组迁移形参及 docstring，同步必要调用和关键字行为测试，保持每组验证通过。
3. 检查 19 个函数的文档完整性、作用域重命名与字符串字段保护，运行 `.venv/Scripts/python.exe -m unittest discover -s tests`、模块导入检查及 OpenSpec 严格校验。
4. 无数据迁移或依赖安装。如需回退，按本次独立差异恢复签名及相应调用，不修改主规范既有内容或历史归档。
