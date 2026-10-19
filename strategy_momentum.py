import pandas as pd
import numpy as np


def getv(df, t, col):
    """改进的值获取函数"""
    try:
        v = df.loc[t, col]
        if isinstance(v, pd.Series):
            return float(v.iloc[-1])
        return float(v)
    except:
        return np.nan
    

def calc_quantity(quantity, min_num):
    return int(quantity / min_num) * min_num


def atr(df_single, window=10):
    """改进的ATR计算
    df_single: 单品种数据
    window: 滚动窗口
    """
    # talib conda
    high_low = df_single["high"] - df_single["low"]
    high_close = (df_single["high"] - df_single["close"].shift()).abs()
    low_close = (df_single["low"] - df_single["close"].shift()).abs()
    
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    # 使用rolling mean替代EMA，更稳定
    return tr.rolling(window).mean()


def calc_corr_matrix(df_all: dict, name: str = "close") -> pd.DataFrame:
    """
    计算互相关矩阵
    df_all: 多品种数据字典
    name: 计算互相关的列名
    """
    rets = {}

    for sym, df in df_all.items():
        if name not in df.columns:
            continue

        s = df[name].sort_index()
        ret = np.log(s).diff()
        rets[sym] = ret

    ret_df = pd.DataFrame(rets)
    ret_df = ret_df.dropna(how="all")
    corr = ret_df.corr()
    return corr


def check_correlation_constraint(sym, pos_dict: dict, corr_matrix, threshold):
    """
    判断给定品种是否与选中品种列表存在相关性
    sym: 给定品种
    pos_dict: 选中品种以及品种仓位
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


def calc_position_size(equity, atr_value, px, atr_stop, max_risk_per_trade):
    """
    改进的仓位计算：基于风险的仓位管理
    equity: 当前市值
    atr_value: 品种的 atr 数值
    px: 品种每手价格
    atr_stop: 止损 atr 倍率 (参数)
    max_risk_per_trade: 每笔交易的最大损失 (百分比)
    """
    # 该品种每手最大可能损失
    risk_per_share = atr_value * atr_stop
    if risk_per_share <= 0:
        return 0
    
    # 每笔交易的最大允许损失
    risk_amount = equity * max_risk_per_trade  
    shares = calc_quantity(risk_amount/risk_per_share, 100)
    
    # 确保仓位不超过市值
    notional = shares * px
    if notional > equity:
        shares = calc_quantity(equity / px, 100)
    
    return shares


def preprocess(df_all: dict, atr_window, extreme_window, avg_window):
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
        
        # 计算技术指标
        df["atr"] = atr(df, atr_window)
        df["hh"] = df["high"].rolling(extreme_window).max().shift(1)
        df["ll"] = df["low"].rolling(extreme_window).min().shift(1)
        df["ma"] = df["close"].rolling(avg_window).mean()
    
        
        # 改进信号：增加过滤条件
        df["sig_long"] = ((df["close"] > df["hh"]) & (df["close"] > df["ma"]))
        df["sig_short"] = ((df["close"] < df["ll"]) &  (df["close"] < df["ma"]))
        
        df_all[sym] = df


def update_equity_close(df_all: dict, pos: dict, prev_close: dict, time, prev_equity):
    """
    df_all: 多品种字典
    pos: 仓位字典
    prev_close: 前一天的收盘价 
    time: 当前时刻
    equity: 前一天市值
    """
    equity = prev_equity
    for sym, p in list(pos.items()):
        df = df_all[sym]
        if time in df.index:
            c = getv(df, time, "close")
            pc = prev_close.get(sym, c)
            equity += p["qty"] * (c - pc)
            prev_close[sym] = c

    return equity


def update_stop_price(df_all: dict, pos: dict, time, atr_stop):
    """
    动态移动止损：价格上升时提高止损
    df_all: 多品种字典
    pos: 仓位字典 (会更新)
    time: 当前时刻
    atr_stop: 回撤倍数
    """
    for sym, p in pos.items():
        df = df_all[sym]
        if time not in df.index:
            continue

        c = getv(df, time, "close")
        new_stop = c - atr_stop * p["atr"]
        p["stop"] = max(p["stop"], new_stop)


def update_reserve_pos(df_all: dict, pos: dict, time):
    """
    判断每个品种的价格是否超过阈值, 否则保留
    df_all: 多品种字典
    pos: 仓位字典
    time: 当前时刻
    """
    reserve_pos = {}

    for sym in list(pos.keys()):
        df = df_all[sym]
        # 如果当天不能交易, 则保留仓位
        if time not in df.index:
            reserve_pos[sym] = pos[sym].copy()
            continue

        c = getv(df, time, "close")
        p = pos[sym]

        # 止损或者止盈
        if c <= p["stop"] or c >= p["take"]:  
            continue
        else: # 保留仓位
            reserve_pos[sym] = pos[sym].copy()

    return reserve_pos


def calc_buy_signals(df_all: dict, pos: dict, corr_matrix, time, corr_threshold):
    """
    更新开仓信号
    df_all: 多品种字典
    pos: 仓位字典
    corr_matrix: 品种相关矩阵
    time: 当前时刻
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

        valid_signals.append((sym, side, strength, px, a))

    return valid_signals


