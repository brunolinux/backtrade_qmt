# coding: gbk
"""QMT 内置 Python 实盘模型；每日只更新下方配置区，不读取外部文件。

09:35 卖出超额/非目标持仓，09:36 买入缺口，仅在对应一分钟内执行。
ETF volume 单位为份（不是手），买入按 100 份取整。每个方向/标的每天
只提交一次，IOC 部分成交或撤销后不自动补单。请每天重新启动模型。

SH: prType=42, price=0（涨跌停保护价）；SZ: prType=47, price=-1。
官方文档：https://knowledge.thinktrader.net/docs/python/enum_constants.html
本文件以 GBK 保存，可直接导入 QMT 编辑器。
此文件供 QMT 注入 passorder/get_trade_detail_data，不可直接用普通 Python 交易。
"""

import datetime as dt
import math
import threading
from types import SimpleNamespace


ACCOUNT_ID = "xxx"
ACCOUNT_TYPE = "STOCK"
# 每日手动更新：信号日期、执行日期、执行后目标持仓（份）。
SIGNAL_DATE = dt.date(2026, 10, 16)
TRADE_DATE = dt.date(2026, 10, 19)
TARGET_QUANTITIES = {
    "159650.SZ": 400,
    "159941.SZ": 21800,
    "159981.SZ": 11800,
    "512800.SH": 118400,
}
STRATEGY_NAME = "qmt_portfolio_v2"
REFRESH_SECONDS = 3
BUY_LOT_SIZE = 100
# 仅用于预估可负担数量；实际费用/成交价格仍由券商决定。
BUY_PRICE_BUFFER = 0.02
FEE_RATE_RESERVE = 0.001
MIN_FEE_RESERVE = 5.0
TERMINAL_ORDER_STATUSES = {53, 54, 56, 57}


def _now():
    """使用北京时间，避免机器系统时区不同。"""
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).replace(tzinfo=None)


def _symbol(code):
    if len(code) != 6 or not code.isdigit():
        raise ValueError("非法 ETF 代码: " + code)
    if code.startswith("15"):
        return code + ".SZ"
    if code.startswith("5"):
        return code + ".SH"
    raise ValueError("无法识别 ETF 交易所: " + code)


def _validate_portfolio(C, today):
    """仅校验代码中的配置与 QMT 交易日，不读取文件。"""
    if type(SIGNAL_DATE) is not dt.date or type(TRADE_DATE) is not dt.date:
        raise ValueError("SIGNAL_DATE/TRADE_DATE 必须为 dt.date 日期")
    if today != TRADE_DATE:
        raise ValueError("今天 {} 不是计划交易日 {}，请更新代码日期".format(today, TRADE_DATE))
    if not isinstance(TARGET_QUANTITIES, dict):
        raise ValueError("TARGET_QUANTITIES 必须为代码到份额的字典")
    for code, qty in TARGET_QUANTITIES.items():
        if not isinstance(code, str) or len(code) != 9 or _symbol(code[:6]) != code:
            raise ValueError("ETF 代码或交易所后缀错误: {}".format(code))
        if type(qty) is not int or qty < 0 or qty % BUY_LOT_SIZE:
            raise ValueError("目标数量必须为非负整数且为 100 份整数倍: {}={}".format(code, qty))
    yesterday = (today - dt.timedelta(days=1)).strftime("%Y%m%d")
    days = C.get_trading_dates("000001.SH", "", yesterday, 1, "1d")
    if not days:
        raise ValueError("QMT 未返回前一个交易日，无法校验日期")
    previous = dt.datetime.strptime(days[-1], "%Y%m%d").date()
    if SIGNAL_DATE != previous:
        raise ValueError("信号日期 {}，应为前一个交易日 {}".format(SIGNAL_DATE, previous))
    current_days = C.get_trading_dates("000001.SH", "", today.strftime("%Y%m%d"), 1, "1d")
    if not current_days or current_days[-1] != today.strftime("%Y%m%d"):
        raise ValueError("今天不是交易日，退出模型")


def _snapshot():
    accounts = get_trade_detail_data(ACCOUNT_ID, ACCOUNT_TYPE, "ACCOUNT")
    if len(accounts) != 1:
        raise ValueError("无法获取唯一账户资金信息")
    account = accounts[0]
    for value in (account.m_dAvailable, account.m_dBalance, account.m_dInstrumentValue):
        if not math.isfinite(value) or value < 0:
            raise ValueError("账户资金数据无效")
    positions = {}
    for p in get_trade_detail_data(ACCOUNT_ID, ACCOUNT_TYPE, "POSITION"):
        code = p.m_strInstrumentID + "." + p.m_strExchangeID
        total, usable = int(p.m_nVolume), int(p.m_nCanUseVolume)
        if total < 0 or usable < 0 or usable > total:
            raise ValueError("持仓数量无效: " + code)
        old = positions.get(code, (0, 0))
        positions[code] = (old[0] + total, old[1] + usable)
    orders = get_trade_detail_data(ACCOUNT_ID, ACCOUNT_TYPE, "ORDER")
    return account, positions, orders


