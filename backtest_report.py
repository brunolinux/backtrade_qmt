"""回测结果的独立报表构造与 Excel 导出。"""

from collections.abc import Mapping
import re
from pathlib import Path
from typing import NamedTuple

import pandas as pd
import numpy as np

from money import round_money, sum_money
from strategy_common import Trade


class BacktestTables(NamedTuple):
    """按用途具名访问的三张独立报表。"""

    trade: pd.DataFrame
    portfolio_value: pd.DataFrame
    portfolio_qty: pd.DataFrame


def to_qmt_symbol(symbol: str) -> str:
    """将当前范围的 ETF 代码规范为 QMT 代码。

    Args:
        symbol: 六位 ETF 裸代码，或已有正确 SH/SZ 后缀的代码。

    Returns:
        15 开头对应 .SZ，5 开头对应 .SH，已有正确后缀保持不变。

    Raises:
        ValueError: 代码不在当前 ETF 范围，或已有后缀不匹配。
    """
    match = re.fullmatch(r'(15[0-9]{4}|5[0-9]{5})(?:\.(SH|SZ))?', str(symbol))
    if match:
        code, suffix = match.groups()
        exchange = 'SZ' if code.startswith('15') else 'SH'
        if suffix is None or suffix == exchange:
            return f'{code}.{exchange}'
    raise ValueError(f'无法识别或交易所后缀不匹配的 ETF 代码: {symbol!r}')


def build_backtest_tables(
        portfolio: pd.DataFrame, trades: pd.DataFrame,
        names: Mapping[str, str]) -> BacktestTables:
    """从回测结果构造交易、市值和数量报表，不修改输入。

    Args:
        portfolio: 以 datetime 为索引，包含 symbol、quantity、value 的持仓快照。
        trades: 包含 Trade 字段的交易记录表。
        names: 标的代码到中文名称的只读映射。

    Returns:
        三张独立报表；市值包含现金及末列 total_value，数量不含现金。
        金额逐项半入到分，NaN 在金额汇总中继续传播。代码统一为 QMT 格式，
        数量校验后转为整数，保留零及负号。

    Raises:
        ValueError: 代码无效、转换后标的列重复，或数量缺失、非整数、非整手。
    """
    trade = trades.loc[:, list(Trade._fields)].copy()
    normalized_names = {to_qmt_symbol(code): name for code, name in names.items() if code != 'cash'}
    trade['symbol'] = trade['symbol'].map(to_qmt_symbol)
    trade.insert(0, 'name', trade['symbol'].map(normalized_names))
    trade['pnl'] = trade['pnl'].map(round_money)

    values = portfolio.pivot(columns='symbol', values='value').map(round_money)
    codes = {code: to_qmt_symbol(code) for code in values.columns if code != 'cash'}
    if len(set(codes.values())) != len(codes):
        raise ValueError(f'QMT 代码转换后存在重复标的列: {list(codes.values())}')
    values = values.rename(columns=codes)
    if 'cash' not in values:
        values['cash'] = 0.
    values['total_value'] = pd.Series(
        [sum_money(row) for row in values.itertuples(index=False, name=None)],
        index=values.index, dtype=float)
    quantities = portfolio.pivot(columns='symbol', values='quantity').drop(columns='cash', errors='ignore')
    for code in quantities:
        column = quantities[code]
        if column.isna().any() or not (np.isfinite(column) & (column % 100 == 0)).all():
            raise ValueError(f'标的 {code} 的数量必须为有限整数且为 100 的倍数')
    quantities = quantities.astype('int64').rename(columns=codes)
    return BacktestTables(trade, values, quantities)


def write_backtest_workbook(path: str | Path, tables: BacktestTables) -> None:
    """将已构造的三张报表写入 Excel，并设置数值显示格式。

    Args:
        path: 目标 .xlsx 文件路径，父目录不存在时创建。
        tables: build_backtest_tables 返回的报表，只读且金额已按分处理。

    Returns:
        None，写出 trade、portfolio_value、portfolio_qty 三张工作表。
        金额与数量保持数值类型，日期显示为年月日。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine='openpyxl') as writer:
        for sheet_name, table in zip(BacktestTables._fields, tables):
            # 显式写出日期列，也覆盖只有日期、没有任何标的列的全现金数量表。
            output = table if sheet_name == 'trade' else table.reset_index()
            output.to_excel(writer, sheet_name=sheet_name, index=False)
            worksheet = writer.sheets[sheet_name]
            for column in worksheet.iter_cols():
                header = column[0].value
                if header in ('datetime', 'entry_time', 'exit_time'):
                    number_format = 'yyyy-mm-dd'
                elif sheet_name == 'portfolio_qty':
                    number_format = '0'
                elif sheet_name == 'portfolio_value' or header == 'pnl':
                    number_format = '0.00'
                else:
                    continue
                for cell in column[1:]:
                    cell.number_format = number_format