def calc_buy_pos(signals, time, equity, num_candidate, atr_stop, atr_take, max_risk_per_trade):
    """
    按信号强度排序，只选择最强的几个信号
    signals: 信号
    time: 当前时刻
    equity: 当前市值
    num_candidate: 候选品种数目
    atr_stop: 止损 atr 倍数
    atr_take: 止盈 atr 倍数
    max_risk_per_trade: 每笔交易的最大允许损失
    """
    # 
    signals.sort(key=lambda x: x[2], reverse=True)

    pos = {}
    prev_close = {}

    for i, (sym, side, strength, px, a) in enumerate(signals):
        if i >= num_candidate:
            break

        stop = px - atr_stop * a
        take = px + atr_take * a

        # 计算仓位
        qty_abs = calc_position_size(equity, a, px, atr_stop, max_risk_per_trade)
        
        if qty_abs <= 0:
            continue

        pos[sym] = {
            "side": side,
            "entry": px,
            "entry_time": time,
            "stop": stop,
            "take": take,
            "atr": a,
            "qty": qty_abs * side
        }
        prev_close[sym] = px

    return pos, prev_close


def calc_leverage_by_vol(equity_hist, window_vol, annual_factor, target_vol, min_lev, max_lev):
    """
    根据波动率调整杠杆率
    equity_hist: 市值曲线
    window_vol: 计算波动率的窗口长度
    annual_factor: 一年的 bar 数目 (如果是日线, 则为 252)
    target_vol: 目标年化波动率
    min_lev: 最低杠杆率
    max_lev: 最大杠杆率
    """
    if len(equity_hist) < window_vol:
        return 1.0
    
    eq = np.array(equity_hist[-window_vol:])
    ret = np.diff(np.log(eq))
    
    realized_vol = np.std(ret) * np.sqrt(annual_factor)

    vol_scale = target_vol / (realized_vol + 1e-6)
    vol_scale = np.clip(vol_scale, min_lev, max_lev)
    return vol_scale


def update_portfolio(df_all: dict, pos: dict, time, real_equity, pos_change_threshold):
    """
    调整仓位
    df_all: 多品种字典
    pos: 仓位字典 (更新)
    time: 当前时刻
    real_equity: 实际市值
    pos_change_threshold: 仓位变更阈值 
    """
    if len(pos) == 0:
        return {}
    
    total_risk = sum(1.0 / p["atr"] for p in pos.values())

    # 在新的仓位上管理
    new_pos = {}
    for sym, p in pos.items():
        new_pos[sym] = p.copy()
        df = df_all[sym]
        if time not in df.index:
            # 如果当天不能交易, 仓位不变
            continue

        px = getv(df, time, "close")

        risk_weight = (1.0/p["atr"])/total_risk
        target_notional = real_equity * risk_weight
        target_qty = calc_quantity(target_notional/px, 100)
        
        # 平滑调整仓位，避免频繁调仓
        cur_qty = abs(p["qty"])
        if abs(target_qty - cur_qty) > cur_qty*pos_change_threshold:
            new_pos[sym]["qty"] = target_qty * p["side"]
        # 更新时间
        new_pos[sym]["entry_time"] = time
        new_pos[sym]["entry"] = px
    
    # 获取股票总仓位 (只考虑可以交易的)
    unchanged_money = 0
    unchanged_sym_list = []
    money_list = []
    sym_list = []
    for sym, p in new_pos.items():
        df = df_all[sym]
        if time not in df.index:
            # 如果当天不能交易, 仓位不变
            unchanged_money += p["qty"] * p["entry"]
            unchanged_sym_list.append(sym)
        else:
            money_list.append(p["qty"] * p["entry"])
            sym_list.append(sym)

    money_list = np.array(money_list)

    # 如果现金不够, 则优先选择权重大的
    cash = real_equity - np.sum(money_list) - unchanged_money
    if cash < 0:
        count = 0
        new_new_pos = {}
        # 无法交易的直接拷贝过来
        for sym in unchanged_sym_list:
            new_new_pos[sym] = new_pos[sym].copy()

        # 只考虑可以交易的
        idx_list = np.argsort(money_list)[::-1]
        for idx in idx_list:
            count += money_list[idx]
            sym = sym_list[idx]
            new_new_pos[sym] = new_pos[sym].copy()
            if count > real_equity:
                left = real_equity - (count - money_list[idx])
                px = new_pos[sym]["entry"]
                qty = calc_quantity(left/px, 100)
                new_new_pos[sym]["qty"] = qty
                break
    
        new_pos = new_new_pos.copy()

    # 去除仓位为 0 的标的
    out_pos = {}
    for sym, p in new_pos.items():
        if p["qty"] != 0:
            out_pos[sym] = p.copy()
    return out_pos


