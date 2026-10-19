from factor.config_etf import getETFFundsInfo
from factor.util import getFundsDataDict, CodeType
# from momentum_v3 import backtest
from strategy_momentum_v2 import backtest
import os
import pandas as pd

if __name__ == "__main__":
    funds_info = getETFFundsInfo()    
    df_all = getFundsDataDict(funds_info, CodeType.ETF)

    # # ETF
    params = {
        "init_equity": 18_5000,         # 初始市值
        "window_atr": 40,               # ATR 窗口
        "window_short": 20,             # 短周期
        "window_long": 40,              # 长周期
        "window_vol": 40,               # 波动率窗口
        "atr_stop": 3,                  # 止损 atr 倍数

        "top_num_reserve": 8,
        "hold_max_num": 5,              # 持有品种最大数目
        "max_risk_per_trade": 0.02,     # 单笔交易最大损失: 2%
        "annual_factor": 252,           # 日线, 252 个交易日
        "target_vol": 0.3,              # 目标年化波动率 30%
        "min_lev": 0.3,                 
        "max_lev": 1.0,
        "pos_change_threshold": 0.2     # 仓位至少变更 20% 才调仓
    }

    portfolio, curve, trades = backtest(df_all, params, start_date="2026-01-01")

    symbols = funds_info["name"].to_dict()
    symbols["cash"] = "现金"

    sub_dir = os.path.join(os.path.dirname(__file__), "data", "output_v2")

    trades = pd.concat([trades["symbol"].map(symbols), trades], axis=1)
    trades.to_csv(f"{sub_dir}/trade.csv", encoding="GB2312", index=False)

    portfolio_val = portfolio.pivot(columns="symbol", values="value")
    # 总资产价值：所有标的市值与现金之和
    portfolio_val["total_value"] = portfolio_val.sum(axis=1)
    # portfolio_val = portfolio_val.rename(columns=symbols)
    portfolio_val.to_csv(f"{sub_dir}/portfolio_value.csv", encoding="GB2312")
    portfolio_qty = portfolio.pivot(columns="symbol", values="quantity")
    # portfolio_qty = portfolio_qty.rename(columns=symbols)
    portfolio_qty.to_csv(f"{sub_dir}/portfolio_qty.csv", encoding="GB2312")


    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 1)
    curve.plot(ax=ax)

    # for sym, df in df_all.items():
    #     fig, ax = plt.subplots(1, 1)
    #     df.close.plot(ax=ax)

    #     val = portfolio_qty[sym] * df.close.max() / portfolio_qty[sym].max() 
    #     val.plot(ax=ax)

    #     ax.set_title(sym)

    plt.show()



        
