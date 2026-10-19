参考 https://dict.thinktrader.net/innerApi/start_now.html?id=dqamF2#%E5%AE%9E%E7%9B%98%E7%A4%BA%E4%BE%8B-%E5%9F%BA%E4%BA%8E-subscribe 网址中里的例子，代码为： 
```python
#coding:gbk

class a():pass
A = a()
A.bought_list = []

account = 'testaccount'
def init(C):
	#下单函数的参数需要 ContextInfo对象 在init中定义行情回调函数 可以用到init函数的入参 不用手动传入 
	def callback_func(data):
		#print(data)
		for stock in data:
			current_price = data[stock]['close']
			pre_price = data[stock]['preClose']
			ratio = current_price / pre_price - 1
			print(stock, C.get_stock_name(stock), '当前涨幅', ratio)
			if ratio > 0 and stock not in A.bought_list:
				msg = f"当前涨幅 {ratio} 大于0 买入100股"
				print(msg)
				#下单函数passorder 安全起见处于注释状态 需要实际测试下单交易时再放开
				#passorder(23, 1101, account, stock, 5, -1, 100, '订阅下单示例', 2, msg, C)
				A.bought_list.append(stock)
	stock_list = ['600000.SH', '000001.SZ']
	for stock in stock_list:
		C.subscribe_quote(stock, period = '1d', callback = callback_func)

```

以及 qmt 手册的下单说明，对应接口说明在 https://dict.thinktrader.net/innerApi/trading_function.html?id=dqamF2#passorder-%E7%BB%BC%E5%90%88%E4%B8%8B%E5%8D%95%E5%87%BD%E6%95%B0
使用示例如下：

```python
passorder(
    opType, orderType, accountid
    , orderCode, prType, price, volume
    , strategyName, quickTrade, userOrderId
    , ContextInfo
)
'''
passorder(
    2 #opType 操作号
    , 1101 #orderType 组合方式
    , '1000044' #accountid 资金账号
    , 'cu2403.SF' #orderCode 品种代码
    , 14 #prType 报价类型
    , 0.0 #price 价格
    , 2 #volume 下单量
    , '示例下单' #strategyName 策略名称
    , 1 #quickTrade 快速下单标记
    , '投资备注' #userOrderId 投资备注
    , C #ContextInfo 策略上下文
)
'''

```

要求：

1. 在文件中新增 qmt_passorder.py 文件，实现 qmt 下单模型，要求使用事件驱动模型，刷新间隔为 3秒钟，init() 函数中读取当前账户的仓位和总市值，你需要读取文件夹 data/output_v2/portfolio_qty.csv 文件的最后一行，并据此在代码中写对应的常量购买标的和对应仓位，
2. 注意标的名称在 csv 和 qmt 的差别，后者需要 .xx 后缀，xx 表示交易所，请根据 etf 所在交易所自行补齐，参考 https://dict.thinktrader.net/innerApi/variable_convention.html?id=dqamF2#symbol-code-%E4%BB%A3%E7%A0%81%E8%A1%A8%E7%A4%BA
3. 注意确认文件最后一行的交易日是当前天的前一个交易日，如果不是，则打印错误，并直接退出
4. 9点35卖出超额持仓或者清空该标的，以确保账户有足够余额，9点36执行买入
5. passorder 的 opType 为 23 或者 24，前者表示买入，后者为卖出，orderType 为 1101，表示单股、单账号、普通、股/手方式下单，accountID 为 "xxx", 留给我来填，orderCode 填标的信息，需要后缀信息，prType 我希望是立即成交，请自行参考 https://dict.thinktrader.net/innerApi/enum_constants.html?id=dqamF2#prtype-%E4%B8%8B%E5%8D%95%E9%80%89%E4%BB%B7%E7%B1%BB%E5%9E%8B, price 为 -1, volume 是下单数量, 表示份数目，quicktrade 为 1

