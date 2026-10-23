# coding: gb2312
"""Submit fixed ETF target differences from the embedded QMT Python runtime."""

import datetime as dt
import math
import re
import threading
from collections import namedtuple
from types import SimpleNamespace


ACCOUNT_ID = "xxx"
ACCOUNT_TYPE = "STOCK"
SIGNAL_DATE = dt.date(2026, 10, 16)
TRADE_DATE = dt.date(2026, 10, 19)
TARGET_QUANTITIES = {
    "159650.SZ": 400,
    "159941.SZ": 21800,
    "159981.SZ": 11800,
    "512800.SH": 118400,
}
TOTAL_VALUE = 240000
STRATEGY_NAME = "ETF_TARGET"

BEIJING = dt.timezone(dt.timedelta(hours=8))

# total 为实际持仓份数；available 为当前可卖份数，可能受 T+1 限制。
Holding = namedtuple("Holding", "total available")

# balance 为账户总资产；available 为可用资金；market_value 为持仓市值。
# holdings 将每个 ETF 代码映射到唯一一条 Holding 记录。
Snapshot = namedtuple("Snapshot", "balance available market_value holdings")

# code 为带交易所后缀的代码；operation 为买入 23 或卖出 24；quantity 为委托份数。
PlannedOrder = namedtuple("PlannedOrder", "code operation quantity")

# QMT rewinds ContextInfo attributes between ticks. Keep trading state outside it.
_state = None


def _now():
    """Return the current Beijing time independently of the machine timezone."""
    return dt.datetime.now(BEIJING)


def _valid_symbol(code):
    """Return whether a code belongs to the supported ETF symbol range."""
    return isinstance(code, str) and re.fullmatch(r"(?:15[0-9]{4}\.SZ|5[0-9]{5}\.SH)", code) is not None


def _money(value, label):
    """Validate a finite nonnegative account amount and return it as float."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Invalid amount: " + label)
    if not math.isfinite(value) or value < 0:
        raise ValueError("Invalid amount: " + label)
    return float(value)


def _validate_config(today):
    """Validate manually copied constants before accessing the account.

    Args:
        today: Current Beijing calendar date.

    Raises:
        ValueError: A configuration value is invalid or out of date.
    """
    if not isinstance(ACCOUNT_ID, str) or not ACCOUNT_ID.strip() or ACCOUNT_ID == "xxx":
        raise ValueError("Configure ACCOUNT_ID before starting")
    if type(SIGNAL_DATE) is not dt.date or type(TRADE_DATE) is not dt.date:
        raise ValueError("SIGNAL_DATE and TRADE_DATE must be dates")
    if today != TRADE_DATE:
        raise ValueError("Beijing today does not match TRADE_DATE")
    if not isinstance(TARGET_QUANTITIES, dict):
        raise ValueError("TARGET_QUANTITIES must be a dictionary")
    for code, quantity in TARGET_QUANTITIES.items():
        if not _valid_symbol(code):
            raise ValueError("Unsupported ETF code: " + str(code))
        if type(quantity) is not int or quantity < 0 or quantity % 100:
            raise ValueError("Target must be a nonnegative integer multiple of 100: " + code)
    if _money(TOTAL_VALUE, "TOTAL_VALUE") <= 0:
        raise ValueError("TOTAL_VALUE must be positive")


def _validate_calendar(C):
    """Check execution and signal dates using QMT's daily trading calendar."""
    days = C.get_trading_dates("000001.SH", "", TRADE_DATE.strftime("%Y%m%d"), 2, "1d")
    expected = [SIGNAL_DATE.strftime("%Y%m%d"), TRADE_DATE.strftime("%Y%m%d")]
    if days is None or list(days) != expected:
        raise ValueError("Trading calendar missing or SIGNAL_DATE is not the previous trading day")