def update_trades(df_all:dict, time, new_pos: dict, old_pos: dict):
    """
    根据仓位调整新增交易信息
    """
    trades = []
    old_sym = set(old_pos.keys())
    new_sym = set(new_pos.keys())

    common_sym = new_sym.intersection(old_sym)
    close_sym = old_sym.difference(new_sym)

    # 关闭仓位
    for sym in close_sym:
        p = old_pos[sym]
        # 如果时间相同, 则不用交易
        if p["entry_time"] == time:
            continue

        # 如果仓位为 0, 则不用交易
        if p["qty"] == 0:
            continue

        df = df_all[sym]
        px = getv(df, time, "close")
        pnl = p["qty"] * (px - p["entry"])
        reason = "止盈" if pnl > 0 else "止损"
        trade_info = (
            sym,                # 品种
            p["side"],          # 
            p["entry_time"],    # 买入时刻
            time,               # 卖出时刻
            float(pnl),         # 交易收益
            reason              # 卖出原因
        )
        trades.append(trade_info)

    # 切换仓位
    for sym in common_sym:
        # 如果时间相同， 则跳过
        if new_pos[sym]["entry_time"] == old_pos[sym]["entry_time"]:
            continue

        # 如果仓位相同，则更新新的时间为老的时间
        if new_pos[sym]["qty"] == old_pos[sym]["qty"]:
            new_pos[sym]["entry_time"] = old_pos[sym]["entry_time"]
            new_pos[sym]["entry"] = old_pos[sym]["entry"]
            continue

        if old_pos[sym]["qty"] == 0:
            continue

        df = df_all[sym]
        px = getv(df, time, "close")
        p = old_pos[sym]
        pnl = p["qty"] * (px - p["entry"])
        trade_info = (
            sym,                # 品种
            p["side"],          # 
            p["entry_time"],    # 买入时刻
            time,               # 卖出时刻
            float(pnl),         # 交易收益
            "切换仓位"           # 卖出原因
        )
        trades.append(trade_info)

    return trades


def update_portfolio_info(df_all: dict, pos: dict, time, equity):
    """
    更新仓位信息

    """
    cur_port = []

    for sym, df in df_all.items():
        if time not in df.index:
            cur_port.append((time, sym, 0, 0))
            continue

        if sym not in pos.keys():
            cur_port.append((time, sym, 0, 0))
            continue

        px = getv(df, time, "close")  # pos[sym]["entry"]  # 
        qty = pos[sym]["qty"]
        
        value = px * qty
        cur_port.append((time, sym, qty, value))
        equity -= value

    cur_port.append((time, "cash", equity, equity))
    return cur_port



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
    preprocess(df_all, params["window_atr"], params["window_extreme"], 
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
        equity = update_equity_close(df_all, pos, prev_close, t, equity)
        equity_hist.append(equity)

        # 更新仓位信息中的止损价格
        update_stop_price(df_all, pos, t, params["atr_drawdown"])

        for sym, p in pos.items():
            print("{} close: {:.3f} stop: {:.3f}, take: {:.3f}".format(sym, p["entry"], p["stop"], p["take"]))

        # 更新保留仓位, 卖出部分仓位
        reserve_pos = update_reserve_pos(df_all, pos, t)
        trades.extend(update_trades(df_all, t, reserve_pos, pos))
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

        
