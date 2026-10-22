"""从回测工作簿读取最新目标仓位，并生成下一交易日的控制台清单。"""

from contextlib import redirect_stderr, redirect_stdout
import argparse
from datetime import date, timedelta
from io import StringIO
import math
from numbers import Number
import os
from pathlib import Path
import sys
from typing import NamedTuple

import pandas as pd

from backtest_report import to_qmt_symbol
from money import round_money


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_WORKBOOK = PROJECT_ROOT / 'data/output_v2/backtest_results.xlsx'


class ReportError(ValueError):
    """可以向用户直接展示的摘要生成错误。"""


class LatestPositions(NamedTuple):
    """最新源日期、有序仓位及同日现金和总资产，不修改来源工作簿。"""

    source_date: date
    positions: tuple[tuple[str, int], ...]
    cash: float
    total_value: float


def _parse_dates(frame: pd.DataFrame, sheet: str) -> pd.Series:
    """解析工作表的日期列，拒绝无效日期和按日重复的记录。

    Args:
        frame: 以普通列保存 datetime 的只读数据表。
        sheet: 用于定位错误的工作表名称。

    Returns:
        与原表索引对应的自然日期序列。

    Raises:
        ReportError: 日期列缺失、无法解析或按日重复。
    """
    if 'datetime' not in frame:
        raise ReportError(f'{sheet} 缺少日期列 datetime')
    dates = []
    for value in frame['datetime']:
        try:
            if pd.isna(value) or isinstance(value, Number):
                raise ValueError
            timestamp = pd.Timestamp(value)
            if pd.isna(timestamp):
                raise ValueError
            dates.append(timestamp.date())
        except (ValueError, TypeError, OverflowError):
            raise ReportError(f'{sheet} 包含无效日期') from None
    parsed = pd.Series(dates, index=frame.index, dtype=object)
    if parsed.duplicated().any():
        raise ReportError(f'{sheet} 包含重复日期')
    return parsed


def _finite_number(value, field: str) -> float:
    """读取有限数值，不以零替代缺失值。

    Args:
        value: 工作簿中的标量数值。
        field: 用于定位错误的标的或金额字段。

    Returns:
        有限浮点数。

    Raises:
        ReportError: 数值无法转换或非有限。
    """
    try:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError
        return number
    except (ValueError, TypeError, OverflowError):
        raise ReportError(f'{field} 必须是有限数值') from None


def read_latest_positions(workbook_path: str | Path) -> LatestPositions:
    """只读工作簿，选取最大日期的目标仓位及同日现金和总资产。

    Args:
        workbook_path: 含 portfolio_qty 和 portfolio_value 的 Excel 路径。

    Returns:
        具名最新状态，保留标的列顺序以及零、负数量，总资产取包含现金的
        total_value，不重新估算，不改写工作簿。

    Raises:
        ReportError: 文件不可读、必要表列缺失、日期歧义、数量或金额不合法。
    """
    path = Path(workbook_path)
    try:
        with pd.ExcelFile(path, engine='openpyxl') as workbook:
            for sheet in ('portfolio_qty', 'portfolio_value'):
                if sheet not in workbook.sheet_names:
                    raise ReportError(f'工作簿缺少工作表 {sheet}')
            quantities = workbook.parse('portfolio_qty')
            values = workbook.parse('portfolio_value')
    except ReportError:
        raise
    except Exception:
        raise ReportError(f'无法读取工作簿 {path}') from None

    quantity_dates = _parse_dates(quantities, 'portfolio_qty')
    value_dates = _parse_dates(values, 'portfolio_value')
    if quantities.empty:
        raise ReportError('portfolio_qty 没有仓位日期记录')
    for field in ('cash', 'total_value'):
        if field not in values:
            raise ReportError(f'portfolio_value 缺少 {field} 列')
    source_date = max(quantity_dates)
    row = quantities.loc[quantity_dates == source_date].iloc[0]
    matching_values = values.loc[value_dates == source_date]
    if len(matching_values) != 1:
        raise ReportError(f'portfolio_value 缺少 {source_date} 唯一对应的 cash 和 total_value')
    cash = _finite_number(matching_values.iloc[0]['cash'], 'cash')
    total_value = _finite_number(matching_values.iloc[0]['total_value'], 'total_value')
    positions = []
    for symbol in quantities.columns:
        if symbol == 'datetime':
            continue
        try:
            if to_qmt_symbol(symbol) != symbol:
                raise ValueError
        except ValueError:
            raise ReportError(f'无效的 QMT ETF 代码: {symbol}') from None
        quantity = _finite_number(row[symbol], symbol)
        if quantity % 100 != 0:
            raise ReportError(f'{symbol} 的数量必须为整数且为 100 的倍数')
        positions.append((symbol, int(quantity)))
    return LatestPositions(source_date, tuple(positions), cash, total_value)


