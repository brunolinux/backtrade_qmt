import pandas as pd
import numpy as np
from portfolio_accounting import calc_equity_close
from strategy_common import (getv, atr, calc_corr_matrix,
    calc_quantity, calc_stop_positions,
    calc_trade_records, normalize_positions, calc_position_size, calc_leverage_by_vol,
    rebalance_portfolio, build_portfolio_snapshot)


def preprocess(market_data: dict, atr_window, short_window, long_window, volatility_window):
    """整理行情并计算 ATR 和波动率调整后的动量因子。

    Args:
        market_data: 按标的代码组织的行情 DataFrame 字典，包含 high、low、
            close 数值列；输入字典及 DataFrame 只读。
        atr_window: int，ATR 滚动均值的行数窗口。
        short_window: int，短周期动量收益率的间隔行数。
        long_window: int，长周期动量收益率的间隔行数。
        volatility_window: int，单期收益率滚动标准差的行数窗口。

    Returns:
        dict，包含独立 DataFrame 的新行情字典。每张表按索引排序，重复索引
        保留最后一条，并添加 atr 和 factor 列；因子为短、长动量按 0.7、0.3
        加权后除以波动率。窗口未满的指标保留 NaN。
    """
    processed_data = {}
    for sym, df in market_data.items():
        df = df.sort_index()
        df = df[~df.index.duplicated(keep="last")].copy(deep=True)
        
        df["atr"] = atr(df, atr_window)

        # 计算技术指标
        mom_short = df["close"].pct_change(short_window)
        mom_long = df["close"].pct_change(long_window)
        vol = df["close"].pct_change().rolling(volatility_window).std()
        factor = (mom_short*0.7 + mom_long*0.3)/vol
        df["factor"] = factor
        processed_data[sym] = df

    return processed_data


def rank_factor(market_data: dict, timestamp, factor_column="factor"):
    """按指定时刻的截面因子降序排列标的。

    Args:
        market_data: 按标的代码组织的行情 DataFrame 字典，输入只读；
            当日索引应唯一，且存在指定的因子列。
        timestamp: 与行情索引兼容的排名时刻。
        factor_column: str，用于排名的因子列名，默认为 factor。

    Returns:
        pandas.Series，索引为标的代码，值为因子，按因子降序排列。
        无当日行情或当日因子为 NaN 的标的不参与排名。
    """
    factor = {}
    for sym, df in market_data.items():
        # 当天可以交易且因子不为空
        if timestamp in df.index and not pd.isna(df.loc[timestamp, factor_column]):
            factor[sym] = df.loc[timestamp, factor_column]
    sorted_factor = pd.Series(factor).sort_values(ascending=False)
    return sorted_factor


def select_retained_positions(market_data: dict, positions: dict, ranked_factors, timestamp, retention_rank_limit):
    """筛选收盘价高于止损价且排名在保留范围内的持仓。

    Args:
        market_data: 按标的代码组织的行情 DataFrame 字典，包含 close 列。
        positions: 当前持仓字典，每条记录包含 stop。
        ranked_factors: pandas.Series，按因子降序排列，索引为唯一标的代码；
            所有当日可交易的当前持仓必须出现在索引中。
        timestamp: 与行情索引兼容的筛选时刻。
        retention_rank_limit: int，保留排名的数量上限，排名从零开始且必须
            严格小于此值。

    Returns:
        dict，逐记录复制的保留持仓；当日无行情的持仓直接保留，其他持仓
        须同时满足价格和排名条件。所有输入只读。
    """
    reserve_pos = {}

    # 遍历所有仓位
    for sym in positions.keys():
        df = market_data[sym]
        # 如果当天不能交易, 则保留仓位
        if timestamp not in df.index:
            reserve_pos[sym] = positions[sym].copy()
            continue

        c = getv(df, timestamp, "close")
        p = positions[sym]

        rank_index = ranked_factors.index.get_loc(sym)
        # 如果没有达到止盈线 或者 排序仍然靠前
        if c > p["stop"] and rank_index < retention_rank_limit:
            reserve_pos[sym] = positions[sym].copy()

    return reserve_pos


