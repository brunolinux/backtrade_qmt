from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

import strategy_momentum as strategy
import strategy_momentum_v2 as strategy_v2


class LegacySettlementTest(unittest.TestCase):
    settle = staticmethod(strategy.update_equity_close)

    def setUp(self):
        self.time = pd.Timestamp('2026-01-06')

    def market(self, **prices):
        return {sym: pd.DataFrame({'close': [price]}, index=[self.time])
                for sym, price in prices.items()}

    def test_gains_and_losses_preserve_holdings_and_market(self):
        market = self.market(A=11., B=18., UNHELD=999.)
        positions = {'A': {'qty': 100}, 'B': {'qty': 50}}
        marks = {'A': 10., 'B': 20., 'STALE': 7.}
        old_positions = deepcopy(positions)
        old_market = {sym: df.copy(deep=True) for sym, df in market.items()}
        self.assertEqual(self.settle(market, positions, marks, self.time, 1000.), 1000.)
        self.assertEqual(marks, {'A': 11., 'B': 18., 'STALE': 7.})
        self.assertEqual(positions, old_positions)
        for sym in market:
            assert_frame_equal(market[sym], old_market[sym])

    def test_empty_positions_leave_equity_and_marks_unchanged(self):
        marks = {'STALE': 7.}
        self.assertEqual(self.settle({}, {}, marks, self.time, 1000.), 1000.)
        self.assertEqual(marks, {'STALE': 7.})

    def test_signed_and_zero_quantities(self):
        marks = {'A': 10., 'B': 20.}
        equity = self.settle(self.market(A=11., B=18.),
                             {'A': {'qty': 0}, 'B': {'qty': -50}},
                             marks, self.time, 1000.)
        self.assertEqual(equity, 1100.)
        self.assertEqual(marks, {'A': 11., 'B': 18.})

    def test_missing_mark_initializes_without_profit(self):
        marks = {}
        self.assertEqual(self.settle(self.market(A=11.), {'A': {'qty': 100}},
                                     marks, self.time, 1000.), 1000.)
        self.assertEqual(marks, {'A': 11.})

    def test_suspension_preserves_mark_until_resumption(self):
        market = {'A': pd.DataFrame({'close': [12.]}, index=[self.time + pd.Timedelta(days=1)])}
        marks = {'A': 10.}
        positions = {'A': {'qty': 100}}
        equity = self.settle(market, positions, marks, self.time, 1000.)
        self.assertEqual(equity, 1000.)
        self.assertEqual(marks, {'A': 10.})
        equity = self.settle(market, positions, marks, self.time + pd.Timedelta(days=1), equity)
        self.assertEqual(equity, 1200.)
        self.assertEqual(marks, {'A': 12.})


class SettlementTest(LegacySettlementTest):
    @staticmethod
    def settle(*args, **kwargs):
        from portfolio_accounting import update_equity_close
        return update_equity_close(*args, **kwargs)

    def test_duplicate_dates_use_last_price(self):
        market = {'A': pd.DataFrame({'close': [11., 12.]}, index=[self.time, self.time])}
        marks = {'A': 10.}
        self.assertEqual(self.settle(market, {'A': {'qty': 100}}, marks,
                                     self.time, 1000.), 1200.)
        self.assertEqual(marks, {'A': 12.})

    def test_invalid_or_missing_close_propagates_nan(self):
        for frame in [pd.DataFrame({'other': [11.]}, index=[self.time]),
                      pd.DataFrame({'close': ['invalid']}, index=[self.time]),
                      pd.DataFrame({'close': [float('nan')]}, index=[self.time])]:
            with self.subTest(frame=frame):
                marks = {'A': 10.}
                equity = self.settle({'A': frame}, {'A': {'qty': 100}}, marks,
                                     self.time, 1000.)
                self.assertTrue(pd.isna(equity))
                self.assertTrue(pd.isna(marks['A']))

    def test_calculation_and_marks_share_one_price_read(self):
        class ChangingQuote:
            def __init__(self, time):
                self.index = [time]
                self.loc = self
                self.price = 10.

            def __getitem__(self, key):
                self.price += 1.
                return self.price

        marks = {'A': 10.}
        equity = self.settle({'A': ChangingQuote(self.time)}, {'A': {'qty': 100}},
                             marks, self.time, 1000.)
        self.assertEqual(equity, 1100.)
        self.assertEqual(marks, {'A': 11.})


