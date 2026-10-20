"""两个动量策略共用的行情、指标、风险、持仓和交易记录工具。

本模块不依赖策略或记账模块；函数保留原有数值语义及持仓更新边界。
策略专有的信号、选股规则和回测编排由各策略自身维护。
"""

from typing import NamedTuple

import pandas as pd
import numpy as np


def getv(df, t, col):
    """改进的值获取函数"""
    try:
        v = df.loc[t, col]
        if isinstance(v, pd.Series):
            return float(v.iloc[-1])
        return float(v)
    except:
        return np.nan


def calc_quantity(quantity, min_num):
    return int(quantity / min_num) * min_num


def atr(df_single, window=10):
    """改进的ATR计算
    df_single: 单品种数据
    window: 滚动窗口
    """
    # talib conda
    high_low = df_single["high"] - df_single["low"]
    high_close = (df_single["high"] - df_single["close"].shift()).abs()
    low_close = (df_single["low"] - df_single["close"].shift()).abs()

    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    # 使用rolling mean替代EMA，更稳定
    return tr.rolling(window).mean()


def calc_corr_matrix(df_all: dict, name: str = "close") -> pd.DataFrame:
    """
    计算互相关矩阵
    df_all: 多品种数据字典
    name: 计算互相关的列名
    """
    rets = {}

    for sym, df in df_all.items():
        if name not in df.columns:
            continue

        s = df[name].sort_index()
        ret = np.log(s).diff()
        rets[sym] = ret

    ret_df = pd.DataFrame(rets)
    ret_df = ret_df.dropna(how="all")
    corr = ret_df.corr()
    return corr


def calc_position_size(equity, atr_value, px, atr_stop, max_risk_per_trade):
    """
    改进的仓位计算：基于风险的仓位管理
    equity: 当前市值
    atr_value: 品种的 atr 数值
    px: 品种每手价格
    atr_stop: 止损 atr 倍率 (参数)
    max_risk_per_trade: 每笔交易的最大损失 (百分比)
    """
    # 该品种每手最大可能损失
    risk_per_share = atr_value * atr_stop
    if risk_per_share <= 0:
        return 0

    # 每笔交易的最大允许损失
    risk_amount = equity * max_risk_per_trade
    shares = calc_quantity(risk_amount/risk_per_share, 100)

    # 确保仓位不超过市值
    notional = shares * px
    if notional > equity:
        shares = calc_quantity(equity / px, 100)

    return shares


def calc_leverage_by_vol(equity_hist, window_vol, annual_factor, target_vol, min_lev, max_lev):
    """
    根据波动率调整杠杆率
    equity_hist: 市值曲线
    window_vol: 计算波动率的窗口长度
    annual_factor: 一年的 bar 数目 (如果是日线, 则为 252)
    target_vol: 目标年化波动率
    min_lev: 最低杠杆率
    max_lev: 最大杠杆率
    """
    if len(equity_hist) < window_vol:
        return 1.0

    eq = np.array(equity_hist[-window_vol:])
    ret = np.diff(np.log(eq))

    realized_vol = np.std(ret) * np.sqrt(annual_factor)

    vol_scale = target_vol / (realized_vol + 1e-6)
    vol_scale = np.clip(vol_scale, min_lev, max_lev)
    return vol_scale


class Trade(NamedTuple):
    """已生成的交易记录，字段顺序与交易表一致。"""

    symbol: str              # 品种代码
    side: int                # 持仓方向
    entry_time: pd.Timestamp  # 买入时刻
    exit_time: pd.Timestamp  # 卖出时刻
    pnl: float               # 交易收益
    exit_reason: str         # 卖出原因


def update_stop_price(df_all: dict, pos: dict, time, atr_stop):
    """
    动态移动止损：价格上升时提高止损
    df_all: 多品种字典
    pos: 仓位字典 (会更新)
    time: 当前时刻
    atr_stop: 回撤倍数
    """
    for sym, p in pos.items():
        df = df_all[sym]
        if time not in df.index:
            continue

        c = getv(df, time, "close")
        new_stop = c - atr_stop * p["atr"]
        p["stop"] = max(p["stop"], new_stop)


