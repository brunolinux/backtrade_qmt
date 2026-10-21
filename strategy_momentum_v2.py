import pandas as pd
import numpy as np
from typing import NamedTuple
from portfolio_accounting import calc_equity_close
from strategy_common import (Position, PortfolioRow, Trade, getv, atr, calc_corr_matrix,
    calc_quantity, calc_stop_positions,
    calc_trade_records, preserve_entries_for_unchanged_quantities, calc_position_size, calc_leverage_by_vol,
    rebalance_portfolio, build_portfolio_snapshot)


class EquityRow(NamedTuple):
    """每日账户权益报表行。"""

    datetime: pd.Timestamp
    equity: float


def preprocess(
        market_data: dict[str, pd.DataFrame],
        atr_window: int,
        short_window: int,
        long_window: int,
        volatility_window: int,
        ) -> dict[str, pd.DataFrame]:
    """整理行情并计算 ATR 和波动率调整后的动量因子。

    Args:
        market_data: 按标的代码组织的行情 DataFrame 字典，包含 high、low、
            close 数值列；输入字典及 DataFrame 只读。
        atr_window: ATR 滚动均值的行数窗口。
        short_window: 短周期动量收益率的间隔行数。
        long_window: 长周期动量收益率的间隔行数。
        volatility_window: 单期收益率滚动标准差的行数窗口。

    Returns:
        包含独立 DataFrame 的新行情字典。每张表按索引排序，重复索引
        保留最后一条，并添加 atr 和 factor 列；因子为短、长动量按 0.7、0.3
        加权后除以波动率。窗口未满的指标保留 NaN。
    """
    processed_data = {}
    for sym, df in market_data.items():
        df = df.sort_index()
        df = df[~df.index.duplicated(keep="last")].copy(deep=True)

        df["atr"] = atr(df, atr_window)

        # 计算技术指标
        mom_short = df["close"].pct_change(short_window)
        mom_long = df["close"].pct_change(long_window)
        vol = df["close"].pct_change().rolling(volatility_window).std()
        factor = (mom_short*0.7 + mom_long*0.3)/vol
        df["factor"] = factor
        processed_data[sym] = df

    return processed_data


def rank_factor(
        market_data: dict,
        timestamp,
        factor_column="factor",
        ) -> pd.Series:
    """按指定时刻的截面因子降序排列标的。

    Args:
        market_data: 按标的代码组织的行情 DataFrame 字典，输入只读；
            当日索引应唯一，且存在指定的因子列。
        timestamp: 与行情索引兼容的排名时刻。
        factor_column: 用于排名的因子列名，默认为 factor。

    Returns:
        索引为标的代码，值为因子，按因子降序排列。
        无当日行情或当日因子为 NaN 的标的不参与排名。
    """
    factor = {}
    for sym, df in market_data.items():
        # 当天可以交易且因子不为空
        if timestamp in df.index and not pd.isna(df.loc[timestamp, factor_column]):
            factor[sym] = df.loc[timestamp, factor_column]
    sorted_factor = pd.Series(factor).sort_values(ascending=False)
    return sorted_factor


def select_retained_positions(
        market_data: dict[str, pd.DataFrame],
        positions: dict[str, Position],
        ranked_factors: pd.Series,
        timestamp,
        retention_rank_limit: int
        ) -> dict[str, Position]:
    """筛选收盘价高于止损价且排名在保留范围内的持仓。

    Args:
        market_data: 按标的代码组织的行情 DataFrame 字典，包含 close 列。
        positions: 当前 Position 持仓字典，使用 stop，不使用 take。
        ranked_factors: pandas.Series，按因子降序排列，索引为唯一标的代码；
            所有当日可交易的当前持仓必须出现在索引中。
        timestamp: 与行情索引兼容的筛选时刻。
        retention_rank_limit: int，保留排名的数量上限，排名从零开始且必须
            严格小于此值。

    Returns:
        dict[str, Position]，新的外层保留持仓字典，允许共享不可变记录；
        当日无行情的持仓直接保留，其他持仓须同时满足价格和排名条件。
        所有输入只读。
    """
    reserve_pos = {}

    # 遍历所有仓位
    for sym in positions.keys():
        df = market_data[sym]

        # 如果当天不能交易, 则保留仓位
        if timestamp not in df.index:
            reserve_pos[sym] = positions[sym]
            continue

        c = getv(df, timestamp, "close")
        p = positions[sym]

        rank_index = ranked_factors.index.get_indexer([sym])[0]
        # 如果没有达到止损线 或者 排序仍然靠前
        if c > p.stop and rank_index < retention_rank_limit:
            reserve_pos[sym] = positions[sym]

    return reserve_pos


