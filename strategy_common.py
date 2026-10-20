"""两个动量策略共用的行情、指标、风险、持仓和交易记录工具。

本模块不依赖策略或记账模块；函数仅读取输入，新状态通过返回值提供。
策略专有的信号、选股规则和回测编排由各策略自身维护。
"""

from typing import NamedTuple

import pandas as pd
import numpy as np


def getv(dataframe, index_label, column):
    """读取指定索引和列的浮点值。

    重复索引取最后一条记录。读取或浮点转换失败时返回 NaN，输入只读。

    Args:
        dataframe: pandas.DataFrame，包含待读取列的行情表。
        index_label: 与表索引兼容的标签，不限于时间戳。
        column: str，待读取的列名。

    Returns:
        float，读取并转换后的值；读取或转换失败时为 NaN。
    """
    try:
        v = dataframe.loc[index_label, column]
        if isinstance(v, pd.Series):
            return float(v.iloc[-1])
        return float(v)
    except:
        return np.nan


def calc_quantity(quantity, lot_size):
    """将数量按交易单位向零截断取整。

    Args:
        quantity: float，待取整的股数，可以为带符号数量。
        lot_size: int，正的最小交易股数，例如 100。

    Returns:
        int，lot_size 的整数倍；负数也按向零方向截断。
    """
    return int(quantity / lot_size) * lot_size


def atr(price_data, window=10):
    """按输入行顺序计算真实波幅的滚动均值。

    Args:
        price_data: pandas.DataFrame，包含 high、low、close 数值列。
        window: int，滚动窗口的行数，默认为 10。

    Returns:
        pandas.Series，与输入索引一致的 ATR；窗口未满时为 NaN。
        不修改输入行情。
    """
    # talib conda
    high_low = price_data["high"] - price_data["low"]
    high_close = (price_data["high"] - price_data["close"].shift()).abs()
    low_close = (price_data["low"] - price_data["close"].shift()).abs()

    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    # 使用rolling mean替代EMA，更稳定
    return tr.rolling(window).mean()


def calc_corr_matrix(market_data: dict, price_column: str = "close") -> pd.DataFrame:
    """计算各标的对数收益率的相关矩阵。

    Args:
        market_data: 按标的代码组织的行情 DataFrame 字典，输入只读。
        price_column: 价格列名，默认为 close；缺少该列的标的被跳过。

    Returns:
        pandas.DataFrame，行列均为标的代码，元素为收益率相关系数。
        每个价格序列按索引排序后计算对数收益率，并按索引对齐。
    """
    rets = {}

    for sym, df in market_data.items():
        if price_column not in df.columns:
            continue

        s = df[price_column].sort_index()
        ret = np.log(s).diff()
        rets[sym] = ret

    ret_df = pd.DataFrame(rets)
    ret_df = ret_df.dropna(how="all")
    corr = ret_df.corr()
    return corr


def calc_position_size(equity, atr_value, price, stop_atr_multiple, max_trade_risk_ratio):
    """根据单笔风险预算和总权益上限计算开仓股数。

    Args:
        equity: float，账户总权益，用于风险预算和持仓金额上限。
        atr_value: float，与每股价格处于同一尺度的 ATR。
        price: float，标的每股价格。
        stop_atr_multiple: float，止损距离相对 ATR 的倍数。
        max_trade_risk_ratio: float，单笔风险占权益的比例，例如 0.02。

    Returns:
        int，按 100 股向零取整且不超过权益金额上限的开仓股数。
        每股止损风险非正时返回 0；不修改输入。
    """
    # 该品种每手最大可能损失
    risk_per_share = atr_value * stop_atr_multiple
    if risk_per_share <= 0:
        return 0

    # 每笔交易的最大允许损失
    risk_amount = equity * max_trade_risk_ratio
    shares = calc_quantity(risk_amount/risk_per_share, 100)

    # 确保仓位不超过市值
    notional = shares * price
    if notional > equity:
        shares = calc_quantity(equity / price, 100)

    return shares


def calc_leverage_by_vol(equity_history, volatility_window, periods_per_year, target_annual_volatility, min_leverage, max_leverage):
    """根据权益曲线的年化波动率计算目标杠杆。

    Args:
        equity_history: 正数权益组成的序列，按时间先后排列，输入只读。
        volatility_window: int，用于估计波动率的最近权益观测数量。
        periods_per_year: float，每年周期数，日频通常为 252。
        target_annual_volatility: float，目标年化波动率，例如 0.3。
        min_leverage: float，样本充足时允许的杠杆下限。
        max_leverage: float，样本充足时允许的杠杆上限。

    Returns:
        float，按上下限裁剪的波动率目标杠杆。权益观测数量不足窗口时
        直接返回 1.0，此时不应用上下限裁剪。
    """
    if len(equity_history) < volatility_window:
        return 1.0

    eq = np.array(equity_history[-volatility_window:])
    ret = np.diff(np.log(eq))

    realized_vol = np.std(ret) * np.sqrt(periods_per_year)

    vol_scale = target_annual_volatility / (realized_vol + 1e-6)
    vol_scale = np.clip(vol_scale, min_leverage, max_leverage)
    return vol_scale


