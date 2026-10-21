import pandas as pd
import numpy as np
from portfolio_accounting import calc_equity_close
from strategy_common import (
    Position, Trade, getv, atr, calc_corr_matrix, calc_quantity, calc_position_size,
    calc_leverage_by_vol, calc_stop_positions, rebalance_portfolio, calc_trade_records,
    preserve_entries_for_unchanged_quantities,
    build_portfolio_snapshot,
)


def check_correlation_constraint(sym, pos_dict: dict[str, Position], corr_matrix, threshold):
    """
    判断给定品种是否与选中品种列表存在相关性
    sym: 给定品种
    pos_dict: 选中标的代码到不可变 Position 的映射
    corr_matrix: 品种相关矩阵
    threshold: 相关系数阈值
    """
    if not pos_dict:
        return True
    
    for existing_sym, p in pos_dict.items():
        if existing_sym in corr_matrix.index and sym in corr_matrix.columns:
            corr_value = corr_matrix.loc[existing_sym, sym]
            if abs(corr_value) > threshold:
                return False
    return True


def preprocess(df_all: dict, atr_window, extreme_window, avg_window):
    """
    返回包含指标的独立行情字典，不修改输入字典或 DataFrame。
    df_all: 多品种数据字典，后复权 OHLC 用于指标，raw_close 原始价列原样保留
    atr_window: ATR 指标计算窗口
    extreme_window: 历史极值数据计算窗口
    avg_window: 均值数据计算窗口
    """
    processed_data = {}
    for sym, df in df_all.items():
        df = df.sort_index()
        df = df[~df.index.duplicated(keep="last")].copy(deep=True)
        
        # 计算技术指标
        df["atr"] = atr(df, atr_window)
        df["hh"] = df["high"].rolling(extreme_window).max().shift(1)
        df["ll"] = df["low"].rolling(extreme_window).min().shift(1)
        df["ma"] = df["close"].rolling(avg_window).mean()
    
        
        # 改进信号：增加过滤条件
        df["sig_long"] = ((df["close"] > df["hh"]) & (df["close"] > df["ma"]))
        df["sig_short"] = ((df["close"] < df["ll"]) &  (df["close"] < df["ma"]))
        
        processed_data[sym] = df

    return processed_data


def select_retained_positions(df_all: dict, pos: dict[str, Position], time) -> dict[str, Position]:
    """
    返回继续持有的新仓位字典，允许共享不可变记录，不修改输入。
    df_all: 多品种字典
    pos: Position 仓位字典，sig_take 必须为数值的复权止盈价
    time: 当前时刻
    """
    reserve_pos = {}

    for sym in list(pos.keys()):
        df = df_all[sym]
        # 如果当天不能交易, 则保留仓位
        if time not in df.index:
            reserve_pos[sym] = pos[sym]
            continue

        c = getv(df, time, "close")
        p = pos[sym]

        # 止损或者止盈
        if c <= p.sig_stop or c >= p.sig_take:
            continue
        else: # 保留仓位
            reserve_pos[sym] = pos[sym]

    return reserve_pos


def calc_buy_signals(df_all: dict, pos: dict[str, Position], corr_matrix, time, corr_threshold):
    """按后复权行情选择开仓信号，并携带同一时刻的原始价格。

    Args:
        df_all: 多标的行情字典，包含 close、raw_close、atr、ma 和 sig_long。
        pos: 当前 Position 仓位字典，用于排除已持有标的；输入只读。
        corr_matrix: 标的相关矩阵。
        time: 信号时刻。
        corr_threshold: 新标的与已有持仓相关性的阈值。

    Returns:
        list[tuple]，每项为标的、方向、强度、复权入场价、复权 ATR、原始收盘价。
        信号强度仅使用复权价格和 ATR，行情及持仓输入不变。
    """
    valid_signals = []
    for sym, df in df_all.items():
        # 如果有持仓或者时间戳不在index里，则跳出当前的循环
        if sym in pos or time not in df.index:  
            continue

        a = getv(df, time, "atr")
        px = getv(df, time, "close")
        # 确保atr和price不是infinite
        if not np.isfinite(a) or a <= 0 or not np.isfinite(px):  
            continue

        has_long = bool(getv(df, time, "sig_long"))

        # 确保has long 是 bool值
        if not has_long:  
            continue
            
        # 检查该品种和当前持有品种的相关性
        if not check_correlation_constraint(sym, pos, corr_matrix, corr_threshold):
            continue
        
        ma = getv(df, time, "ma")
        if not np.isfinite(ma):
            continue

        # 如果出现买入信号, 计算信号强度
        if has_long:
            # 把离散的信号变成了连续
            strength = (px - ma) / a  
            side = 1

        raw_close = getv(df, time, "raw_close")
        valid_signals.append((sym, side, strength, px, a, raw_close))

    return valid_signals


