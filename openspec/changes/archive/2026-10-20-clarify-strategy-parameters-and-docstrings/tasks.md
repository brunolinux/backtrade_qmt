# Tasks

## 1. 核对现有接口与行为基线

- [x] 1.1 运行 `.venv/Scripts/python.exe -m unittest discover -s tests`，以设计中的 19 个目标函数核对当前签名、默认值、配置和持仓字符串字段及实际关键字调用；验证现有完整回测、Trade、CSV 和输入保护案例通过，记录实施开始时的用户修改以便保留。

## 2. 明确公共工具模块的形参与文档

- [x] 2.1 按设计迁移 getv、calc_quantity、atr、calc_corr_matrix、calc_position_size 和 calc_leverage_by_vol 的形参及对应引用，补齐中文 Google 风格 Args/Returns 和实际边界说明，同步必要调用；用新关键字执行行情读取、交易单位取整、风险仓位及年化杠杆的固定数值案例，验证默认值、位置调用和 NaN、暖启动行为不变。
- [x] 2.2 按设计迁移 calc_stop_positions、rebalance_portfolio、normalize_positions、calc_trade_records 和 build_portfolio_snapshot 的形参及 docstring，明确候选/当前持仓、配置预算和相对股数阈值；用新关键字验证止损、预算调仓、未改股数的入场修正及交易记录，并确认固定结果、Trade 字段和输入保护案例通过。

## 3. 明确记账模块的调用契约

- [x] 3.1 迁移 calc_equity_close 的 market_data、positions、timestamp 形参，保持另外两个记账函数名称及形参名，统一三个函数的 Google 风格 docstring 和返回元组说明；用新关键字执行估值，验证权益与完整下一基准、缺基准、停牌保留值、重复日期、单次价格读取和 NaN 行为，与原位置调用的独立预期值一致。

## 4. 明确 v2 策略的形参与文档

- [x] 4.1 按设计迁移 preprocess、rank_factor 的形参及引用，说明行情必需列、窗口、因子列和降序输出；以新关键字验证预处理及自定义 factor_column 的排名，覆盖缺行情和 NaN 因子，确认默认 factor 列及输入隔离规则不变。
- [x] 4.2 按设计迁移 select_retained_positions 和 calc_buy_pos 的形参及 docstring，明确 ranked_factors、held_positions、retention_rank_limit 和 candidate_limit；用新关键字及固定排名案例验证已有持仓消耗候选扫描范围、负因子停止扫描和保留排名边界，保持原算法、返回元组及输入不变。
- [x] 4.3 将 v2 backtest 的 df_all 改为 market_data，保留 params、start_date 和原配置键，补充 Google 风格参数及三张返回表结构说明；同步仓库内实际受影响的关键字调用，用新关键字执行完整回测并与固定预期表比较，确认旧策略仍可按原位置调用公共函数，无需全面修改旧策略签名和注释。

## 5. 核对文档和完整迁移结果

- [x] 5.1 一次性检查全部 19 个函数的首行摘要、Args 参数覆盖、Returns 结构和签名一致性，人工复核每股价格、风险比例、年化波动率、配置预算、候选扫描及 getv 异常回退说明；确认没有为未实现的校验添加承诺，不新增长期固定文案测试或文档工具依赖。
- [x] 5.2 运行 `.venv/Scripts/python.exe -m unittest discover -s tests`、`openspec validate clarify-strategy-parameters-and-docstrings --strict` 及模块独立导入检查；核对函数名称、参数顺序、默认值、配置键、持仓字段及计算语句的差异，确认仅发生设计内的名称和文档调整，完整回测、CSV、输入保护及新关键字调用测试全部通过。
