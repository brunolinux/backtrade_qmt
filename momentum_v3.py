from typing import NamedTuple

import pandas as pd
import numpy as np
from momentum_util import (getv, atr, calc_quantity,
    calc_volatility_targeting_leverage, validate_lot_size)
from momentum_util import calc_position_size as _calc_position_size


class Position(NamedTuple):
    """不可变持仓：sig_ 为后复权信号，trade_ 为实际交易和记账数据。"""

    trade_entry: float     # 实际每股平均持仓成本，加仓时按股数加权更新。
    trade_entry_time: pd.Timestamp  # 当前持仓首次建仓时间，加减仓时保留。
    trade_mark_price: float     # 最近可交易时刻的实际收盘价，停牌期间用于估值。
    sig_stop: float        # 后复权价格尺度的移动止损线，用于退出信号判断。
    sig_atr: float         # 建仓时由后复权 high/low/close 计算的 ATR；持仓期间保持不变。
    trade_qty: int         # 实际持有股数，按 params['lot_size'] 为单位调整，默认 100 股。
    trade_side: int        # 持仓方向，v2 当前仅支持多头，取值为 1。


class Trade(NamedTuple):
    """一次减仓或平仓的已实现盈亏记录，不包含买入或加仓成交。"""

    symbol: str               # 交易品种代码，对应持仓字典的键。
    side: int                 # 原持仓方向，v2 当前仅支持多头，取值为 1。
    entry_time: pd.Timestamp  # 原持仓首次建仓时间，加减仓不会重置。
    exit_time: pd.Timestamp   # 本次减仓或平仓的成交时间。
    pnl: float                # 实际卖出股数 ×（实际成交价 - 实际平均成本）的已实现盈亏。
    exit_reason: str          # 部分减仓为“切换仓位”；平仓按盈亏归为“止盈”或“止损”。


def get_trade_close(df, time):
    """成交、估值必须使用有效的实际价格，不能回退到后复权价。"""
    price = getv(df, time, "raw_close")
    if not np.isfinite(price) or price <= 0:
        raise ValueError(f"{time}: raw_close 必须是有限的正数")
    return price


def calc_trade_risk_per_share(sig_atr, sig_close, trade_price):
    """在交易计算边界，将后复权 ATR 换算为实际每股的一倍 ATR 风险金额。

    返回值不写入 Position。仅在计算开仓股数时另行应用止损倍数。
    """
    if any(not np.isfinite(value) or value <= 0
           for value in (sig_atr, sig_close, trade_price)):
        raise ValueError("ATR、后复权收盘价和实际价格必须是有限的正数")
    return sig_atr * trade_price / sig_close


def calc_entry_trade_quantity(
        *, sig_atr: float, sig_close: float, sig_stop_atr_multiple: float,
        trade_equity: float, trade_price: float, trade_max_risk_ratio: float,
        trade_lot_size: int = 100) -> int:
    """按信号止损风险和实际资金上限，计算最小交易单位取整后的开仓股数。

    信号参数：
    sig_atr: 后复权价格尺度的 ATR，不要提前换算为实际价格尺度。
    sig_close: 与 sig_atr 同时刻、同一后复权尺度的收盘价。
    sig_stop_atr_multiple: 信号止损的 ATR 倍数，对应 params['atr_stop']。

    交易参数：
    trade_equity: 实际账户总权益，用于计算风险预算及持仓金额上限。
    trade_price: 与 sig_close 同时刻的实际每股价格，来自 raw_close。
    trade_max_risk_ratio: 单笔允许损失占实际权益的比例。
    trade_lot_size: 最小交易股数，须为正整数，默认 100。

    仅在本函数内部将信号 ATR 换算为实际每股风险，再应用止损倍数。
    所有参数仅允许关键字传入，返回实际股数，不修改持仓或信号。
    """
    trade_risk_per_share = calc_trade_risk_per_share(sig_atr, sig_close, trade_price)
    return _calc_position_size(
        equity=trade_equity,
        atr_value=trade_risk_per_share,
        px=trade_price,
        atr_stop=sig_stop_atr_multiple,
        max_risk_per_trade=trade_max_risk_ratio,
        lot_size=trade_lot_size,
    )