class Trade(NamedTuple):
    """已生成的交易记录，字段顺序与交易表一致。"""

    symbol: str              # 品种代码
    side: int                # 持仓方向
    entry_time: pd.Timestamp  # 买入时刻
    exit_time: pd.Timestamp  # 卖出时刻
    pnl: float               # 交易收益
    exit_reason: str         # 卖出原因


def calc_stop_positions(market_data: dict, positions: dict, timestamp, stop_atr_multiple):
    """根据当日收盘价提高持仓止损价。

    Args:
        market_data: 按标的代码组织的行情 DataFrame 字典，包含 close 列。
        positions: 当前持仓字典，记录包含 stop 和入场时的 atr；输入只读。
        timestamp: 与行情索引兼容的当前时刻。
        stop_atr_multiple: float，止损距离相对持仓 atr 的倍数。

    Returns:
        dict，逐记录复制的新持仓；止损只升不降，无当日行情的记录保持原值。
    """
    next_pos = {sym: p.copy() for sym, p in positions.items()}
    for sym, p in next_pos.items():
        df = market_data[sym]
        if timestamp not in df.index:
            continue

        c = getv(df, timestamp, "close")
        new_stop = c - stop_atr_multiple * p["atr"]
        p["stop"] = max(p["stop"], new_stop)

    return next_pos


def rebalance_portfolio(market_data: dict, positions: dict, timestamp, allocation_budget, quantity_change_threshold_ratio):
    """按 ATR 倒数分配预算并调整持仓股数。

    Args:
        market_data: 按标的代码组织的行情 DataFrame 字典，包含 close 列。
        positions: 当前持仓字典，记录包含 atr、qty、side、entry 和
            entry_time；行情及持仓输入只读。
        timestamp: 与行情索引兼容的调仓时刻。
        allocation_budget: float，可分配的持仓金额预算，通常为权益乘以杠杆。
        quantity_change_threshold_ratio: float，目标股数与当前绝对股数之差
            相对当前绝对股数的阈值；按 ATR 分配的目标调整仅在严格超过时执行。

    Returns:
        dict，逐记录复制且去除零股数记录的新持仓。预算不足时还会裁减可交易
        仓位，此阶段不受上述阈值限制。无当日行情的非零记录保留；可交易记录
        的入场价和时间改为当日值，即使股数未变也会改写返回记录。
    """
    if len(positions) == 0:
        return {}

    total_risk = sum(1.0 / p["atr"] for p in positions.values())

    # 在新的仓位上管理
    new_pos = {}
    for sym, p in positions.items():
        new_pos[sym] = p.copy()
        df = market_data[sym]
        if timestamp not in df.index:
            # 如果当天不能交易, 仓位不变
            continue

        px = getv(df, timestamp, "close")

        risk_weight = (1.0/p["atr"])/total_risk
        target_notional = allocation_budget * risk_weight
        target_qty = calc_quantity(target_notional/px, 100)

        # 平滑调整仓位，避免频繁调仓
        cur_qty = abs(p["qty"])
        if abs(target_qty - cur_qty) > cur_qty*quantity_change_threshold_ratio:
            new_pos[sym]["qty"] = target_qty * p["side"]
        # 更新时间
        new_pos[sym]["entry_time"] = timestamp
        new_pos[sym]["entry"] = px

    # 获取股票总仓位 (只考虑可以交易的)
    unchanged_money = 0
    unchanged_sym_list = []
    money_list = []
    sym_list = []
    for sym, p in new_pos.items():
        df = market_data[sym]
        if timestamp not in df.index:
            # 如果当天不能交易, 仓位不变
            unchanged_money += p["qty"] * p["entry"]
            unchanged_sym_list.append(sym)
        else:
            money_list.append(p["qty"] * p["entry"])
            sym_list.append(sym)

    money_list = np.array(money_list)

    # 如果现金不够, 则优先选择权重大的
    cash = allocation_budget - np.sum(money_list) - unchanged_money
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
            if count > allocation_budget:
                left = allocation_budget - (count - money_list[idx])
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