def calc_buy_pos(
        market_data: dict,
        held_positions: dict[str, Position],
        ranked_factors: pd.Series,
        timestamp,
        equity : float,
        candidate_limit: int,
        stop_atr_multiple: float,
        max_trade_risk_ratio: float,
        ) -> tuple[dict[str, Position], dict[str, float]]:
    """扫描排名靠前的候选标的并计算新开仓记录。

    Args:
        market_data: 按标的代码组织的行情 DataFrame 字典，包含 close 和
            atr 列；扫描标的应具有当日有效行情。
        held_positions: 已持有标的的 Position 仓位字典，用于跳过已有持仓。
        ranked_factors: 按因子降序排列, 索引为标的代码。
        timestamp: 与行情索引兼容的开仓时刻。
        equity: 账户总权益，用于计算单笔风险预算和持仓金额上限。
        candidate_limit: 最多扫描的排名项数; 已有持仓也占用扫描名额。
        stop_atr_multiple: 止损距离相对当日 ATR 的倍数。
        max_trade_risk_ratio: 单笔允许损失占权益的比例, 如 0.02。

    Returns:
        tuple[dict[str, Position], dict[str, float]]，即 (positions, prev_close)，
        分别为新开仓记录和对应每股买入价基准，记录的 take 为 None。
        遇到负因子立即停止扫描，已有持仓跳过；
        不过滤计算所得的零股数记录。所有输入只读。
    """

    pos: dict[str, Position] = {}
    prev_close = {}

    for i, sym in enumerate(ranked_factors.index):
        # 超过候选数目
        if i >= candidate_limit:
            break

        # 得分小于 0
        if ranked_factors[sym] < 0:
            break

        # 已经包含在已有仓位
        if sym in held_positions.keys():
            continue

        df = market_data[sym]

        price = getv(df, timestamp, "close")
        atr = getv(df, timestamp, "atr")

        stop = price - stop_atr_multiple * atr

        # 计算仓位
        qty = calc_position_size(equity, atr, price, stop_atr_multiple, max_trade_risk_ratio)

        pos[sym] = Position(
            entry=price, entry_time=timestamp, stop=stop, atr=atr, qty=qty, side=1)
        prev_close[sym] = price

    return pos, prev_close


def calc_daily_positions(
        market_data: dict,
        positions: dict[str, Position],
        close_marks: dict[str, float],
        timestamp,
        equity,
        equity_history,
        params: dict
    ) -> tuple[dict[str, Position], dict[str, float], list[Trade]]:
    """计算当日止损、持仓筛选及条件开仓和调仓后的新状态。

    Args:
        market_data: 已预处理的行情字典，包含 close、atr 和 factor 列。
        positions: 已完成当日估值、尚未处理当日止损的 Position 持仓字典。
        close_marks: 已完成当日估值的完整价格基准，包含停牌及残留标的键。
        timestamp: 与行情索引兼容的当日时刻。
        equity: 当日估值后的账户总权益，本函数不再计算权益。
        equity_history: 按时间排列且已包含当日权益的序列，用于杠杆计算。
        params: 原策略配置字典；所有输入只读，本函数不追加权益历史。

    Returns:
        tuple[dict[str, Position], dict[str, float], list[Trade]]，依次为新持仓、
        完整新价格基准和当日交易列表。两个映射均独立于输入，允许共享不可变
        Position；退出记录先于调仓记录。仅有剩余持仓名额时开仓和调仓，
        即使未实际买入也执行该分支；新基准保留全部旧键并合入买入价。
    """
    # step 1: 根据最新收盘价更新止损价格
    stopped_positions = calc_stop_positions(market_data, positions, timestamp, params["atr_stop"])
    # step 2: 根据最新因子对标的排序
    ranked_factors = rank_factor(market_data, timestamp, "factor")
    # step 3: 从现有持有标的中选出继续持有的标的
    retained_positions = select_retained_positions(
        market_data, stopped_positions, ranked_factors, timestamp, params["top_num_reserve"])
    # step 4: 记录标的卖出交易
    daily_trades = calc_trade_records(market_data, timestamp, retained_positions, stopped_positions)
    # step 5: 更新所有标的的最新收盘价信息
    next_close_marks = close_marks.copy()

    # step 6: 判断是否有剩余标的名额，如果没有，直接退出
    available_slots = params["hold_max_num"] - len(retained_positions)
    if available_slots <= 0:
        return retained_positions, next_close_marks, daily_trades

    # 如果有剩余持仓名额，则开仓并调仓,
    # 注意: 不执行日频调仓 (可选方案)
    # step 7: 仅考虑单只标的最大亏损的情况下计算持有
    new_positions, entry_close_marks = calc_buy_pos(
        market_data, retained_positions, ranked_factors, timestamp, equity, available_slots,
        params["atr_stop"], params["max_risk_per_trade"])
    # 更新候选标, 并将其收盘价纳入 close_marks, 方便后续计算盯市收益
    candidate_positions = {**retained_positions, **new_positions}
    next_close_marks.update(entry_close_marks)

    # step 8: 计算杠杆率, ETF 没有杠杆的说法，其实是持有现金的比率
    leverage = calc_leverage_by_vol(
        equity_history, params["window_vol"], params["annual_factor"], params["target_vol"],
        params["min_lev"], params["max_lev"])
    allocation_budget = equity * leverage
    rebalanced_positions = rebalance_portfolio(
        market_data, candidate_positions, timestamp, allocation_budget, params["pos_change_threshold"])
    rebalanced_positions = preserve_entries_for_unchanged_quantities(rebalanced_positions, candidate_positions)
    daily_trades.extend(calc_trade_records(
        market_data, timestamp, rebalanced_positions, candidate_positions))
    return rebalanced_positions, next_close_marks, daily_trades


