"""两个动量策略共用的行情、指标、风险、持仓和交易记录工具。

本模块不依赖策略或记账模块；函数仅读取输入，新状态通过返回值提供。
策略专有的信号、选股规则和回测编排由各策略自身维护。
"""

from typing import NamedTuple

import pandas as pd
import numpy as np


class Position(NamedTuple):
    """不可变持仓记录，通过属性读取，以 _replace 创建字段变化后的新记录。

    Attributes:
        side: 持仓方向。
        trade_entry_time: 入场或调仓时刻，与两种入场价格对应。
        trade_qty: 带符号的实际持仓股数。
        trade_raw_close: 同一入场或调仓时刻的原始收盘价，不随每日估值更新。
        sig_entry: 入场或调仓时的后复权每股收盘价。
        sig_atr: 建仓时后复权尺度的 ATR。
        sig_stop: 后复权尺度的每股止损价。
        sig_take: 旧策略的后复权止盈价, v2 不使用，默认为 None。
    """
    side: int
    trade_entry_time: pd.Timestamp
    trade_qty: int
    trade_raw_close: float
    sig_entry: float
    sig_atr: float
    sig_stop: float
    sig_take: float | None = None


class Trade(NamedTuple):
    """已生成的交易记录，字段顺序与交易表一致。"""

    symbol: str              # 品种代码
    side: int                # 持仓方向
    entry_time: pd.Timestamp  # 买入时刻
    exit_time: pd.Timestamp  # 卖出时刻
    pnl: float               # 交易收益
    exit_reason: str         # 卖出原因


class PortfolioRow(NamedTuple):
    """每日标的或现金的持仓快照行。"""

    datetime: pd.Timestamp
    symbol: str
    quantity: float
    value: float


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


def calc_corr_matrix(
        market_data: dict,
        price_column: str = "close"
        ) -> pd.DataFrame:
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


def calc_position_size(
        equity: float,
        sig_atr: float,
        sig_entry: float,
        trade_raw_close: float,
        stop_atr_multiple: float,
        max_trade_risk_ratio: float
        ) -> int:
    """根据单笔风险预算和总权益上限计算开仓股数。

    Args:
        equity: 账户总权益，用于风险预算和持仓金额上限。
        sig_atr: 后复权尺度的 ATR。
        sig_entry: 后复权每股入场价，要求有限且为正。
        trade_raw_close: 与信号入场价同一时刻的原始收盘价，要求有限且为正。
        stop_atr_multiple: 止损距离相对 ATR 的倍数。
        max_trade_risk_ratio: 单笔风险占权益的比例, 例如 0.02。

    Returns:
        按 100 股向零取整且不超过权益金额上限的开仓股数。
        复权止损距离乘原始价与信号价之比得到真实每股风险，资金上限使用原始价。
        每股止损风险非正时返回 0；不修改输入。
    """
    # 将复权尺度的止损距离换算为真实每股风险
    risk_per_share = sig_atr * stop_atr_multiple * trade_raw_close / sig_entry
    if risk_per_share <= 0:
        return 0

    # 每笔交易的最大允许损失
    risk_amount = equity * max_trade_risk_ratio
    shares = calc_quantity(risk_amount/risk_per_share, 100)

    # 确保仓位不超过市值
    notional = shares * trade_raw_close
    if notional > equity:
        shares = calc_quantity(equity / trade_raw_close, 100)

    return shares