def calc_mark_to_market_equity(
        df_all: dict, pos: dict[str, Position], prev_close: dict, time, prev_equity):
    """用实际股数和上次实际收盘价计算盯市权益，不修改任何输入。

    必须在更新估值价格之前调用；当天无法交易的持仓不产生价格盈亏。
    """
    equity = prev_equity
    for sym, p in pos.items():
        df = df_all[sym]
        if time not in df.index:
            continue
        price = get_trade_close(df, time)
        previous = prev_close.get(sym, p.trade_mark_price)
        equity += p.trade_qty * (price - previous)
    return equity


def update_position_trade_marks(
        df_all: dict, pos: dict[str, Position], prev_close: dict, time):
    """同步持仓估值价和下次盯市的实际价格基准；停牌时保留原值。

    不计算权益、不更新信号，必须在当次盯市计算之后调用。
    """
    for sym, p in pos.items():
        df = df_all[sym]
        if time not in df.index:
            continue
        price = get_trade_close(df, time)
        pos[sym] = p._replace(trade_mark_price=price)
        prev_close[sym] = price


def update_position_stop_price(df_all: dict, pos: dict[str, Position], time, atr_stop):
    """按后复权收盘价更新止损信号，替换持仓记录并保留其余字段。"""
    for sym, p in pos.items():
        df = df_all[sym]
        if time not in df.index:
            continue
        new_sig_stop = getv(df, time, "close") - atr_stop * p.sig_atr
        pos[sym] = p._replace(sig_stop=max(p.sig_stop, new_sig_stop))


def update_position_cost_basis(
        df_all: dict, time, new_pos: dict[str, Position], old_pos: dict[str, Position]):
    """仅维护 new_pos 中的实际平均成本和首次建仓时间，不修改 old_pos。

    加仓按实际成交价和新增股数更新平均成本；减仓或股数不变时保留
    原成本。已有持仓保留首次建仓时间；全新持仓沿用 build_entry_position()
    初始化的成本及时间。本函数不生成盈亏记录，也不更新总权益。
    """
    for sym, new in new_pos.items():
        old = old_pos.get(sym)
        # 全新持仓的成本和建仓时间已在开仓时初始化。
        if old is None:
            continue
        entry = old.trade_entry
        # 仅加仓需要重算平均成本；减仓不改变剩余股份的每股成本。
        if new.trade_qty > old.trade_qty:
            price = get_trade_close(df_all[sym], time)
            added_qty = new.trade_qty - old.trade_qty
            entry = (old.trade_qty * old.trade_entry + added_qty * price) / new.trade_qty
        new_pos[sym] = new._replace(trade_entry=entry, trade_entry_time=old.trade_entry_time)


def calc_realized_pnl_records(
        df_all: dict, time, new_pos: dict[str, Position], old_pos: dict[str, Position]) -> list[Trade]:
    """仅返回减仓、平仓的已实现盈亏记录，不修改输入持仓或总权益。

    按实际卖出股数和 old_pos 中的平均成本记账。加仓和股数不变时
    不产生记录；此结果用于盈亏统计，不再重复计入已盯市的权益。
    v2 只持有多头仓位，记录格式与回测返回的 trades 表保持一致。
    """
    trades: list[Trade] = []
    for sym, old in old_pos.items():
        new = new_pos.get(sym)
        old_qty = old.trade_qty
        # 新持仓中已无该品种时，视为全部平仓，目标股数为 0。
        new_qty = new.trade_qty if new is not None else 0
        # 加仓没有卖出股份；股数不变没有买卖，两者均无已实现盈亏。
        if new_qty >= old_qty:
            continue
        price = get_trade_close(df_all[sym], time)
        # 剩余情况为减仓或全部平仓，仅按卖出股数计算已实现盈亏。
        pnl = (old_qty - new_qty) * (price - old.trade_entry)
        # 部分减仓标记为切换仓位；全部平仓按盈亏正负标记原因，零收益归为止损。
        if new_qty > 0:
            reason = "切换仓位"
        elif pnl > 0:
            reason = "止盈"
        else:
            reason = "止损"
        trades.append(Trade(
            symbol=sym,
            side=old.trade_side,
            entry_time=old.trade_entry_time,
            exit_time=time,
            pnl=float(pnl),
            exit_reason=reason,
        ))
    return trades


