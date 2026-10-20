# Tasks

## 1. 固定基线并定义持仓模型

- [x] 1.1 在实施开始时检查工作区并运行 `.venv/Scripts/python.exe -m unittest discover -s tests`，核对当前 61 个用例或新增用例的实际基线；记录两个策略的固定回测、Trade 和 CSV 预期，保留用户已有修改。
- [x] 1.2 在 strategy_common.py 定义设计中的 Position(NamedTuple)，以固定字段顺序、六个必填字段及末尾 take=None 表达契约，并补充模型说明；在公共模块测试中验证关键字构造、属性读取、默认及显式 take、字段不可赋值，以及 `_replace` 保持原记录和其他字段不变。

## 2. 迁移公共持仓计算及对应测试

- [x] 2.1 将 calc_stop_positions 和 normalize_positions 改为读取 Position 属性并通过替代记录返回新外层字典，同步持仓类型与 Google 风格注释；迁移对应输入和关键字测试，验证止损只升、停牌保留、空映射、原入场信息恢复，以及候选其他字段（尤其 take）保留，替换或增删返回字典项不影响输入。
- [x] 2.2 将 rebalance_portfolio 的复制后赋值改为替代记录，保留原计算顺序，同步类型、文档和测试；用既有手算预期验证 ATR 预算、阈值内外、预算不足裁仓、停牌及零股数过滤，确认各分支保留 take 和输入不变，不再要求内部记录对象身份不同。
- [x] 2.3 将 calc_trade_records 和 build_portfolio_snapshot 迁移为属性读取，更新类型、文档及公共、交易和关键字测试中的完整 Position 输入；验证原全量旧股数盈亏、跳过条件、Trade 字段、停牌零值及现金行预期不变，属性访问与记录替换不引入数值转换。

## 3. 迁移收盘估值入口

- [x] 3.1 将 portfolio_accounting.calc_equity_close 的持仓参数改为具名记录映射并读取 qty 属性，更新类型、文档和估值测试的完整 Position 构造；验证固定权益和完整新基准、空持仓、带符号数量、停牌、缺基准、重复日期、单次价格读取与 NaN，确认纯盯市数量映射和价格字典接口保持原样。

## 4. 迁移两个策略及调用契约

- [x] 4.1 将 strategy_momentum.py 的开仓构造、保留筛选、调试打印和所有持仓消费迁移为 Position，同步相关持仓类型及说明；迁移旧策略输入保护、交易和完整回测测试，验证原数值 take 的创建、止盈筛选及经止损、调仓、修正后保留，固定回测表与 CSV 预期不变。
- [x] 4.2 将 strategy_momentum_v2.py 的开仓构造和保留筛选迁移为 Position，同步类型及 Google 风格文档，迁移剩余新关键字与输入保护测试；验证 take=None、候选扫描含已持有标的、负因子停止、排名边界、零股数行为、返回映射隔离，以及新关键字和原位置调用的完整回测结果一致。

## 5. 核对完整迁移结果

- [x] 5.1 运行 `.venv/Scripts/python.exe -m unittest discover -s tests`、`openspec validate refactor-positions-to-namedtuple --strict` 和四个模块的独立导入检查；检查所有生产持仓构造、读取与赋值均已迁移，函数名称、参数名称及顺序、默认值、配置键、Trade、价格基准和三张输出表未被改写，类型与文档符合新记录约定，完整回测、CSV、输入保护及关键字测试全部通过。