def calc_leverage_by_vol(
        equity_history: list[float],
        volatility_window: int,
        periods_per_year: int,
        target_annual_volatility: float,
        min_leverage: float,
        max_leverage: float
        ) -> float:
    """根据权益曲线的年化波动率计算目标杠杆。

    Args:
        equity_history: 正数权益组成的序列，按时间先后排列，输入只读。
        volatility_window: 用于估计波动率的最近权益观测数量。
        periods_per_year: 每年周期数，日频通常为 252。
        target_annual_volatility: 目标年化波动率，例如 0.3。
        min_leverage: 样本充足时允许的杠杆下限。
        max_leverage: 样本充足时允许的杠杆上限。

    Returns:
        按上下限裁剪的波动率目标杠杆。权益观测数量不足窗口时
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


def calc_stop_positions(
        market_data: dict,
        positions: dict[str, Position],
        timestamp,
        stop_atr_multiple: float,
        ) -> dict[str, Position]:
    """根据当日后复权收盘价提高信号止损价。

    Args:
        market_data: 按标的代码组织的行情 DataFrame 字典，包含 close 列。
        positions: 当前 Position 持仓字典，使用 sig_stop 和建仓时的 sig_atr；输入只读。
        timestamp: 与行情索引兼容的当前时刻。
        stop_atr_multiple: 止损距离相对持仓 sig_atr 的倍数。

    Returns:
        dict[str, Position]，新的外层持仓字典；止损只升不降，未变化的
        不可变记录允许共享，无当日行情的记录保持原值。
    """
    next_pos = positions.copy()
    for sym, p in next_pos.items():
        df = market_data[sym]
        if timestamp not in df.index:
            continue

        c = getv(df, timestamp, "close")
        new_stop = c - stop_atr_multiple * p.sig_atr
        next_pos[sym] = p._replace(sig_stop=max(p.sig_stop, new_stop))

    return next_pos


def rebalance_portfolio(
        market_data: dict,
        positions: dict[str, Position],
        timestamp,
        allocation_budget: float,
        quantity_change_threshold_ratio: float,
        ) -> dict[str, Position]:
    """按信号 ATR 倒数分配预算，以原始价计算实际股数。

    Args:
        market_data: 按标的代码组织的行情 DataFrame 字典，包含后复权 close
            和原始 raw_close 列。
        positions: 当前 Position 持仓字典，使用 sig_atr、trade_qty、side、
            sig_entry、trade_raw_close 和 trade_entry_time；行情及持仓输入只读。
        timestamp: 与行情索引兼容的调仓时刻。
        allocation_budget: 可分配的持仓金额预算，通常为权益乘以杠杆。
        quantity_change_threshold_ratio: 目标股数与当前绝对股数之差
            相对当前绝对股数的阈值；按 ATR 分配的目标调整仅在严格超过时执行。

    Returns:
        dict[str, Position]，新的外层持仓字典，去除零股数记录；未变化的
        不可变记录允许共享。预算不足时还会裁减可交易仓位，此阶段不受上述
        阈值限制。无当日行情的非零记录保留；可交易记录
        的两种入场价和交易入场时间改为当日值，即使股数未变也会改写返回记录，
        调用方再通过入场信息保留函数恢复未实际调仓的成本。资金占用及裁仓使用
        原始价；停牌记录的资金占用沿用保存的原始入场价。
    """
    if len(positions) == 0:
        return {}

    total_risk = sum(1.0 / p.sig_atr for p in positions.values())

    # 在新的仓位上管理
    new_pos = {}
    for sym, p in positions.items():
        new_pos[sym] = p
        df = market_data[sym]
        if timestamp not in df.index:
            # 如果当天不能交易, 仓位不变
            continue

        sig_price = getv(df, timestamp, "close")
        raw_price = getv(df, timestamp, "raw_close")

        risk_weight = (1.0/p.sig_atr)/total_risk
        target_notional = allocation_budget * risk_weight
        target_qty = calc_quantity(target_notional/raw_price, 100)

        # 平滑调整仓位，避免频繁调仓
        cur_qty = abs(p.trade_qty)
        if abs(target_qty - cur_qty) > cur_qty*quantity_change_threshold_ratio:
            new_pos[sym] = new_pos[sym]._replace(trade_qty=target_qty * p.side)
        # 更新时间
        new_pos[sym] = new_pos[sym]._replace(
            trade_entry_time=timestamp, sig_entry=sig_price, trade_raw_close=raw_price)

    # 获取股票总仓位 (只考虑可以交易的)
    unchanged_money = 0
    unchanged_sym_list = []
    money_list = []
    sym_list = []
    for sym, p in new_pos.items():
        df = market_data[sym]
        if timestamp not in df.index:
            # 如果当天不能交易, 仓位不变
            unchanged_money += p.trade_qty * p.trade_raw_close
            unchanged_sym_list.append(sym)
        else:
            money_list.append(p.trade_qty * p.trade_raw_close)
            sym_list.append(sym)

    money_list = np.array(money_list)

    # 如果现金不够, 则优先选择权重大的
    cash = allocation_budget - np.sum(money_list) - unchanged_money
    if cash < 0:
        count = 0
        new_new_pos = {}
        # 无法交易的直接拷贝过来
        for sym in unchanged_sym_list:
            new_new_pos[sym] = new_pos[sym]

        # 只考虑可以交易的
        idx_list = np.argsort(money_list)[::-1]
        for idx in idx_list:
            count += money_list[idx]
            sym = sym_list[idx]
            new_new_pos[sym] = new_pos[sym]
            if count > allocation_budget:
                left = allocation_budget - (count - money_list[idx])
                raw_price = new_pos[sym].trade_raw_close
                qty = calc_quantity(left/raw_price, 100)
                new_new_pos[sym] = new_new_pos[sym]._replace(trade_qty=qty)
                break

        new_pos = new_new_pos.copy()

    # 去除仓位为 0 的标的
    out_pos = {}
    for sym, p in new_pos.items():
        if p.trade_qty != 0:
            out_pos[sym] = p
    return out_pos


def preserve_entries_for_unchanged_quantities(
        candidate_positions: dict[str, Position],
        current_positions: dict[str, Position]
        ) -> dict[str, Position]:
    """为股数未变的候选持仓恢复原入场信息。

    Args:
        candidate_positions: 候选 Position 持仓字典，使用 trade_qty、
            trade_entry_time、sig_entry 和 trade_raw_close。
        current_positions: 调仓前的 Position 持仓字典；两个输入及记录只读。

    Returns:
        dict[str, Position]，新的外层候选持仓字典。共有标的入场时间不同但
        股数相同时，恢复当前持仓的交易入场时间和两种入场价格，其他字段保留候选值；
        未变化的不可变记录允许共享。
    """
    normalized = candidate_positions.copy()
    for sym in candidate_positions.keys() & current_positions.keys():
        if candidate_positions[sym].trade_entry_time == current_positions[sym].trade_entry_time:
            continue
        if candidate_positions[sym].trade_qty == current_positions[sym].trade_qty:
            normalized[sym] = candidate_positions[sym]._replace(
                trade_entry_time=current_positions[sym].trade_entry_time,
                sig_entry=current_positions[sym].sig_entry,
                trade_raw_close=current_positions[sym].trade_raw_close)
    return normalized


def calc_trade_records(
        market_data:dict,
        timestamp,
        candidate_positions: dict[str, Position],
        current_positions: dict[str, Position]
        ) -> list[Trade]:
    """根据持仓退出和股数变化，以实际股数及原始价差计算交易记录。

    Args:
        market_data: 按标的代码组织的行情 DataFrame 字典，包含原始 raw_close 列。
        timestamp: 与行情索引兼容的交易时刻。
        candidate_positions: 调仓后的候选 Position 持仓字典。
        current_positions: 调仓前的 Position 持仓字典，使用 trade_qty、side、
            trade_raw_close 和 trade_entry_time；行情及两个持仓输入只读。

    Returns:
        list[Trade]，包含退出和切换仓位的记录，收益为原持仓全部实际股数乘
        当日原始价与原始入场价之差，报表 entry_time 来自 trade_entry_time。
        新开仓及原股数为零时不生成记录；退出时跳过当日入场的记录，切换时
        跳过新旧入场时间相同或股数未变的记录。入场信息修正由
        preserve_entries_for_unchanged_quantities 单独处理。
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
        if p.trade_entry_time == timestamp:
            continue

        # 如果仓位为 0, 则不用交易
        if p.trade_qty == 0:
            continue

        df = market_data[sym]
        px = getv(df, timestamp, "raw_close")
        pnl = p.trade_qty * (px - p.trade_raw_close)
        reason = "止盈" if pnl > 0 else "止损"
        trade_info = Trade(
            symbol=sym,
            side=p.side,
            entry_time=p.trade_entry_time,
            exit_time=timestamp,
            pnl=float(pnl),
            exit_reason=reason,
        )
        trades.append(trade_info)

    # 切换仓位
    for sym in common_sym:
        # 如果时间相同， 则跳过
        if candidate_positions[sym].trade_entry_time == current_positions[sym].trade_entry_time:
            continue

        # 如果仓位相同，则不生成交易记录
        if candidate_positions[sym].trade_qty == current_positions[sym].trade_qty:
            continue

        if current_positions[sym].trade_qty == 0:
            continue

        df = market_data[sym]
        px = getv(df, timestamp, "raw_close")
        p = current_positions[sym]
        pnl = p.trade_qty * (px - p.trade_raw_close)
        trade_info = Trade(
            symbol=sym,
            side=p.side,
            entry_time=p.trade_entry_time,
            exit_time=timestamp,
            pnl=float(pnl),
            exit_reason="切换仓位",
        )
        trades.append(trade_info)

    return trades