def calc_target_positions(
        df_all: dict, pos: dict[str, Position], time, trade_budget,
        pos_change_threshold, lot_size=100) -> dict[str, Position]:
    """按风险权重计算目标股数，应用最小交易单位和调仓阈值。

    更新返回持仓中的实际估值价，保留原成本和信号；停牌持仓保持原样。
    风险换算只使用截至当前的行情。返回新映射，不修改输入持仓。
    预算裁剪及零仓位清理由 apply_position_budget_limit() 统一处理。
    """
    validate_lot_size(lot_size)
    if not pos:
        return {}
    new_pos = pos.copy()
    tradable = []
    trade_risk_per_share = {}
    for sym, p in new_pos.items():
        df = df_all[sym]
        if time not in df.index:
            # 停牌时使用最近已知行情配对换算，不能读取未来的复权因子。
            risk_time = df.index[df.index <= time].max()
            if pd.isna(risk_time):
                raise ValueError(f"{sym}: {time} 之前无可用于风险换算的行情")
            price = get_trade_close(df, risk_time)
        else:
            risk_time = time
            price = get_trade_close(df, time)
            new_pos[sym] = p._replace(trade_mark_price=price)
            tradable.append(sym)
        trade_risk_per_share[sym] = calc_trade_risk_per_share(
            p.sig_atr, getv(df, risk_time, "close"), price)

    total_risk = sum(1.0 / risk for risk in trade_risk_per_share.values())
    for sym in tradable:
        p = new_pos[sym]
        target_value = trade_budget * (1.0 / trade_risk_per_share[sym]) / total_risk
        target_qty = calc_quantity(target_value / p.trade_mark_price, lot_size)
        if abs(target_qty - p.trade_qty) > p.trade_qty * pos_change_threshold:
            new_pos[sym] = p._replace(trade_qty=target_qty)
    return new_pos


def apply_position_budget_limit(
        target_positions: dict[str, Position], tradable_symbols: set[str],
        trade_budget, lot_size=100) -> dict[str, Position]:
    """对目标仓位应用资金预算约束，返回新映射，不修改输入持仓。

    使用目标仓位中已更新的实际估值价；先扣除不可交易持仓占用，再按
    目标持仓金额从大到小配置可交易品种，按 lot_size 裁剪并移除零仓位。
    不重新计算风险或调仓阈值。若停牌持仓已超预算，仍须保留这些持仓，
    此时可交易品种的可用预算为零。
    """
    validate_lot_size(lot_size)
    new_pos = target_positions.copy()
    tradable = [sym for sym in new_pos if sym in tradable_symbols]
    frozen_value = sum(p.trade_qty * p.trade_mark_price
                       for sym, p in new_pos.items() if sym not in tradable_symbols)
    available = max(0.0, trade_budget - frozen_value)
    # 保留原有优先配置大仓位的规则，同时扣除停牌持仓占用的资金。
    tradable.sort(key=lambda sym: new_pos[sym].trade_qty * new_pos[sym].trade_mark_price,
                  reverse=True)
    for sym in tradable:
        p = new_pos[sym]
        if p.trade_qty * p.trade_mark_price > available:
            p = p._replace(trade_qty=max(0, calc_quantity(available / p.trade_mark_price, lot_size)))
            new_pos[sym] = p
        available = max(0.0, available - p.trade_qty * p.trade_mark_price)
    return {sym: p for sym, p in new_pos.items() if p.trade_qty > 0}


def calc_rebalanced_positions(
        df_all: dict, pos: dict[str, Position], time, trade_budget,
        pos_change_threshold, lot_size=100) -> dict[str, Position]:
    """编排目标仓位计算和预算约束，返回最终调仓持仓，不修改输入持仓。"""
    targets = calc_target_positions(
        df_all, pos, time, trade_budget, pos_change_threshold, lot_size=lot_size)
    tradable_symbols = {sym for sym in targets if time in df_all[sym].index}
    return apply_position_budget_limit(targets, tradable_symbols, trade_budget, lot_size=lot_size)


def update_portfolio_info(df_all: dict, pos: dict[str, Position], time, equity):
    """持仓市值 = 实际收盘价 × 实际股数；现金 = 总权益 - 持仓市值。"""
    rows = []
    cash = equity
    for sym, df in df_all.items():
        if sym not in pos:
            rows.append((time, sym, 0, 0))
            continue
        p = pos[sym]
        price = get_trade_close(df, time) if time in df.index else p.trade_mark_price
        value = price * p.trade_qty
        rows.append((time, sym, p.trade_qty, value))
        cash -= value
    rows.append((time, "cash", cash, cash))
    return rows


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

        if "raw_close" not in df.columns:
            raise ValueError(f"{sym}: 缺少实际收盘价 raw_close")
        if not (np.isfinite(df["raw_close"]) & (df["raw_close"] > 0)).all():
            raise ValueError(f"{sym}: raw_close 必须是有限的正数")
        
        # high/low/close 均为后复权 OHLC；raw_close 不参与 ATR 信号计算。
        df["atr"] = atr(df, atr_window)

        # 计算技术指标
        mom_short = df["close"].pct_change(short_window)
        mom_long = df["close"].pct_change(long_window)
        vol = df["close"].pct_change().rolling(vol_window).std()
        factor = (mom_short*0.7 + mom_long*0.3)/vol
        df["factor"] = factor
        df_all[sym] = df


