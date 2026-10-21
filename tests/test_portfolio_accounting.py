from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

import strategy_momentum as strategy
import strategy_momentum_v2 as strategy_v2
from strategy_common import Position


def position(qty):
    return Position(trade_qty=qty, side=1, trade_raw_close=10., sig_entry=10., trade_entry_time=pd.Timestamp('2026-01-05'),
                    sig_stop=9., sig_atr=1.)


class StrategySettlementTest(unittest.TestCase):
    @staticmethod
    def settle(*args, **kwargs):
        return strategy.calc_equity_close(*args, **kwargs)

    def setUp(self):
        self.time = pd.Timestamp('2026-01-06')

    def market(self, **prices):
        return {sym: pd.DataFrame({'raw_close': [price], 'close': [price]}, index=[self.time])
                for sym, price in prices.items()}

    def assert_settlement(self, market, positions, marks, time, prev_equity,
                          expected_equity, expected_marks):
        original_marks = marks.copy()
        original_positions = deepcopy(positions)
        original_market = deepcopy(market)
        for _ in range(2):
            equity, next_close = self.settle(market, positions, marks, time, prev_equity)
            self.assertEqual(equity, expected_equity)
            self.assertEqual(next_close, expected_marks)
            self.assertIsNot(next_close, marks)
            self.assertEqual(marks, original_marks)
            self.assertEqual(positions, original_positions)
            for sym in market:
                assert_frame_equal(market[sym], original_market[sym])
        next_close['OUTPUT_ONLY'] = 999.
        self.assertEqual(marks, original_marks)

    def test_gains_and_losses_preserve_holdings_and_market(self):
        market = self.market(A=11., B=18., UNHELD=999.)
        positions = {'A': position(100), 'B': position(50)}
        marks = {'A': 10., 'B': 20., 'STALE': 7.}
        old_positions = deepcopy(positions)
        old_market = {sym: df.copy(deep=True) for sym, df in market.items()}
        self.assert_settlement(market, positions, marks, self.time, 1000., 1000.,
                               {'A': 11., 'B': 18., 'STALE': 7.})
        self.assertEqual(positions, old_positions)
        for sym in market:
            assert_frame_equal(market[sym], old_market[sym])

    def test_empty_positions_leave_equity_and_marks_unchanged(self):
        marks = {'STALE': 7.}
        self.assert_settlement({}, {}, marks, self.time, 1000., 1000., {'STALE': 7.})

    def test_signed_and_zero_quantities(self):
        marks = {'A': 10., 'B': 20.}
        self.assert_settlement(self.market(A=11., B=18.),
                               {'A': position(0), 'B': position(-50)},
                               marks, self.time, 1000., 1100., {'A': 11., 'B': 18.})

    def test_missing_mark_initializes_without_profit(self):
        marks = {}
        self.assert_settlement(self.market(A=11.), {'A': position(100)},
                               marks, self.time, 1000., 1000., {'A': 11.})

    def test_suspension_preserves_mark_until_resumption(self):
        market = {'A': pd.DataFrame({'raw_close': [12.], 'close': [12.]}, index=[self.time + pd.Timedelta(days=1)])}
        marks = {'A': 10.}
        positions = {'A': position(100)}
        self.assert_settlement(market, positions, marks, self.time, 1000., 1000., {'A': 10.})
        self.assert_settlement(market, positions, marks, self.time + pd.Timedelta(days=1),
                               1000., 1200., {'A': 12.})