def format_positions_report(state: LatestPositions, next_trade_date: date) -> str:
    """将已验证的最新状态格式化为配置赋值片段及金额核对信息。

    Args:
        state: 最新源日期、有序数量及同日现金和总资产，只读。
        next_trade_date: 由交易日历确定的下一交易日。

    Returns:
        SIGNAL_DATE、TRADE_DATE、正仓位 TARGET_QUANTITIES 字典及 TOTAL_VALUE
        赋值片段，随后附中文现金与总市值。两个总资产金额相同，金额按分显示；
        年月日不补零，不附导入语句或末尾换行，不改变原始状态。
    """
    source_date = state.source_date
    lines = [
        f'SIGNAL_DATE = dt.date({source_date.year}, {source_date.month}, {source_date.day})',
        f'TRADE_DATE = dt.date({next_trade_date.year}, {next_trade_date.month}, {next_trade_date.day})',
        'TARGET_QUANTITIES = {',
    ]
    lines.extend(f'    "{symbol}": {quantity},' for symbol, quantity in state.positions if quantity > 0)
    total_value = f'{round_money(state.total_value):.2f}'
    lines.extend([
        '}',
        f'TOTAL_VALUE = {total_value}',
        f'现金: {round_money(state.cash):.2f}',
        f'总市值: {total_value}',
    ])
    return '\n'.join(lines)


def query_next_trade_date(source_date: date, client) -> date:
    """查询源日期后 31 个自然日内的第一个沪深开市日。

    Args:
        source_date: 仓位来源日期，不以命令执行日期替代。
        client: 提供 trade_cal 方法的 Tushare 客户端，可注入固定日历用于测试。

    Returns:
        日历中严格晚于源日期的最早开市日期，不依赖接口返回顺序。

    Raises:
        ReportError: 请求失败、日历格式无效或窗口内无法确定下一交易日。
            错误不包含第三方请求或认证信息，不回退到工作日推测。
    """
    start_date = source_date + timedelta(days=1)
    end_date = source_date + timedelta(days=31)
    try:
        # 第三方日志可能带请求信息，既不能进入清单，也不能泄露认证内容。
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            calendar = client.trade_cal(
                exchange='SSE', start_date=start_date.strftime('%Y%m%d'),
                end_date=end_date.strftime('%Y%m%d'), is_open='1',
                fields='cal_date,is_open')
    except Exception:
        raise ReportError('交易日历查询失败，请检查网络及接口配置') from None
    if not isinstance(calendar, pd.DataFrame) or not {'cal_date', 'is_open'} <= set(calendar.columns):
        raise ReportError('交易日历缺少有效日期或开市状态')
    dates = pd.to_datetime(calendar['cal_date'].astype(str), format='%Y%m%d', errors='coerce')
    states = pd.to_numeric(calendar['is_open'], errors='coerce')
    if dates.isna().any() or not states.isin([0, 1]).all():
        raise ReportError('交易日历包含无效日期或开市状态')
    candidates = dates.dt.date[(states == 1) & (dates.dt.date >= start_date) & (dates.dt.date <= end_date)]
    if candidates.empty:
        raise ReportError('交易日历在源日期之后 31 日内没有可确认的开市日期')
    return min(candidates)


def create_calendar_client():
    """从项目环境配置创建日历客户端，不在模块导入时执行。

    Returns:
        使用 TushareToken 的客户端；项目 .env 不覆盖已有环境变量。
        可选 TushareIP 仅覆盖当前客户端地址，未设置时使用库默认地址。

    Raises:
        ReportError: 缺少令牌或初始化失败，错误不包含令牌或原始请求信息。
    """
    try:
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            from dotenv import load_dotenv
            import tushare

            load_dotenv(PROJECT_ROOT / '.env', override=False)
            token = os.getenv('TushareToken', '').strip()
            if not token:
                raise ReportError('缺少 TushareToken 配置')
            client = tushare.pro_api(token)
            url = os.getenv('TushareIP', '').strip()
            if url:
                client._DataApi__http_url = url
            return client
    except ReportError:
        raise
    except Exception:
        raise ReportError('交易日历客户端初始化失败，请检查接口配置') from None


def main(argv: list[str] | None = None, *, calendar_client=None) -> int:
    """读取最新状态并一次性打印下一交易日的仓位清单。

    Args:
        argv: 命令行参数，默认使用进程参数；支持 --workbook PATH。
        calendar_client: 可注入的日历客户端，默认从项目环境创建。

    Returns:
        成功返回 0；可预期失败返回 1，错误进入 stderr，stdout 不留部分清单。
        工作簿只读，导入模块不会运行此入口。
    """
    parser = argparse.ArgumentParser(description='打印最新回测仓位及下一交易日')
    parser.add_argument('--workbook', type=Path, default=DEFAULT_WORKBOOK,
                        help='回测工作簿路径，默认使用项目 data/output_v2/backtest_results.xlsx')
    args = parser.parse_args(argv)
    try:
        state = read_latest_positions(args.workbook)
        client = calendar_client if calendar_client is not None else create_calendar_client()
        next_date = query_next_trade_date(state.source_date, client)
        output = format_positions_report(state, next_date)
    except ReportError as error:
        print(f'错误: {error}', file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