def calc_cross_sectional_ranking(df_all: dict, time, col_name="factor"):
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


def calc_retained_positions(df_all: dict, pos: dict[str, Position], sorted_factor, time, top_num_reserve):
    """
    从已有持仓中筛选继续持有的仓位，不修改输入持仓。

    判断依据：
    1. 当天无行情记录时，无法交易，继续保留原持仓。
    2. 当天有行情记录时，必须同时满足：后复权收盘价严格高于
       sig_stop，且截面因子降序排名位于前 top_num_reserve 名。
    3. 收盘价触及或跌破止损线、排名超出保留范围，或未进入当天
       有效因子排名的持仓，均不继续持有。

    止损比较统一使用后复权价格，实际交易价格不参与此信号判断。
    df_all: 多品种字典
    pos: 现有仓位字典
    sorted_factor: 按因子值降序排列的截面排名
    time: 当前时刻
    top_num_reserve: 允许继续持有的排名范围（前 N 名）
    """
    reserve_pos = {}

    # 遍历所有仓位
    for sym in pos.keys():
        df = df_all[sym]
        # 如果当天不能交易, 则保留仓位
        if time not in df.index:
            reserve_pos[sym] = pos[sym]
            continue

        c = getv(df, time, "close")
        p = pos[sym]

        rank_index = (sorted_factor.index.get_loc(sym)
                      if sym in sorted_factor.index else np.inf)
        # 后复权收盘价高于信号止损线，且因子排序仍靠前时保留。
        if c > p.sig_stop and rank_index < top_num_reserve:
            reserve_pos[sym] = p

    return reserve_pos


def select_entry_candidates(
        sorted_factor: pd.Series, old_pos: dict[str, Position]) -> list[str]:
    """按截面因子降序选择未持仓且因子有效、非负的候选品种。

    此处只筛选信号，不限制候选数量；后续构建失败的品种不占新增名额。
    sorted_factor 必须已按降序排列，遇到负因子时结束筛选。
    """
    candidates = []
    for sym, factor in sorted_factor.items():
        if not np.isfinite(factor):
            continue
        # 因为 factor 降序排列，如果当前 factor 小于 0，后续 factor 均小于0，不用考虑了
        if factor < 0:
            break
        if sym in old_pos:
            continue
        candidates.append(sym)
    return candidates


def build_entry_position(
        df: pd.DataFrame, time, equity, atr_stop, max_risk_per_trade, lot_size=100) -> Position | None:
    """为单个品种构建开仓持仓，信号使用后复权价，股数和成本使用实际价。

    当天无行情、信号数据无效或计算股数不足 lot_size 时，返回 None。
    实际价格必须有效，由 get_trade_close() 校验。本函数不修改行情数据。
    """
    if time not in df.index:
        return None
    sig_close = getv(df, time, "close")
    sig_atr = getv(df, time, "atr")
    if (not np.isfinite(sig_close) or sig_close <= 0
            or not np.isfinite(sig_atr) or sig_atr <= 0):
        return None
    trade_price = get_trade_close(df, time)
    sig_stop = sig_close - atr_stop * sig_atr

    # 信号和实际交易参数分别传入，由股数计算函数在内部完成尺度换算。
    trade_qty = calc_entry_trade_quantity(
        sig_atr=sig_atr,
        sig_close=sig_close,
        sig_stop_atr_multiple=atr_stop,
        trade_equity=equity,
        trade_price=trade_price,
        trade_max_risk_ratio=max_risk_per_trade,
        trade_lot_size=lot_size,
    )
    if trade_qty <= 0:
        return None

    return Position(
        trade_entry=trade_price,
        trade_entry_time=time,
        trade_mark_price=trade_price,
        sig_stop=sig_stop,
        sig_atr=sig_atr,
        trade_qty=trade_qty,
        trade_side=1,
    )


