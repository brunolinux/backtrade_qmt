"""与策略无关的组合盯市计算和收盘估值基准维护。"""

from collections.abc import Mapping, MutableMapping

from strategy_common import getv


def calc_mark_to_market_equity(
        quantities: Mapping[str, float], current_close: Mapping[str, float],
        prev_close: Mapping[str, float], prev_equity: float) -> float:
    """按持仓数量和价格快照返回盯市后的权益，不修改任何输入。

    quantities 为带符号的持仓数量，current_close 为当日有行情的价格，
    prev_close 为上次估值价格，prev_equity 为上次总权益。
    无当日价格的持仓不产生盈亏；缺少上次价格时以当日价格为基准。
    须在 update_close_marks 推进基准之前调用，可以独立重复计算。
    """
    equity = prev_equity
    for sym, qty in quantities.items():
        if sym in current_close:
            price = current_close[sym]
            previous = prev_close.get(sym, price)
            equity += qty * (price - previous)
    return equity


def update_close_marks(
        current_close: Mapping[str, float],
        prev_close: MutableMapping[str, float]) -> None:
    """将当日价格快照 current_close 写入 prev_close，无返回值。

    仅原地更新 prev_close 中快照对应的键，保留其他键，不修改快照。
    不计算权益；调用方须先完成盯市计算，并仅传入应推进基准的价格。
    无行情的标的不应放入快照，其既有基准将保持不变。
    """
    prev_close.update(current_close)


def update_equity_close(df_all: dict, pos: dict, prev_close: dict, time, prev_equity):
    """用收盘价结算持仓，返回盯市权益，并原地推进 prev_close 基准。

    df_all 为按标的组织的行情 DataFrame，pos 为含 qty 的持仓字典，
    time 为当前时刻，prev_equity 为上次权益；不修改行情及持仓。
    仅读取当日有行情的持仓，缺行情则保留原基准，缺基准则使用当日价。
    使用同一份价格快照先计算权益再更新基准；无效价格保持 NaN 传播。
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
    update_close_marks(current_close, prev_close)
    return equity