class SettlementTest(StrategySettlementTest):
    @staticmethod
    def settle(*args, **kwargs):
        from portfolio_accounting import calc_equity_close
        return calc_equity_close(*args, **kwargs)

    def test_duplicate_dates_use_last_price(self):
        market = {'A': pd.DataFrame({'raw_close': [11., 12.], 'close': [11., 12.]}, index=[self.time, self.time])}
        marks = {'A': 10.}
        self.assert_settlement(market, {'A': position(100)}, marks,
                               self.time, 1000., 1200., {'A': 12.})

    def test_invalid_or_missing_raw_close_propagates_nan(self):
        for frame in [pd.DataFrame({'other': [11.]}, index=[self.time]),
                      pd.DataFrame({'raw_close': ['invalid'], 'close': ['invalid']}, index=[self.time]),
                      pd.DataFrame({'raw_close': [float('nan')], 'close': [float('nan')]}, index=[self.time])]:
            with self.subTest(frame=frame):
                marks = {'A': 10.}
                equity, next_close = self.settle({'A': frame}, {'A': position(100)}, marks,
                                                 self.time, 1000.)
                self.assertTrue(pd.isna(equity))
                self.assertTrue(pd.isna(next_close['A']))
                self.assertEqual(marks, {'A': 10.})

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
        equity, next_close = self.settle({'A': ChangingQuote(self.time)}, {'A': position(100)},
                                         marks, self.time, 1000.)
        self.assertEqual(equity, 1100.)
        self.assertEqual(next_close, {'A': 11.})
        self.assertEqual(marks, {'A': 10.})


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

    def test_equity_close_preserves_other_marks_and_inputs(self):
        from portfolio_accounting import calc_equity_close

        timestamp = pd.Timestamp('2026-01-06')
        market = {
            'A': pd.DataFrame({'raw_close': [11.], 'close': [11.]}, index=[timestamp]),
            'NEW': pd.DataFrame({'raw_close': [15.], 'close': [15.]}, index=[timestamp]),
            'SUSPENDED': pd.DataFrame(
                {'raw_close': [21.], 'close': [21.]}, index=[timestamp + pd.Timedelta(days=1)]),
        }
        positions = {symbol: position(quantity)
                     for symbol, quantity in [('A', 100), ('NEW', 100), ('SUSPENDED', 10)]}
        marks = {'A': 10., 'SUSPENDED': 20., 'STALE': 7.}
        original_market = deepcopy(market)
        original_positions = deepcopy(positions)
        original_marks = marks.copy()

        equity, next_marks = calc_equity_close(market, positions, marks, timestamp, 1000.)

        self.assertEqual(equity, 1100.)
        self.assertEqual(next_marks, {
            'A': 11., 'NEW': 15., 'SUSPENDED': 20., 'STALE': 7.,
        })
        self.assertIsNot(next_marks, marks)
        self.assertEqual((positions, marks), (original_positions, original_marks))
        for symbol in market:
            assert_frame_equal(market[symbol], original_market[symbol])
        next_marks['A'] = 999.
        self.assertEqual(marks, original_marks)

        empty_result = calc_equity_close({}, {}, marks, timestamp, 1000.)[1]
        self.assertEqual(empty_result, marks)
        self.assertIsNot(empty_result, marks)


class BacktestAccountingTest(unittest.TestCase):
    def test_v2_open_mark_and_close_match_fixed_baseline(self):
        self.assert_backtest_baseline(strategy_v2, hold_max_num=1)

    def test_old_strategy_rebalance_and_close_match_fixed_baseline(self):
        # 空余名额使每天都尝试调仓；股数不变时需保留首次入场价。
        self.assert_backtest_baseline(strategy, hold_max_num=2)

    def test_v2_unchanged_quantity_preserves_entry_until_close(self):
        self.assert_backtest_baseline(strategy_v2, hold_max_num=2)

    def assert_backtest_baseline(self, module, hold_max_num):
        dates = pd.date_range('2026-01-05', periods=6)
        prices = [10., 11., 13., 14., 12., 11.]
        market = {'A': pd.DataFrame({
            'raw_close': prices, 'close': prices, 'high': [x + 1 for x in prices],
            'low': [x - 1 for x in prices],
        }, index=dates)}
        params = dict(
            init_equity=10000, window_atr=2, window_short=1, window_long=2,
            window_vol=2, atr_stop=1, top_num_reserve=1, hold_max_num=hold_max_num,
            max_risk_per_trade=1., annual_factor=252, target_vol=.3,
            min_lev=1., max_lev=1., pos_change_threshold=.2,
            window_extreme=2, window_avg=2, atr_drawdown=1, atr_take=10,
            corr_threshold=.9,
        )
        original_market = deepcopy(market)
        original_frames = market.copy()
        original_params = deepcopy(params)
        results = []
        with redirect_stdout(StringIO()):
            for run_index in range(2):
                if module is strategy_v2 and run_index == 1:
                    results.append(module.backtest(
                        market_data=market, params=params, start_date=dates[0]))
                else:
                    results.append(module.backtest(market, params))
                self.assertEqual(params, original_params)
                self.assertEqual(list(market), list(original_market))
                for sym in market:
                    self.assertIs(market[sym], original_frames[sym])
                    assert_frame_equal(market[sym], original_market[sym])
        portfolio, curve, trades = results[0]
        for first, second in zip(results[0], results[1]):
            assert_frame_equal(first, second)

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