def calc_buy_pos(signals, time, equity, num_candidate, atr_stop, atr_take, max_risk_per_trade) -> tuple[dict[str, Position], dict[str, float]]:
    """按信号强度排序并构造带两种价格的新持仓。

    Args:
        signals: 六元素信号元组列表，依次为标的、方向、强度、复权入场价、
            复权 ATR 和同一时刻原始收盘价；输入只读。
        time: 入场时刻。
        equity: 当前账户权益。
        num_candidate: 最多选择的候选品种数。
        atr_stop: 复权止损距离的 ATR 倍数。
        atr_take: 复权止盈距离的 ATR 倍数。
        max_risk_per_trade: 单笔允许损失占权益的比例。

    Returns:
        tuple[dict[str, Position], dict[str, float]]，即新持仓和原始买入价基准。
        非正数量不开仓；两种入场价格对应 time，输入信号顺序保持不变。
    """
    # 
    sorted_signals = sorted(signals, key=lambda x: x[2], reverse=True)

    pos: dict[str, Position] = {}
    prev_close = {}

    for i, (sym, side, strength, px, a, raw_close) in enumerate(sorted_signals):
        if i >= num_candidate:
            break

        stop = px - atr_stop * a
        take = px + atr_take * a

        # 计算仓位
        qty_abs = calc_position_size(equity, a, px, raw_close, atr_stop, max_risk_per_trade)
        
        if qty_abs <= 0:
            continue

        pos[sym] = Position(
            side=side, sig_entry=px, trade_entry_time=time, sig_stop=stop, sig_take=take,
            sig_atr=a, trade_qty=qty_abs * side, trade_raw_close=raw_close)
        prev_close[sym] = raw_close

    return pos, prev_close


def backtest(df_all: dict, params: dict, start_date=None):
    """
    返回持仓、权益及交易表，不修改调用方的行情字典、DataFrame 或参数。
    df_all: 多品种行情字典，包含后复权 OHLC 和用于交易、记账的 raw_close
    params: 参数
    start_date: 起始日期
    """
    equity = float(params["init_equity"])
    pos: dict[str, Position] = {}
    prev_close = {}
    trades = []
    equity_hist = []
    df_portfolio = []
    curve = []

    # 预处理
    df_all = preprocess(df_all, params["window_atr"], params["window_extreme"],
               params["window_avg"])
    print("预处理计算")

    # ===== 计算相关性矩阵 =====
    corr_matrix = calc_corr_matrix(df_all)
    print("相关性矩阵计算")

    timeline = sorted(set().union(*[df.index for df in df_all.values()]))

    if start_date:
        start_date = pd.to_datetime(start_date)

    for t in timeline:
        if start_date and t < start_date:
            continue

        # 更新盯市收益 & 收盘价信息
        equity, prev_close = calc_equity_close(df_all, pos, prev_close, t, equity)
        equity_hist.append(equity)

        # 更新仓位信息中的止损价格
        pos = calc_stop_positions(df_all, pos, t, params["atr_drawdown"])

        for sym, p in pos.items():
            print("{} close: {:.3f} stop: {:.3f}, take: {:.3f}".format(sym, p.sig_entry, p.sig_stop, p.sig_take))

        # 更新保留仓位, 卖出部分仓位
        reserve_pos = select_retained_positions(df_all, pos, t)
        reserve_pos = preserve_entries_for_unchanged_quantities(reserve_pos, pos)
        trades.extend(calc_trade_records(df_all, t, reserve_pos, pos))
        pos = reserve_pos

        # 计算每个品种的买入信号
        signals = calc_buy_signals(df_all, pos, corr_matrix, t, params["corr_threshold"])

        # 计算候选品种数目
        num_candidate = params["hold_max_num"] - len(pos)

        # 如果有候选品种
        if num_candidate > 0:
            # 计算买入仓位和买入价格 (只考虑单个品种)
            cur_pos, cur_close = calc_buy_pos(signals, t, equity, num_candidate,
                                            params["atr_stop"], 
                                            params["atr_take"], 
                                            params["max_risk_per_trade"])
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
            cur_pos = rebalance_portfolio(df_all, pos, t, real_equity, params["pos_change_threshold"])
            cur_pos = preserve_entries_for_unchanged_quantities(cur_pos, pos)
            trades.extend(calc_trade_records(df_all, t, cur_pos, pos))
            pos = cur_pos


        # 更新每个标的的仓位信息, 如果没有买入，则为0
        cur_portfolio = build_portfolio_snapshot(df_all, pos, t, equity)
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
