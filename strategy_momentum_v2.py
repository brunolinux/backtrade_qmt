import pandas as pd
import numpy as np
from portfolio_accounting import update_equity_close
from strategy_common import (getv, atr, calc_corr_matrix,
    calc_quantity, update_stop_price,
    update_trades, calc_position_size, calc_leverage_by_vol, 
    update_portfolio, update_portfolio_info)


def preprocess(df_all: dict, atr_window, short_window, long_window, vol_window):
    """
    预处理函数
    df_all: 多品种数据字典
    atr_window: ATR 指标计算窗口
    extreme_window: 历史极值数据计算窗口
    avg_window: 均值数据计算窗口
    """
    for sym, df in df_all.items():
        df = df.sort_index()
        df = df[~df.index.duplicated(keep="last")]
        
        df["atr"] = atr(df, atr_window)

        # 计算技术指标
        mom_short = df["close"].pct_change(short_window)
        mom_long = df["close"].pct_change(long_window)
        vol = df["close"].pct_change().rolling(vol_window).std()
        factor = (mom_short*0.7 + mom_long*0.3)/vol
        df["factor"] = factor
        df_all[sym] = df


def rank_factor(df_all: dict, time, col_name="factor"):
    """
    根据指定截面因子在指定时间排序
    """
    factor = {}
    for sym, df in df_all.items():
        # 当天可以交易且因子不为空
        if time in df.index and not pd.isna(df.loc[time, col_name]):
            factor[sym] = df.loc[time, col_name]
    sorted_factor = pd.Series(factor).sort_values(ascending=False)
    return sorted_factor


def update_reserve_pos(df_all: dict, pos: dict, sorted_factor, time, top_num_reserve):
    """
    更新保留仓位
    df_all: 多品种字典
    pos: 现有仓位字典
    sorted_factor: 截面排序因子
    time: 当前时刻
    top_num_reserve: 保留顶层数目
    """
    reserve_pos = {}

    # 遍历所有仓位
    for sym in pos.keys():
        df = df_all[sym]
        # 如果当天不能交易, 则保留仓位
        if time not in df.index:
            reserve_pos[sym] = pos[sym].copy()
            continue

        c = getv(df, time, "close")
        p = pos[sym]

        rank_index = sorted_factor.index.get_loc(sym)
        # 如果没有达到止盈线 或者 排序仍然靠前
        if c > p["stop"] and rank_index < top_num_reserve:
            reserve_pos[sym] = pos[sym].copy()

    return reserve_pos


def calc_buy_pos(df_all: dict, old_pos: dict, sorted_factor: pd.Series, time, 
                 equity, num_candidate, atr_stop, max_risk_per_trade):
    """
    按信号强度排序，只选择最强的几个信号
    df_all: 多品种字典
    old_pos: 现有仓位字典
    sorted_factor: 截面排序因子
    time: 当前时刻
    num_candidate: 候选品种数目
    atr_stop: 止损 atr 倍数
    max_risk_per_trade: 每笔交易的最大允许损失
    """

    pos = {}
    prev_close = {}

    for i, sym in enumerate(sorted_factor.index):
        # 超过候选数目
        if i >= num_candidate:
            break
        
        # 得分小于 0
        if sorted_factor[sym] < 0:
            break
        
        # 已经包含在已有仓位
        if sym in old_pos.keys():
            continue

        df = df_all[sym]

        px = getv(df, time, "close")
        a = getv(df, time, "atr")

        stop = px - atr_stop * a

        # 计算仓位
        qty = calc_position_size(equity, a, px, atr_stop, max_risk_per_trade)

        pos[sym] = {
            "entry": px,
            "entry_time": time,
            "stop": stop,
            "atr": a,
            "qty": qty,
            "side": 1,
        }
        prev_close[sym] = px

    return pos, prev_close


def backtest(df_all: dict, params: dict, start_date=None):
    """
    回撤
    df_all: 多品种数据字典
    params: 参数
    start_date: 起始日期
    """
    equity = float(params["init_equity"])
    pos = {}
    prev_close = {}
    trades = []
    equity_hist = []
    df_portfolio = []
    curve = []

    # 预处理
    preprocess(df_all, params["window_atr"], params["window_short"], 
               params["window_long"], params["window_vol"])
    print("预处理计算")

    timeline = sorted(set().union(*[df.index for df in df_all.values()]))

    # 如果设置起始时间, 则从指定时间开始
    if start_date:
        start_date = pd.to_datetime(start_date)

    for t in timeline:
        if start_date and t < start_date:
            continue

        # 更新盯市收益 & 收盘价信息
        equity = update_equity_close(df_all, pos, prev_close, t, equity)
        equity_hist.append(equity)
 
        # 更新仓位信息中的止损价格
        update_stop_price(df_all, pos, t, params["atr_stop"])

        # 对截面因子排序
        sorted_factor = rank_factor(df_all, t, "factor")

        # 计算保留品种
        reserve_pos = update_reserve_pos(df_all, pos, sorted_factor, t, params["top_num_reserve"])
        # 更新卖出品种
        trades.extend(update_trades(df_all, t, reserve_pos, pos))
        pos = reserve_pos

        # 计算候选品种数目
        num_add = params["hold_max_num"] - len(pos)

        # 如果有候选品种
        if num_add > 0:
            # 计算买入仓位和买入价格 (只考虑单个品种)
            cur_pos, cur_close = calc_buy_pos(df_all, pos, sorted_factor, t, equity, num_add, 
                                              params["atr_stop"], params["max_risk_per_trade"])
            pos.update(cur_pos)
            prev_close.update(cur_close)

            # 更新波动率计算杠杆率
            lev = calc_leverage_by_vol(equity_hist, 
                                       params["window_vol"],
                                       params["annual_factor"],
                                       params["target_vol"],
                                       params["min_lev"],
                                       params["max_lev"])
            real_equity = equity * lev

            # 调整仓位 (考虑整个资产组合)
            cur_pos = update_portfolio(df_all, pos, t, real_equity, params["pos_change_threshold"])
            trades.extend(update_trades(df_all, t, cur_pos, pos))
            pos = cur_pos


        # 更新每个标的的仓位信息, 如果没有买入，则为0
        cur_portfolio = update_portfolio_info(df_all, pos, t, equity)
        df_portfolio.extend(cur_portfolio)
        curve.append((t, equity))
        print("{} over!!!!".format(t))

    portfolio = pd.DataFrame(df_portfolio, columns=["datetime", "symbol", "quantity", "value"]).set_index("datetime")

    curve = pd.DataFrame(curve, columns=["datetime", "equity"]).set_index("datetime")
    trades = pd.DataFrame(trades, columns=["symbol", "side", "entry_time", "exit_time", "pnl", "exit_reason"])

    # for sym, df in df_all.items():
    #     qty = portfolio.loc[portfolio["symbol"] == sym, "quantity"]
    #     df["quantity"] = qty
    #     df.to_csv(os.path.join(os.path.dirname(__file__), "data", "tmp", "{}.csv".format(sym)))

    return portfolio, curve, trades

        
