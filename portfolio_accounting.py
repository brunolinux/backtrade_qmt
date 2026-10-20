"""与策略无关的组合盯市计算和收盘估值基准维护。"""

from collections.abc import Mapping

from strategy_common import Position, getv


def calc_mark_to_market_equity(
        quantities: Mapping[str, float], current_close: Mapping[str, float],
        prev_close: Mapping[str, float], prev_equity: float) -> float:
    """按持仓股数和价格变动计算盯市后的权益。

    Args:
        quantities: 标的代码到带符号持仓股数的映射。
        current_close: 标的代码到当日每股收盘价的映射，仅包含有行情的标的。
        prev_close: 标的代码到上次每股估值价格的映射。
        prev_equity: float，上次账户总权益；所有输入只读。

    Returns:
        float，上次权益加各持仓股数乘以价格变动的总和。缺当日价格不产生
        盈亏，缺旧基准以当日价格为基准，NaN 价格按运算规则传播。
        每次均按传入的旧基准计算，无跨调用去重机制。
    """
    equity = prev_equity
    for sym, qty in quantities.items():
        if sym in current_close:
            price = current_close[sym]
            previous = prev_close.get(sym, price)
            equity += qty * (price - previous)
    return equity


def build_close_marks(
        current_close: Mapping[str, float],
        prev_close: Mapping[str, float]) -> dict[str, float]:
    """合并当日收盘价与旧估值基准。

    Args:
        current_close: 当日有行情标的的每股收盘价映射，无行情标的应省略。
        prev_close: 上次每股估值价格的映射；两个输入只读。

    Returns:
        dict[str, float]，独立的完整新基准字典。当日键覆盖旧值，包括 NaN；
        未出现在当日映射中的旧键保留。
    """
    return {**prev_close, **current_close}


def calc_equity_close(
        market_data: dict,
        positions: dict[str, Position],
        prev_close: dict,
        timestamp,
        prev_equity
        ):
    """用同一份收盘价快照计算权益和下一次估值基准。

    Args:
        market_data: 按标的代码组织的行情 DataFrame 字典，包含 close 列。
        positions: 当前 Position 持仓字典，每条记录的 qty 为带符号股数。
        prev_close: 上次每股估值价格字典，开仓基准由调用方按买入价初始化。
        timestamp: 与行情索引兼容的当前估值时刻。
        prev_equity: float，上次账户总权益；行情、持仓及旧基准输入只读。

    Returns:
        tuple[float, dict]，即 (equity, next_close)。权益按收盘价变动计算；
        新基准保留全部旧键，更新当日有行情的持仓。缺行情保留旧基准，
        缺旧基准使用当日价；重复索引取最后一条，无效价格按 NaN 传播。
        每个可估值持仓仅读取一次价格，无跨调用的按日去重机制。
    """
    quantities = {}
    current_close = {}
    for sym, position in list(positions.items()):
        df = market_data[sym]
        if timestamp in df.index:
            quantities[sym] = position.qty
            current_close[sym] = getv(df, timestamp, 'close')

    equity = calc_mark_to_market_equity(quantities, current_close, prev_close, prev_equity)
    next_close = build_close_marks(current_close, prev_close)
    return equity, next_close