def calc_entry_positions(
        df_all: dict, old_pos: dict[str, Position], sorted_factor: pd.Series, time,
        equity, max_new_positions, atr_stop, max_risk_per_trade, lot_size=100) -> dict[str, Position]:
    """编排候选筛选和持仓构建，最多返回 max_new_positions 个有效新增持仓。

    已有持仓、无效信号和零股数均不占名额，按排名继续查找后续品种。
    仅返回拟新增持仓；最终采用持仓的盯市基准由 backtest() 初始化。
    """
    entries: dict[str, Position] = {}
    if max_new_positions <= 0:
        return entries
    for sym in select_entry_candidates(sorted_factor, old_pos):
        position = build_entry_position(
            df_all[sym], time, equity, atr_stop, max_risk_per_trade, lot_size=lot_size)
        if position is None:
            continue
        entries[sym] = position
        # 按成功构建的新增持仓计数，而不是按遍历过的排名位置计数。
        if len(entries) >= max_new_positions:
            break
    return entries


def backtest(df_all: dict, params: dict, start_date=None):
    """
    回测：实际价格用于成交和记账，后复权价格用于信号。
    df_all: 多品种数据字典
    params: 参数；可选 lot_size 为最小交易股数，须为正整数，默认 100
    start_date: 起始日期

    当前按收盘价成交，不计手续费，也不自动处理分红现金或送转股数；
    这些权益变动需要额外的公司行动数据，不能用后复权价差代替。
    """
    lot_size = params.get("lot_size", 100)
    validate_lot_size(lot_size)
    equity = float(params["init_equity"])
    pos: dict[str, Position] = {}
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

        # 先按旧价格基准计算盯市权益，再同步当前实际估值价。
        equity = calc_mark_to_market_equity(df_all, pos, prev_close, t, equity)
        equity_hist.append(equity)
        update_position_trade_marks(df_all, pos, prev_close, t)
 
        # 更新仓位信息中的止损价格
        update_position_stop_price(df_all, pos, t, params["atr_stop"])

        # 对截面因子排序
        sorted_factor = calc_cross_sectional_ranking(df_all, t, "factor")

        # 计算继续持有品种
        retained_pos = calc_retained_positions(df_all, pos, sorted_factor, t, params["top_num_reserve"])
        # 仅记录退出持仓的已实现盈亏；继续持有的仓位沿用原成本。
        trades.extend(calc_realized_pnl_records(df_all, t, retained_pos, pos))
        # 更换为继续持有品种
        pos = retained_pos

        # 新增持仓数量上限，已有持仓和构建失败的候选不占新增名额。
        max_new_positions = params["hold_max_num"] - len(pos)

        if max_new_positions > 0:
            entry_positions = calc_entry_positions(
                df_all, pos, sorted_factor, t, equity, max_new_positions,
                params["atr_stop"], params["max_risk_per_trade"], lot_size=lot_size)
            candidate_pos = {**pos, **entry_positions}

            # 更新波动率计算杠杆率
            lev = calc_volatility_targeting_leverage(equity_hist,
                                       params["window_vol"],
                                       params["annual_factor"],
                                       params["target_vol"],
                                       params["min_lev"],
                                       params["max_lev"])
            real_equity = equity * lev

            # 调整仓位 (考虑整个资产组合)
            cur_pos = calc_rebalanced_positions(
                df_all, candidate_pos, t, real_equity, params["pos_change_threshold"], lot_size=lot_size)
            trades.extend(calc_realized_pnl_records(df_all, t, cur_pos, pos))
            update_position_cost_basis(df_all, t, cur_pos, pos)
            # 只为组合调仓后实际采用的新持仓初始化盯市基准。
            prev_close.update({sym: p.trade_mark_price for sym, p in cur_pos.items()
                               if sym not in pos})
            pos = cur_pos


        # 更新每个标的的仓位信息, 如果没有买入，则为0
        cur_portfolio = update_portfolio_info(df_all, pos, t, equity)
        df_portfolio.extend(cur_portfolio)
        curve.append((t, equity))
        print("{} over!!!!".format(t))

    portfolio = pd.DataFrame(df_portfolio, columns=["datetime", "symbol", "quantity", "value"]).set_index("datetime")

    curve = pd.DataFrame(curve, columns=["datetime", "equity"]).set_index("datetime")
    trades = pd.DataFrame(trades, columns=Trade._fields)

    # for sym, df in df_all.items():
    #     qty = portfolio.loc[portfolio["symbol"] == sym, "quantity"]
    #     df["quantity"] = qty
    #     df.to_csv(os.path.join(os.path.dirname(__file__), "data", "tmp", "{}.csv".format(sym)))

    return portfolio, curve, trades

        
