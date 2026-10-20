"""与策略无关的组合盯市计算和收盘估值基准维护。"""

from collections.abc import Mapping

from strategy_common import getv


def calc_mark_to_market_equity(
        quantities: Mapping[str, float], current_close: Mapping[str, float],
        prev_close: Mapping[str, float], prev_equity: float) -> float:
    """按持仓数量和价格快照返回盯市后的权益，不修改任何输入。

    quantities 为带符号的持仓数量，current_close 为当日有行情的价格，
    prev_close 为上次估值价格，prev_equity 为上次总权益。
    无当日价格的持仓不产生盈亏；缺少上次价格时以当日价格为基准。
    按传入的旧基准计算，可以独立重复调用。
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
    """合并当日价格快照和旧基准，返回独立的完整价格基准字典。

    current_close 中的键覆盖旧值，其他键保留；两个输入都不修改。
    无行情的标的不应放入快照，其既有基准将保留在返回结果中。
    """
    return {**prev_close, **current_close}


def calc_equity_close(df_all: dict, pos: dict, prev_close: dict, time, prev_equity):
    """用收盘价计算持仓权益，返回 (equity, next_close)，不修改输入。

    df_all 为按标的组织的行情 DataFrame，
    pos 为含 qty 的持仓字典，
    time 为当前时刻，
    prev_equity 为上次权益；行情、持仓及旧价格基准均只读。
    仅读取当日有行情的持仓，缺行情则保留原基准，缺基准则使用当日价。
    使用同一份价格快照计算权益并构造完整新基准；无效价格保持 NaN 传播。
    开仓基准由调用方按买入价初始化。本入口无跨调用的按日去重机制。
    """
    quantities = {}
    current_close = {}
    for sym, position in list(pos.items()):
        df = df_all[sym]
        if time in df.index:
            quantities[sym] = position['qty']
            current_close[sym] = getv(df, time, 'close')

    equity = calc_mark_to_market_equity(quantities, current_close, prev_close, prev_equity)
    next_close = build_close_marks(current_close, prev_close)
    return equity, next_close