def build_portfolio_snapshot(
        market_data: dict,
        positions: dict[str, Position],
        timestamp,
        equity: float,
        ) -> list[PortfolioRow]:
    """以实际股数和当日原始收盘价构建标的与现金的仓位快照。

    Args:
        market_data: 按标的代码组织的行情 DataFrame 字典，包含原始 raw_close 列。
        positions: 当前 Position 持仓字典，使用 trade_qty；行情及持仓输入只读。
        timestamp: 与行情索引兼容的快照时刻。
        equity: 当日账户总权益，用于扣除可估值持仓后计算现金。

    Returns:
        list[PortfolioRow]，字段为 datetime、symbol、quantity、value。所有行情
        标的均有记录，无当日行情或未持有的标的输出零股数及零市值；末项为
        cash，其 quantity 和 value 均为权益扣除上述持仓市值后的金额。
    """
    cur_port: list[PortfolioRow] = []

    for sym, df in market_data.items():
        if timestamp not in df.index:
            cur_port.append(PortfolioRow(datetime=timestamp, symbol=sym, quantity=0, value=0))
            continue

        if sym not in positions.keys():
            cur_port.append(PortfolioRow(datetime=timestamp, symbol=sym, quantity=0, value=0))
            continue

        px = getv(df, timestamp, "raw_close")
        qty = positions[sym].trade_qty

        value = px * qty
        cur_port.append(PortfolioRow(datetime=timestamp, symbol=sym, quantity=qty, value=value))
        equity -= value

    cur_port.append(PortfolioRow(datetime=timestamp, symbol="cash", quantity=equity, value=equity))
    return cur_port
