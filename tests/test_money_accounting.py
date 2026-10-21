import unittest

import pandas as pd

from portfolio_accounting import calc_equity_close, calc_mark_to_market_equity
from strategy_common import Position, build_portfolio_snapshot, calc_trade_records, rebalance_portfolio


class MoneyAccountingTest(unittest.TestCase):
    def setUp(self):
        self.time = pd.Timestamp('2026-01-06')

    def position(self, quantity=100, price=2.626):
        return Position(1, self.time - pd.Timedelta(days=1), quantity, price,
                        20.123456, 1.234567, 18.123456)

    def test_three_decimal_marks_and_equity(self):
        market = {'A': pd.DataFrame({'raw_close': [2.627]}, index=[self.time])}
        marks = {'A': 2.626}
        equity, next_marks = calc_equity_close(
            market, {'A': self.position()}, marks, self.time, 1000.)
        self.assertEqual(equity, 1000.1)
        self.assertEqual(next_marks, {'A': 2.627})
        self.assertEqual(marks, {'A': 2.626})

    def test_equity_rounds_each_increment_before_adding(self):
        self.assertEqual(calc_mark_to_market_equity(
            {'A': 1, 'B': 1}, {'A': 1.005, 'B': 1.005},
            {'A': 1., 'B': 1.}, 1000.005), 1000.03)

    def test_exit_and_rebalance_pnl_use_decimal_difference(self):
        market = {'A': pd.DataFrame({'raw_close': [2.675]}, index=[self.time])}
        current = {'A': self.position(quantity=1, price=0)}
        for candidate in [{}, {'A': current['A']._replace(
                trade_qty=2, trade_entry_time=self.time)}]:
            records = calc_trade_records(market, self.time, candidate, current)
            self.assertEqual(records[0].pnl, 2.68)

    def test_tiny_profit_keeps_profit_reason_after_rounding_to_zero(self):
        market = {'A': pd.DataFrame({'raw_close': [2.626001]}, index=[self.time])}
        record = calc_trade_records(
            market, self.time, {}, {'A': self.position()})[0]
        self.assertEqual(record.pnl, 0)
        self.assertEqual(record.exit_reason, '止盈')

    def test_snapshot_rounds_each_value_then_cash(self):
        market = {sym: pd.DataFrame({'raw_close': [price]}, index=[self.time])
                  for sym, price in [('A', 2.626), ('B', 1.005)]}
        positions = {'A': self.position(), 'B': self.position(quantity=1)}
        rows = build_portfolio_snapshot(market, positions, self.time, 1000.005)
        self.assertEqual([row.value for row in rows], [262.6, 1.01, 736.4])
        self.assertEqual(rows[-1].quantity, 736.4)
        self.assertEqual(positions['A'].sig_atr, 1.234567)
        self.assertEqual(market['A'].iloc[0].raw_close, 2.626)

    def test_exact_budget_does_not_trim_a_lot_from_float_error(self):
        # 这两个市值的浮点和为 817.4000000000001，实际预算为 817.40。
        market = {sym: pd.DataFrame({'raw_close': [price], 'close': [20.]}, index=[self.time])
                  for sym, price in [('A', 6.543), ('B', 1.631)]}
        positions = {sym: self.position() for sym in market}
        result = rebalance_portfolio(market, positions, self.time, 817.4, 100)
        self.assertEqual({sym: p.trade_qty for sym, p in result.items()}, {'A': 100, 'B': 100})