def _snapshot():
    """Return a validated account snapshot with one holding per ETF code.

    Returns:
        Snapshot containing total assets, cash, market value and new holdings.

    Raises:
        ValueError: Account or holding data is missing or invalid.
    """
    accounts = get_trade_detail_data(ACCOUNT_ID, ACCOUNT_TYPE, "ACCOUNT")
    if accounts is None or len(accounts) != 1:
        raise ValueError("Expected exactly one account snapshot")
    account = accounts[0]
    balance = _money(getattr(account, "m_dBalance", None), "m_dBalance")
    available = _money(getattr(account, "m_dAvailable", None), "m_dAvailable")
    market_value = _money(getattr(account, "m_dInstrumentValue", None), "m_dInstrumentValue")
    if TOTAL_VALUE > balance:
        raise ValueError("TOTAL_VALUE exceeds actual account assets")
    positions = get_trade_detail_data(ACCOUNT_ID, ACCOUNT_TYPE, "POSITION")
    if positions is None:
        raise ValueError("Missing position snapshot")
    holdings = {}
    for item in positions:
        code = "{}.{}".format(item.m_strInstrumentID, item.m_strExchangeID)
        if not _valid_symbol(code):
            continue
        if code in holdings:
            raise ValueError("Duplicate ETF position: " + code)
        total = item.m_nVolume
        usable = item.m_nCanUseVolume
        if type(total) is not int or type(usable) is not int or not 0 <= usable <= total:
            raise ValueError("Invalid holding quantities: " + code)
        holdings[code] = Holding(total, usable)
    return Snapshot(balance, available, market_value, holdings)


def build_plans(holdings, targets):
    """Return immutable sell and buy plans without changing either input.

    Args:
        holdings: Mapping of supported ETF codes to initial Holding records.
        targets: Mapping of ETF codes to absolute target quantities in shares.

    Returns:
        Pair of tuples containing sells and buys as PlannedOrder records.
        Partial differences are rounded down to lots of 100; liquidation
        includes every available share, including odd lots.
    """
    sells = []
    buys = []
    for code in sorted(set(holdings) | set(targets)):
        holding = holdings.get(code, Holding(0, 0))
        target = targets.get(code, 0)
        difference = target - holding.total
        if difference > 0:
            quantity = difference // 100 * 100
            if quantity:
                buys.append(PlannedOrder(code, 23, quantity))
        elif difference < 0:
            quantity = min(-difference, holding.available)
            if target != 0:
                quantity = quantity // 100 * 100
            if quantity:
                sells.append(PlannedOrder(code, 24, quantity))
    return tuple(sells), tuple(buys)


def init(C):
    """Validate static configuration and enable QMT native account callbacks."""
    global _state
    _state = SimpleNamespace(ready=False, configured=False)
    try:
        _validate_config(_now().date())
        C.set_account(ACCOUNT_ID)
        _state.configured = True
    except Exception as exc:
        print("Initialization failed: {}".format(exc))
        exit()


def after_init(C):
    """Finish initialization where QMT makes the trading calendar available."""
    state = _state
    if state is None or not state.configured or state.ready:
        return
    try:
        _validate_config(_now().date())
        _validate_calendar(C)
        state.snapshot = _snapshot()
        state.sell_plan, state.buy_plan = build_plans(state.snapshot.holdings, TARGET_QUANTITIES)
        state.account_id = ACCOUNT_ID
        state.trade_date = TRADE_DATE
        state.lock = threading.Lock()
        state.running = False
        state.sell_attempted = False
        state.buy_attempted = False
        state.attempts = {}
        print("Initial account: assets={:.2f}, cash={:.2f}, market_value={:.2f}".format(
            state.snapshot.balance, state.snapshot.available, state.snapshot.market_value))
        print("Sell plan: {}".format(state.sell_plan))
        print("Buy plan: {}".format(state.buy_plan))
        print("Partial differences rounded down to 100 shares; liquidation includes available odd lots")
        state.ready = True
        C.run_time("refresh", "3nSecond", _now().strftime("%Y-%m-%d %H:%M:%S"))
    except Exception as exc:
        state.ready = False
        state.configured = False
        print("Initialization failed: {}".format(exc))


def _submit_order(C, state, order):
    """Attempt a planned order once, isolating synchronous submission errors."""
    order_id = "{}-{}-{}-{}".format(
        STRATEGY_NAME, state.trade_date.strftime("%Y%m%d"), order.operation, order.code)
    # Skip orders already attempted.
    if order_id in state.attempts:
        return
    state.attempts[order_id] = order
    price_type, price = (42, 0) if order.code.endswith(".SH") else (47, -1)
    print("Submitting {} {} shares={} id={}".format(
        "BUY" if order.operation == 23 else "SELL", order.code, order.quantity, order_id))
    try:
        passorder(order.operation, 1101, state.account_id, order.code,
                  price_type, price, order.quantity, STRATEGY_NAME, 2, order_id, C)
        print("Submission call returned: {} (await order/deal callbacks)".format(order_id))
    except Exception as exc:
        print("Submission failed: {} {}; no retry".format(order_id, exc))