class AccountingCoreTest(unittest.TestCase):
    def test_pure_calculation_is_repeatable_and_does_not_change_inputs(self):
        from portfolio_accounting import calc_mark_to_market_equity

        quantities = {'A': 100, 'B': 50, 'SUSPENDED': 10, 'NEW': 100}
        current = {'A': 11., 'B': 18., 'NEW': 15., 'UNHELD': 999.}
        previous = {'A': 10., 'B': 20., 'SUSPENDED': 7.}
        before = deepcopy((quantities, current, previous))
        for _ in range(2):
            self.assertEqual(calc_mark_to_market_equity(
                quantities, current, previous, 1000.), 1000.)
            self.assertEqual((quantities, current, previous), before)

    def test_pure_calculation_handles_empty_and_signed_quantities(self):
        from portfolio_accounting import calc_mark_to_market_equity

        self.assertEqual(calc_mark_to_market_equity({}, {}, {}, 1000.), 1000.)
        self.assertEqual(calc_mark_to_market_equity(
            {'A': 0, 'B': -50}, {'A': 11., 'B': 18.},
            {'A': 10., 'B': 20.}, 1000.), 1100.)

    def test_mark_update_preserves_other_keys_and_price_snapshot(self):
        from portfolio_accounting import update_close_marks

        current = {'A': 11., 'NEW': 15.}
        marks = {'A': 10., 'STALE': 7.}
        update_close_marks(current, marks)
        self.assertEqual(marks, {'A': 11., 'NEW': 15., 'STALE': 7.})
        self.assertEqual(current, {'A': 11., 'NEW': 15.})
        update_close_marks({}, marks)
        self.assertEqual(marks, {'A': 11., 'NEW': 15., 'STALE': 7.})


class BacktestAccountingTest(unittest.TestCase):
    def test_v2_open_mark_and_close_match_fixed_baseline(self):
        dates = pd.date_range('2026-01-05', periods=6)
        prices = [10., 11., 13., 14., 12., 11.]
        market = {'A': pd.DataFrame({
            'close': prices, 'high': [x + 1 for x in prices],
            'low': [x - 1 for x in prices],
        }, index=dates)}
        params = dict(
            init_equity=10000, window_atr=2, window_short=1, window_long=2,
            window_vol=2, atr_stop=1, top_num_reserve=1, hold_max_num=1,
            max_risk_per_trade=1., annual_factor=252, target_vol=.3,
            min_lev=1., max_lev=1., pos_change_threshold=.2,
        )
        with redirect_stdout(StringIO()):
            portfolio, curve, trades = strategy_v2.backtest(market, params)

        # 第三天以 13 元买入 700 股，现金 900；第六天以 11 元平仓。
        expected_portfolio = pd.DataFrame({
            'symbol': ['A', 'cash'] * 6,
            'quantity': [0., 10000., 0., 10000., 700., 900.,
                         700., 900., 700., 900., 0., 8600.],
            'value': [0., 10000., 0., 10000., 9100., 900.,
                      9800., 900., 8400., 900., 0., 8600.],
        }, index=pd.DatetimeIndex(dates.repeat(2), name='datetime'))
        expected_curve = pd.DataFrame(
            {'equity': [10000., 10000., 10000., 10700., 9300., 8600.]},
            index=pd.DatetimeIndex(dates, name='datetime'),
        )
        expected_trades = pd.DataFrame({
            'symbol': ['A'], 'side': [1], 'entry_time': [dates[2]],
            'exit_time': [dates[5]], 'pnl': [-1400.], 'exit_reason': ['止损'],
        })
        assert_frame_equal(portfolio, expected_portfolio, check_freq=False)
        assert_frame_equal(curve, expected_curve, check_freq=False)
        assert_frame_equal(trades, expected_trades)


if __name__ == '__main__':
    unittest.main()