def calc_buy_pos(market_data: dict, held_positions: dict, ranked_factors: pd.Series, timestamp,
                 equity, candidate_limit, stop_atr_multiple, max_trade_risk_ratio):
    """扫描排名靠前的候选标的并计算新开仓记录。

    Args:
        market_data: 按标的代码组织的行情 DataFrame 字典，包含 close 和
            atr 列；扫描标的应具有当日有效行情。
        held_positions: 已持有标的的仓位字典，用于跳过已有持仓。
        ranked_factors: pandas.Series，按因子降序排列，索引为标的代码。
        timestamp: 与行情索引兼容的开仓时刻。
        equity: float，账户总权益，用于计算单笔风险预算和持仓金额上限。
        candidate_limit: int，最多扫描的排名项数；已有持仓也占用扫描名额。
        stop_atr_multiple: float，止损距离相对当日 ATR 的倍数。
        max_trade_risk_ratio: float，单笔允许损失占权益的比例，如 0.02。

    Returns:
        tuple[dict, dict]，即 (positions, prev_close)，分别为新开仓记录和
        对应每股买入价基准。遇到负因子立即停止扫描，已有持仓跳过；
        不过滤计算所得的零股数记录。所有输入只读。
    """

    pos = {}
    prev_close = {}

    for i, sym in enumerate(ranked_factors.index):
        # 超过候选数目
        if i >= candidate_limit:
            break
        
        # 得分小于 0
        if ranked_factors[sym] < 0:
            break
        
        # 已经包含在已有仓位
        if sym in held_positions.keys():
            continue

        df = market_data[sym]

        px = getv(df, timestamp, "close")
        a = getv(df, timestamp, "atr")

        stop = px - stop_atr_multiple * a

        # 计算仓位
        qty = calc_position_size(equity, a, px, stop_atr_multiple, max_trade_risk_ratio)

        pos[sym] = {
            "entry": px,
            "entry_time": timestamp,
            "stop": stop,
            "atr": a,
            "qty": qty,
            "side": 1,
        }
        prev_close[sym] = px

    return pos, prev_close


def backtest(market_data: dict, params: dict, start_date=None):
    """执行动量策略回测并返回持仓、权益曲线和交易表。

    Args:
        market_data: 按标的代码组织的行情 DataFrame 字典，包含 high、low、
            close 列，索引为日期；输入字典及 DataFrame 只读。
        params: 只读配置字典，必需键为 init_equity、window_atr、window_short、
            window_long、window_vol、atr_stop、top_num_reserve、hold_max_num、
            max_risk_per_trade、annual_factor、target_vol、min_lev、max_lev 和
            pos_change_threshold。风险及波动率比例用小数表示，如 0.02 为 2%。
        start_date: pandas 可解析的起始日期，包含该日；默认为 None，
            表示遍历全部行情日期。指标预处理仍使用完整行情历史。

    Returns:
        tuple[pandas.DataFrame, pandas.DataFrame, pandas.DataFrame]，依次为：
            portfolio: 以 datetime 为索引，列为 symbol、quantity、value，
                每日包含各标的及 cash 行。
            curve: 以 datetime 为索引，equity 列为每日总权益。
            trades: 默认整数索引，列为 symbol、side、entry_time、exit_time、
                pnl、exit_reason，记录退出和切换仓位的交易。
    """
    equity = float(params["init_equity"])
    pos = {}
    prev_close = {}
    trades = []
    equity_hist = []
    df_portfolio = []
    curve = []

    # 预处理
    market_data = preprocess(market_data, params["window_atr"], params["window_short"],
               params["window_long"], params["window_vol"])
    print("预处理计算")

    timeline = sorted(set().union(*[df.index for df in market_data.values()]))

    # 如果设置起始时间, 则从指定时间开始
    if start_date:
        start_date = pd.to_datetime(start_date)

    for t in timeline:
        if start_date and t < start_date:
            continue

        # 更新盯市收益 & 收盘价信息
        equity, prev_close = calc_equity_close(market_data, pos, prev_close, t, equity)
        equity_hist.append(equity)
 
        # 更新仓位信息中的止损价格
        pos = calc_stop_positions(market_data, pos, t, params["atr_stop"])

        # 对截面因子排序
        sorted_factor = rank_factor(market_data, t, "factor")

        # 计算保留品种
        reserve_pos = select_retained_positions(market_data, pos, sorted_factor, t, params["top_num_reserve"])
        # 更新卖出品种
        reserve_pos = normalize_positions(reserve_pos, pos)
        trades.extend(calc_trade_records(market_data, t, reserve_pos, pos))
        pos = reserve_pos

        # 计算候选品种数目
        num_add = params["hold_max_num"] - len(pos)

        # 如果有候选品种
        if num_add > 0:
            # 计算买入仓位和买入价格 (只考虑单个品种)
            cur_pos, cur_close = calc_buy_pos(market_data, pos, sorted_factor, t, equity, num_add,
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
            cur_pos = rebalance_portfolio(market_data, pos, t, real_equity, params["pos_change_threshold"])
            cur_pos = normalize_positions(cur_pos, pos)
            trades.extend(calc_trade_records(market_data, t, cur_pos, pos))
            pos = cur_pos


        # 更新每个标的的仓位信息, 如果没有买入，则为0
        cur_portfolio = build_portfolio_snapshot(market_data, pos, t, equity)
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

        
