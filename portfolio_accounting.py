"""与策略无关的组合盯市计算和收盘估值基准维护。"""

from collections.abc import Mapping

from money import calc_price_pnl, sum_money
from strategy_common import Position, getv


def calc_mark_to_market_equity(
        quantities: Mapping[str, float], current_close: Mapping[str, float],
        prev_close: Mapping[str, float], prev_equity: float) -> float:
    """按实际持仓股数和原始价差计算盯市后的权益。

    Args:
        quantities: 标的代码到带符号持仓股数的映射。
        current_close: 标的代码到当日原始每股收盘价的映射，仅包含有行情的标的。
        prev_close: 标的代码到上次原始每股估值价格的映射，与当日价格尺度一致。
        prev_equity: float，上次账户总权益；所有输入只读。

    Returns:
        float，旧权益及各标的价差盈亏分别按分四舍五入后求和。缺当日价格不产生
        盈亏，缺旧基准以当日价格为基准，NaN 价格按运算规则传播。
        每次均按传入的旧基准计算，无跨调用去重机制。
    """
    amounts = [prev_equity]
    for sym, qty in quantities.items():
        if sym in current_close:
            price = current_close[sym]
            previous = prev_close.get(sym, price)
            amounts.append(calc_price_pnl(qty, price, previous))
    return sum_money(amounts)


def calc_equity_close(
        market_data: dict,
        positions: dict[str, Position],
        prev_close: dict,
        timestamp,
        prev_equity
        ):
    """用同一份原始收盘价快照计算权益和下一次估值基准。

    Args:
        market_data: 按标的代码组织的行情 DataFrame 字典，包含 raw_close 原始价列。
        positions: 当前 Position 持仓字典，每条记录的 trade_qty 为带符号实际股数。
        prev_close: 上次原始每股估值价格字典，开仓时按原始买入价初始化。
        timestamp: 与行情索引兼容的当前估值时刻。
        prev_equity: float，上次账户总权益；行情、持仓及旧基准输入只读。

    Returns:
        tuple[float, dict]，即 (equity, next_close)。权益按原始价差计算并按分记账；
        新基准保留全部旧键，更新当日有行情的持仓。缺行情保留旧基准，
        缺旧基准使用当日原始价；重复索引取最后一条，无效原始价按 NaN 传播，
        不回退到复权 close。保存的入场价不随估值更新。
        每个可估值持仓仅读取一次价格，无跨调用的按日去重机制。
    """
    quantities = {}
    current_close = {}
    for sym, position in list(positions.items()):
        df = market_data[sym]
        if timestamp in df.index:
            quantities[sym] = position.trade_qty
            current_close[sym] = getv(df, timestamp, 'raw_close')

    equity = calc_mark_to_market_equity(quantities, current_close, prev_close, prev_equity)
    # 非常有意思的代码
    next_close = {**prev_close, **current_close}
    return equity, next_close