def init(C):
    """校验失败时退出，不注册行情或定时器。"""
    C.qmt_state = SimpleNamespace(enabled=False)
    try:
        today = _now().date()
        _validate_portfolio(C, today)
        if not ACCOUNT_ID or ACCOUNT_ID == "xxx":
            raise ValueError("请先填写 ACCOUNT_ID")
        C.set_account(ACCOUNT_ID)
        account, positions, orders = _snapshot()
        C.qmt_state = SimpleNamespace(
            enabled=True, day=today, positions=positions,
            market_value=account.m_dInstrumentValue, total_asset=account.m_dBalance,
            submitted=set(), reservations={}, last_refresh=None, lock=threading.Lock(),
        )
        print("账户 {} 总市值 {} 总资产 {} 可用资金 {} 持仓 {}".format(
            ACCOUNT_ID, account.m_dInstrumentValue, account.m_dBalance,
            account.m_dAvailable, positions))

        def on_quote(data):
            # 订阅事件与定时事件共用入口，最多每三秒检查一次。
            refresh(C)

        for code in sorted(set(TARGET_QUANTITIES) | set(positions)):
            C.subscribe_quote(code, period="tick", callback=on_quote)
        C.run_time("refresh", "{}nSecond".format(REFRESH_SECONDS),
                   _now().strftime("%Y-%m-%d %H:%M:%S"))
    except Exception as exc:
        C.qmt_state.enabled = False
        print("错误：初始化失败，退出模型：{}".format(exc))
        raise SystemExit(1)


def _order_id(day, side, code):
    return "qmt_{}_{}_{}".format(day.strftime("%Y%m%d"), side, code.replace(".", ""))


def _submit(C, side, code, quantity, previous_ids):
    state = C.qmt_state
    order_id = _order_id(state.day, side, code)
    if quantity <= 0 or order_id in state.submitted or order_id in previous_ids:
        return False
    if code.endswith(".SH"):
        pr_type, price = 42, 0
    elif code.endswith(".SZ"):
        pr_type, price = 47, -1
    else:
        raise ValueError("不支持该交易所的即时成交指令: " + code)
    # 先标记再调用；异常可能意味着已送达券商，禁止自动重试。
    state.submitted.add(order_id)
    passorder(side, 1101, ACCOUNT_ID, code, pr_type, price, int(quantity),
              STRATEGY_NAME, 1, order_id, C)
    print("已提交 {} {} {} 份，委托标识 {}；成交以券商回报为准".format(
        "买入" if side == 23 else "卖出", code, quantity, order_id))
    return True


def refresh(C):
    """每三秒处理一个定时事件，不阻塞、不 sleep、不追补错过的交易窗口。"""
    state = C.qmt_state
    if not state.enabled or not state.lock.acquire(blocking=False):
        return
    try:
        now = _now()
        if now.date() != state.day:
            state.enabled = False
            print("交易日已变更，请更新代码中的日期和目标持仓并重启模型")
            return
        if (now.hour, now.minute) not in ((9, 35), (9, 36)) or not C.is_last_bar():
            return
        if state.last_refresh is not None and (now - state.last_refresh).total_seconds() < REFRESH_SECONDS:
            return
        state.last_refresh = now
        account, positions, orders = _snapshot()
        state.positions = positions
        state.market_value = account.m_dInstrumentValue
        previous_ids = {o.m_strRemark for o in orders}
        if any(o.m_nOrderStatus not in TERMINAL_ORDER_STATUSES for o in orders):
            print("仍有未完成委托，等待下一次刷新后检查")
            return
        if now.minute == 35:
            for code, (total, usable) in sorted(positions.items()):
                excess = total - TARGET_QUANTITIES.get(code, 0)
                quantity = min(max(excess, 0), usable)
                # 部分减仓按整手，全部卖出允许零头。
                if quantity != total:
                    quantity = quantity // BUY_LOT_SIZE * BUY_LOT_SIZE
                if excess > usable:
                    print("{} 超额 {} 份，但仅 {} 份可卖".format(code, excess, usable))
                _submit(C, 24, code, quantity, previous_ids)
            return
        # 未完成委托可能冻结资金或改变仓位，不与手动/其他模型委托并发买入。
        if any("_24_" in order_id and order_id not in previous_ids
               for order_id in state.submitted):
            print("卖单尚未出现在券商委托列表，暂不买入")
            return
        ticks = C.get_full_tick(list(TARGET_QUANTITIES))
        budget = max(0, float(account.m_dAvailable) - sum(
            cost for order_id, cost in state.reservations.items() if order_id not in previous_ids))
        for code, target in TARGET_QUANTITIES.items():
            need = target - positions.get(code, (0, 0))[0]
            order_id = _order_id(state.day, 23, code)
            if need <= 0 or order_id in previous_ids or order_id in state.submitted:
                continue
            tick = ticks.get(code, {})
            last = float(tick.get("lastPrice", 0))
            if not math.isfinite(last) or last <= 0:
                print("{} 缺少有效报价，暂不买入".format(code))
                continue
            asks = [float(p) for p in tick.get("askPrice", [])
                    if math.isfinite(float(p)) and float(p) > 0]
            estimate = max([last] + asks) * (1 + BUY_PRICE_BUFFER)
            affordable = max(0, int((budget - MIN_FEE_RESERVE) /
                                   (estimate * (1 + FEE_RATE_RESERVE))))
            quantity = min(need, affordable) // BUY_LOT_SIZE * BUY_LOT_SIZE
            if quantity <= 0:
                print("{} 资金或整手数量不足，暂不买入".format(code))
                continue
            if _submit(C, 23, code, quantity, previous_ids):
                cost = estimate * quantity + max(
                    MIN_FEE_RESERVE, estimate * quantity * FEE_RATE_RESERVE)
                state.reservations[order_id] = cost
                budget -= cost
    except Exception as exc:
        state.enabled = False
        print("错误：停止下单，请核对券商委托后重启：{}".format(exc))
    finally:
        state.lock.release()


def handlebar(C):
    """保留 QMT 模型入口；历史 K 线不触发订单。"""
    pass