def update_portfolio(df_all: dict, pos: dict, time, real_equity, pos_change_threshold):
    """
    调整仓位
    df_all: 多品种字典
    pos: 原仓位字典（不修改，返回调整后的仓位副本）
    time: 当前时刻
    real_equity: 实际市值
    pos_change_threshold: 仓位变更阈值
    """
    if len(pos) == 0:
        return {}

    total_risk = sum(1.0 / p["atr"] for p in pos.values())

    # 在新的仓位上管理
    new_pos = {}
    for sym, p in pos.items():
        new_pos[sym] = p.copy()
        df = df_all[sym]
        if time not in df.index:
            # 如果当天不能交易, 仓位不变
            continue

        px = getv(df, time, "close")

        risk_weight = (1.0/p["atr"])/total_risk
        target_notional = real_equity * risk_weight
        target_qty = calc_quantity(target_notional/px, 100)

        # 平滑调整仓位，避免频繁调仓
        cur_qty = abs(p["qty"])
        if abs(target_qty - cur_qty) > cur_qty*pos_change_threshold:
            new_pos[sym]["qty"] = target_qty * p["side"]
        # 更新时间
        new_pos[sym]["entry_time"] = time
        new_pos[sym]["entry"] = px

    # 获取股票总仓位 (只考虑可以交易的)
    unchanged_money = 0
    unchanged_sym_list = []
    money_list = []
    sym_list = []
    for sym, p in new_pos.items():
        df = df_all[sym]
        if time not in df.index:
            # 如果当天不能交易, 仓位不变
            unchanged_money += p["qty"] * p["entry"]
            unchanged_sym_list.append(sym)
        else:
            money_list.append(p["qty"] * p["entry"])
            sym_list.append(sym)

    money_list = np.array(money_list)

    # 如果现金不够, 则优先选择权重大的
    cash = real_equity - np.sum(money_list) - unchanged_money
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
            if count > real_equity:
                left = real_equity - (count - money_list[idx])
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


def update_trades(df_all:dict, time, new_pos: dict, old_pos: dict) -> list[Trade]:
    """
    根据仓位调整返回交易记录列表，不修改 old_pos。
    数量不变时会将 new_pos 的入场时间和价格恢复为原值。
    """
    trades: list[Trade] = []
    old_sym = set(old_pos.keys())
    new_sym = set(new_pos.keys())

    common_sym = new_sym.intersection(old_sym)
    close_sym = old_sym.difference(new_sym)

    # 关闭仓位
    for sym in close_sym:
        p = old_pos[sym]
        # 如果时间相同, 则不用交易
        if p["entry_time"] == time:
            continue

        # 如果仓位为 0, 则不用交易
        if p["qty"] == 0:
            continue

        df = df_all[sym]
        px = getv(df, time, "close")
        pnl = p["qty"] * (px - p["entry"])
        reason = "止盈" if pnl > 0 else "止损"
        trade_info = Trade(
            symbol=sym,
            side=p["side"],
            entry_time=p["entry_time"],
            exit_time=time,
            pnl=float(pnl),
            exit_reason=reason,
        )
        trades.append(trade_info)

    # 切换仓位
    for sym in common_sym:
        # 如果时间相同， 则跳过
        if new_pos[sym]["entry_time"] == old_pos[sym]["entry_time"]:
            continue

        # 如果仓位相同，则更新新的时间为老的时间
        if new_pos[sym]["qty"] == old_pos[sym]["qty"]:
            new_pos[sym]["entry_time"] = old_pos[sym]["entry_time"]
            new_pos[sym]["entry"] = old_pos[sym]["entry"]
            continue

        if old_pos[sym]["qty"] == 0:
            continue

        df = df_all[sym]
        px = getv(df, time, "close")
        p = old_pos[sym]
        pnl = p["qty"] * (px - p["entry"])
        trade_info = Trade(
            symbol=sym,
            side=p["side"],
            entry_time=p["entry_time"],
            exit_time=time,
            pnl=float(pnl),
            exit_reason="切换仓位",
        )
        trades.append(trade_info)

    return trades


def update_portfolio_info(df_all: dict, pos: dict, time, equity):
    """
    返回当日各标的及现金的仓位记录，不修改持仓或行情。
    保留原规则：无当日行情或未持有标的输出零仓位。
    """
    cur_port = []

    for sym, df in df_all.items():
        if time not in df.index:
            cur_port.append((time, sym, 0, 0))
            continue

        if sym not in pos.keys():
            cur_port.append((time, sym, 0, 0))
            continue

        px = getv(df, time, "close")  # pos[sym]["entry"]  #
        qty = pos[sym]["qty"]

        value = px * qty
        cur_port.append((time, sym, qty, value))
        equity -= value

    cur_port.append((time, "cash", equity, equity))
    return cur_port
