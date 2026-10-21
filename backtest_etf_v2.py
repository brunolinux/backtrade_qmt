"""执行 ETF 回测，保存 QMT 代码、整数数量与按分金额的 Excel 工作簿。"""

from pathlib import Path

from backtest_report import build_backtest_tables, write_backtest_workbook
from factor.config_etf import getETFFundsInfo
from factor.util import getFundsDataDict, CodeType
from strategy_momentum_v2 import backtest


def main(output_dir: str | Path | None = None) -> None:
    """运行回测并保存三张 Excel 报表，然后展示权益曲线。

    Args:
        output_dir: 输出目录，默认使用脚本旁的 data/output_v2。
            工作簿覆盖为 backtest_results.xlsx，已有 CSV 保留。

    Returns:
        None，写出工作簿并展示图表。
    """
    funds_info = getETFFundsInfo()    
    df_all = getFundsDataDict(funds_info, CodeType.ETF)

    # # ETF
    params = {
        "init_equity": 18_5000,         # 初始市值
        "window_atr": 40,               # ATR 窗口
        "window_short": 20,             # 短周期
        "window_long": 40,              # 长周期
        "window_vol": 40,               # 波动率窗口
        "atr_stop": 3,                  # 止损 atr 倍数

        "top_num_reserve": 8,
        "hold_max_num": 5,              # 持有品种最大数目
        "max_risk_per_trade": 0.02,     # 单笔交易最大损失: 2%
        "annual_factor": 252,           # 日线, 252 个交易日
        "target_vol": 0.3,              # 目标年化波动率 30%
        "min_lev": 0.3,                 
        "max_lev": 1.0,
        "pos_change_threshold": 0.2     # 仓位至少变更 20% 才调仓
    }

    portfolio, curve, trades = backtest(df_all, params, start_date="2026-01-01")

    symbols = funds_info["name"].to_dict()
    sub_dir = Path(output_dir) if output_dir is not None else Path(__file__).parent / 'data' / 'output_v2'
    tables = build_backtest_tables(portfolio, trades, symbols)
    write_backtest_workbook(sub_dir / 'backtest_results.xlsx', tables)


    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 1)
    curve.plot(ax=ax)

    # for sym, df in df_all.items():
    #     fig, ax = plt.subplots(1, 1)
    #     df.close.plot(ax=ax)

    #     val = portfolio_qty[sym] * df.close.max() / portfolio_qty[sym].max() 
    #     val.plot(ax=ax)

    #     ax.set_title(sym)

    plt.show()


if __name__ == '__main__':
    main()