def normalize_positions(candidate_positions: dict, current_positions: dict) -> dict:
    """为股数未变的候选持仓恢复原入场信息。

    Args:
        candidate_positions: 候选持仓字典，记录包含 qty、entry_time 和 entry。
        current_positions: 调仓前的当前持仓字典；两个输入及其中的记录只读。

    Returns:
        dict，逐记录复制的候选持仓。共有标的入场时间不同但股数相同时，
        恢复当前持仓的 entry_time 和 entry；其余记录保留候选值。
    """
    normalized = {sym: p.copy() for sym, p in candidate_positions.items()}
    for sym in candidate_positions.keys() & current_positions.keys():
        if candidate_positions[sym]["entry_time"] == current_positions[sym]["entry_time"]:
            continue
        if candidate_positions[sym]["qty"] == current_positions[sym]["qty"]:
            normalized[sym]["entry_time"] = current_positions[sym]["entry_time"]
            normalized[sym]["entry"] = current_positions[sym]["entry"]
    return normalized


def calc_trade_records(market_data:dict, timestamp, candidate_positions: dict, current_positions: dict) -> list[Trade]:
    """根据持仓退出和股数变化计算交易记录。

    Args:
        market_data: 按标的代码组织的行情 DataFrame 字典，包含 close 列。
        timestamp: 与行情索引兼容的交易时刻。
        candidate_positions: 调仓后的候选持仓字典。
        current_positions: 调仓前的当前持仓字典，记录包含 qty、side、entry
            和 entry_time；行情及两个持仓输入只读。

    Returns:
        list[Trade]，包含退出和切换仓位的记录，收益按原持仓全部股数计算。
        新开仓及原股数为零时不生成记录；退出时跳过当日入场的记录，切换时
        跳过新旧入场时间相同或股数未变的记录。入场信息修正由
        normalize_positions 单独处理。
    """
    trades: list[Trade] = []
    old_sym = set(current_positions.keys())
    new_sym = set(candidate_positions.keys())

    common_sym = new_sym.intersection(old_sym)
    close_sym = old_sym.difference(new_sym)

    # 关闭仓位
    for sym in close_sym:
        p = current_positions[sym]
        # 如果时间相同, 则不用交易
        if p["entry_time"] == timestamp:
            continue

        # 如果仓位为 0, 则不用交易
        if p["qty"] == 0:
            continue

        df = market_data[sym]
        px = getv(df, timestamp, "close")
        pnl = p["qty"] * (px - p["entry"])
        reason = "止盈" if pnl > 0 else "止损"
        trade_info = Trade(
            symbol=sym,
            side=p["side"],
            entry_time=p["entry_time"],
            exit_time=timestamp,
            pnl=float(pnl),
            exit_reason=reason,
        )
        trades.append(trade_info)

    # 切换仓位
    for sym in common_sym:
        # 如果时间相同， 则跳过
        if candidate_positions[sym]["entry_time"] == current_positions[sym]["entry_time"]:
            continue

        # 如果仓位相同，则不生成交易记录
        if candidate_positions[sym]["qty"] == current_positions[sym]["qty"]:
            continue

        if current_positions[sym]["qty"] == 0:
            continue

        df = market_data[sym]
        px = getv(df, timestamp, "close")
        p = current_positions[sym]
        pnl = p["qty"] * (px - p["entry"])
        trade_info = Trade(
            symbol=sym,
            side=p["side"],
            entry_time=p["entry_time"],
            exit_time=timestamp,
            pnl=float(pnl),
            exit_reason="切换仓位",
        )
        trades.append(trade_info)

    return trades


def build_portfolio_snapshot(market_data: dict, positions: dict, timestamp, equity):
    """构建当日各标的与现金的仓位快照。

    Args:
        market_data: 按标的代码组织的行情 DataFrame 字典，包含 close 列。
        positions: 当前持仓字典，记录包含 qty；行情及持仓输入只读。
        timestamp: 与行情索引兼容的快照时刻。
        equity: float，当日账户总权益，用于扣除可估值持仓后计算现金。

    Returns:
        list[tuple]，每项为 (timestamp, symbol, quantity, value)。所有行情
        标的均有记录，无当日行情或未持有的标的输出零股数及零市值；末项为
        cash，其 quantity 和 value 均为权益扣除上述持仓市值后的金额。
    """
    cur_port = []

    for sym, df in market_data.items():
        if timestamp not in df.index:
            cur_port.append((timestamp, sym, 0, 0))
            continue

        if sym not in positions.keys():
            cur_port.append((timestamp, sym, 0, 0))
            continue

        px = getv(df, timestamp, "close")  # pos[sym]["entry"]  #
        qty = positions[sym]["qty"]

        value = px * qty
        cur_port.append((timestamp, sym, qty, value))
        equity -= value

    cur_port.append((timestamp, "cash", equity, equity))
    return cur_port