def refresh(C):
    """Submit each due fixed phase once; never wait for an order to fill."""
    state = _state
    if state is None or not state.ready:
        return
    with state.lock:
        if state.running:
            return
        state.running = True
    try:
        now = _now()
        if now.date() != state.trade_date:
            return
        for flag, threshold, plan in (
                ("sell_attempted", dt.time(9, 35), state.sell_plan),
                ("buy_attempted", dt.time(9, 36), state.buy_plan)):
            due = dt.datetime.combine(state.trade_date, threshold).replace(tzinfo=BEIJING)
            with state.lock:
                # Skip phases that are not due or already attempted.
                if now <= due or getattr(state, flag):
                    continue
                setattr(state, flag, True)
            for order in plan:
                _submit_order(C, state, order)
    finally:
        with state.lock:
            state.running = False


def handlebar(C):
    """Leave historical and live bar events free of order submission."""
    pass


def _field(record, name, default=None):
    """Read an optional SDK field without breaking a native callback."""
    try:
        value = getattr(record, name, default)
        return default if value is None else value
    except Exception:
        return default


def _callback_order(C, record, error_args=False):
    """Return the registered plan record only for this account and remark."""
    state = _state
    if state is None or not state.ready:
        return None
    if error_args:
        account_id = _field(record, "accountID")
        combined = _field(record, "strategyName", "")
        if not isinstance(combined, str):
            return None
        strategy, separator, order_id = combined.partition("_&&&_")
        if not separator or strategy != STRATEGY_NAME:
            return None
    else:
        account_id = _field(record, "m_strAccountID")
        order_id = _field(record, "m_strRemark")
    if account_id != state.account_id or not isinstance(order_id, str):
        return None
    order = state.attempts.get(order_id)
    return (order_id, order) if order is not None else None


def _order_label(order_id, order):
    """Describe an order using its fixed plan rather than optional SDK fields."""
    return "{} {} id={}".format("BUY" if order.operation == 23 else "SELL", order.code, order_id)


def order_callback(C, orderInfo):
    """Report native order status without submitting or changing the plan."""
    matched = _callback_order(C, orderInfo)
    if matched is None:
        return
    status = _field(orderInfo, "m_nOrderStatus", "unknown")
    statuses = {
        49: "WAIT_REPORTING",
        50: "REPORTED",
        51: "CANCEL_PENDING",
        52: "PART_CANCEL_PENDING",
        53: "PART_CANCELLED",
        54: "CANCELLED",
        55: "PART_FILLED",
        56: "FILLED",
        57: "REJECTED"
        }
    status_name = statuses.get(status, "unknown")
    if _field(orderInfo, "m_nOrderSubmitStatus") == 52:
        status_name = "REJECTED"
    print("Order status: {} status={}({}) filled={} error={} reason={} cancel={}".format(
        _order_label(*matched), status_name, status,
        _field(orderInfo, "m_nVolumeTraded", "unknown"),
        _field(orderInfo, "m_nErrorID", "unknown"),
        _field(orderInfo, "m_strErrorMsg", "unknown"),
        _field(orderInfo, "m_strCancelInfo", "unknown")))


def deal_callback(C, dealInfo):
    """Report actual fill price, quantity and broker-provided fee if present."""
    matched = _callback_order(C, dealInfo)
    if matched is None:
        return
    fee = "unknown"
    for field in ("m_dCommission", "m_dComission"):
        value = _field(dealInfo, field)
        if isinstance(value, (int, float)) and  \
           not isinstance(value, bool) and      \
           math.isfinite(value) and value >= 0:
            fee = "{:.2f}".format(value)
            break
    print("Deal: {} price={} shares={} fee={} trade_id={}".format(
        _order_label(*matched), _field(dealInfo, "m_dPrice", "unknown"),
        _field(dealInfo, "m_nVolume", "unknown"), fee,
        _field(dealInfo, "m_strTradeID", "unknown")))


def orderError_callback(C, orderArgs, errMsg):
    """Report a native passorder error and leave all other attempts enabled."""
    matched = _callback_order(C, orderArgs, error_args=True)
    if matched is not None:
        print("Order error: {} reason={}; no retry".format(_order_label(*matched), errMsg))
