# QMT 下单模型

`qmt_passorder.py` 用于 QMT 内置 Python 策略，不是 MiniQMT 独立进程脚本。
文件使用 GBK 编码。仅依赖 Python 标准库，交易接口由 QMT 注入。

使用前填写 `ACCOUNT_ID = "xxx"`。将脚本导入 QMT，选择实盘账户并于 09:35 前启动。
本次开发只使用模拟接口验证，未连接账户或发送真实委托。

模型运行时完全不读取外部文件。每日只需在脚本配置区更新以下常量，然后重新导入/启动：

```python
SIGNAL_DATE = dt.date(2026, 10, 16)  # 产生目标持仓的交易日
TRADE_DATE = dt.date(2026, 10, 19)   # 下一交易日，实际执行日
TARGET_QUANTITIES = {
    "159650.SZ": 400,
    "159941.SZ": 21800,
    "159981.SZ": 11800,
    "512800.SH": 118400,
}
```

`TARGET_QUANTITIES` 表示调仓后的目标持仓（份），不是本次直接下单量。
例如持有 300 份、目标 400 份，则买入 100 份；持有 600 份则卖出 200 份。
不再持有的标的可删除或填 0；空字典表示清空所有可卖持仓。不要加入现金项。

初始化会查询账户持仓、总市值、总资产和可用余额，并通过 QMT 交易日数据校验：
北京时间当天必须等于 `TRADE_DATE` 且为交易日，`SIGNAL_DATE` 必须是其前一个交易日。
日期不符、交易日数据缺失、标的后缀或数量非法均打印错误并退出。

当前常量来自 2026-10-16：159650.SZ 400 份，159941.SZ 21800 份，
159981.SZ 11800 份，512800.SH 118400 份。

- 初始化时不订阅行情数据，但设置回调函数，当执行买卖委托操作后，可以通知委托的成功以及交易是否成功，交易价格以及手续费信息
- 初始化时计算好卖出标的和卖出仓位，以及买入标的和买入仓位
- 然后开启周期为 3s 的定时器
- 定时器中获取当前时间，如果时间第一次超过 09:35:00, 则根据之前计算好的, 执行卖出操作, 卖出时按照立即成交模式卖出，不指定卖出价格。
- 如果时间第一次超过 09:36:00 则
- 程序每日会重启，不需要考虑隔日问题



接口依据：[下单枚举](https://knowledge.thinktrader.net/docs/python/enum_constants.html)、
[交易函数](https://knowledge.thinktrader.net/docs/python/trading_function.html)、
[交易日查询](https://knowledge.thinktrader.net/docs/python/data_function.html)、
[事件与定时机制](https://knowledge.thinktrader.net/docs/python/start_now.html)。

本地验证：`python -m unittest discover -s tests -v`。
