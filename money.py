"""实际资金结果的十进制计算；行情与信号不在此处舍入。"""

from collections.abc import Iterable
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext


def round_money(amount: float | Decimal) -> float:
    """将金额按绝对值半入到分。

    Args:
        amount: 待记账金额，NaN 与无穷值保持非有限语义。

    Returns:
        按分量化后转为 float 的金额，保持现有数值接口。
    """
    value = Decimal(str(amount))
    return float(value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                 if value.is_finite() else value)


def calc_notional(quantity: float, raw_price: float) -> float:
    """用完整原始价计算市值并按分记录。

    Args:
        quantity: 带符号实际份数。
        raw_price: 未舍入的原始每份价格。

    Returns:
        按分处理的市值，非有限结果继续传播。
    """
    with localcontext() as context:
        context.traps[InvalidOperation] = False
        return round_money(Decimal(str(quantity)) * Decimal(str(raw_price)))


def calc_price_pnl(quantity: float, current_price: float, previous_price: float) -> float:
    """用原始价差计算实际盈亏并按分记录。

    Args:
        quantity: 带符号实际份数。
        current_price: 当日原始价，保持行情精度。
        previous_price: 旧原始价，保持行情精度。

    Returns:
        按分处理的盈亏，不提前舍入每份价差。
    """
    with localcontext() as context:
        context.traps[InvalidOperation] = False
        return round_money(Decimal(str(quantity)) * (
            Decimal(str(current_price)) - Decimal(str(previous_price))))


def sum_money(amounts: Iterable[float]) -> float:
    """逐项按分处理金额并以十进制求和。

    Args:
        amounts: 独立记账金额序列，输入只读。

    Returns:
        金额合计；空序列返回零，NaN 传播而非跳过。
    """
    with localcontext() as context:
        context.traps[InvalidOperation] = False
        return float(sum((Decimal(str(round_money(value))) for value in amounts), Decimal(0)))