def build_backtest_results(
        portfolio_rows: list[PortfolioRow],
        equity_rows: list[EquityRow],
        trade_records: list[Trade],
        ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """将累计记录转换为持仓、权益曲线和交易三张结果表。

    Args:
        portfolio_rows: PortfolioRow 列表，每行为日期、标的、股数和市值。
        equity_rows: EquityRow 列表，每行为日期和账户总权益。
        trade_records: Trade 记录列表；三个输入列表均只读。

    Returns:
        tuple[pandas.DataFrame, pandas.DataFrame, pandas.DataFrame]，依次为
        portfolio、equity_curve 和 trades。前两表以 datetime 为索引，列分别
        为 symbol/quantity/value 和 equity；交易表保留 Trade 字段顺序。
        空表仍保留对应列，数据类型沿用 pandas 的原始推断。
    """
    portfolio = pd.DataFrame(portfolio_rows, columns=PortfolioRow._fields).set_index("datetime")
    equity_curve = pd.DataFrame(equity_rows, columns=EquityRow._fields).set_index("datetime")
    trades = pd.DataFrame(trade_records, columns=Trade._fields)
    return portfolio, equity_curve, trades


def backtest(market_data: dict, params: dict, start_date=None):
    """执行动量策略回测并返回持仓、权益曲线和交易表。

    负责预处理、逐日估值和结果收集；每日持仓决策和结果表转换由私有函数处理。

    Args:
        market_data: 按标的代码组织的行情 DataFrame 字典，包含 high、low、
            close 列，索引为日期；输入字典及 DataFrame 只读。
        params: 只读配置字典，必需键为 init_equity、window_atr、window_short、
            window_long、window_vol、atr_stop、top_num_reserve、hold_max_num、
            max_risk_per_trade、annual_factor、target_vol、min_lev、max_lev 和
            pos_change_threshold。风险及波动率比例用小数表示，如 0.02 为 2%。
        start_date: pandas 可解析的起始日期，包含该日；默认为 None，
            表示遍历全部行情日期。指标预处理仍使用完整行情历史。

    Returns:
        tuple[pandas.DataFrame, pandas.DataFrame, pandas.DataFrame]，依次为：
            portfolio: 以 datetime 为索引，列为 symbol、quantity、value，
                每日包含各标的及 cash 行。
            curve: 以 datetime 为索引，equity 列为每日总权益。
            trades: 默认整数索引，列为 symbol、side、entry_time、exit_time、
                pnl、exit_reason，记录退出和切换仓位的交易。
    """
    # 跨交易日账户状态：每轮估值前的上次权益，以及上轮决策后的持仓
    equity = float(params["init_equity"])
    positions: dict[str, Position] = {}

    # 盯市基准：各标的最近一次可用收盘价，供下一轮估值使用
    close_marks = {}

    # 累计交易与已估值权益；权益历史供波动率杠杆计算
    trade_records = []
    equity_history = []

    # 报表原始行：每日持仓（含现金）及权益，循环后转换为结果表
    portfolio_rows: list[PortfolioRow] = []
    equity_rows: list[EquityRow] = []

    # 预处理
    processed_market_data = preprocess(
        market_data, params["window_atr"], params["window_short"],
        params["window_long"], params["window_vol"])
    print("预处理计算")

    timeline = sorted(set().union(*[df.index for df in processed_market_data.values()]))

    # 如果设置起始时间, 则从指定时间开始
    if start_date:
        first_date = pd.to_datetime(start_date)
        timeline = [timestamp for timestamp in timeline if timestamp >= first_date]

    for time_stamp in timeline:
        # 更新账户市值, 持仓标的前一个未停牌交易日的收盘价
        equity, close_marks = calc_equity_close(
            processed_market_data, positions, close_marks, time_stamp, equity)
        equity_history.append(equity)

        # 计算仓位
        positions, close_marks, daily_trades = calc_daily_positions(
            processed_market_data, positions, close_marks, time_stamp, equity, equity_history, params)
        trade_records.extend(daily_trades)

        # 记录当日持仓与权益报表行
        portfolio_rows.extend(build_portfolio_snapshot(
            processed_market_data, positions, time_stamp, equity))
        equity_rows.append(EquityRow(datetime=time_stamp, equity=equity))
        print("{} over!!!!".format(time_stamp))

    return build_backtest_results(portfolio_rows, equity_rows, trade_records)
