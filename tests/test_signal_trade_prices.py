from copy import deepcopy
from contextlib import redirect_stdout
from io import StringIO
import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

import strategy_common as common
import portfolio_accounting as accounting
import strategy_momentum as legacy
import strategy_momentum_v2 as momentum


def make_position(**changes):
    values = dict(trade_qty=100, side=1, sig_entry=20.,
                  trade_entry_time=pd.Timestamp('2026-01-05'), sig_stop=18.,
                  sig_atr=1., trade_raw_close=10., sig_take=30.)
    values.update(changes)
    return common.Position(**values)


class SignalPriceFlowTest(unittest.TestCase):
    def test_legacy_signal_carries_raw_price_without_changing_strength(self):
        timestamp = pd.Timestamp('2026-01-06')
        market = {'A': pd.DataFrame({
            'close': [20.], 'raw_close': [10.], 'atr': [2.],
            'ma': [18.], 'sig_long': [True],
        }, index=[timestamp])}
        original = deepcopy(market)
        signals = legacy.calc_buy_signals(
            market, {}, pd.DataFrame([[1.]], index=['A'], columns=['A']), timestamp, .9)
        self.assertEqual(signals, [('A', 1, 1., 20., 2., 10.)])
        positions, marks = legacy.calc_buy_pos(signals, timestamp, 10000., 1, 3., 5., .06)
        self.assertEqual((positions['A'].sig_entry, positions['A'].trade_raw_close), (20., 10.))
        self.assertEqual((positions['A'].sig_stop, positions['A'].sig_take), (14., 30.))
        self.assertEqual(marks, {'A': 10.})
        self.assertEqual(positions['A'].trade_qty, 200)
        assert_frame_equal(market['A'], original['A'])

    def test_v2_opening_stores_both_prices_and_initializes_raw_marks(self):
        timestamp = pd.Timestamp('2026-01-06')
        market = {'A': pd.DataFrame({
            'close': [20.], 'raw_close': [10.], 'atr': [2.],
        }, index=[timestamp])}
        original = deepcopy(market)
        positions, marks = momentum.calc_buy_pos(
            market, {}, pd.Series({'A': 1.}), timestamp, 10000., 1, 3., .06)
        position = positions['A']
        self.assertEqual((position.sig_entry, position.trade_raw_close), (20., 10.))
        self.assertEqual((position.sig_stop, position.sig_atr), (14., 2.))
        self.assertEqual(position.trade_entry_time, timestamp)
        self.assertIsNone(position.sig_take)
        self.assertEqual(marks, {'A': 10.})
        self.assertEqual(position.trade_qty, 200)
        assert_frame_equal(market['A'], original['A'])


class PositionSizingPriceTest(unittest.TestCase):
    def test_risk_conversion_and_capital_limit_use_raw_price(self):
        cases = [
            ((10000., 2., 20., 10., 3., .06), 200),
            ((1000., 1., 20., 10., 2., 1.), 100),
            ((10000., 1., 10., 10., 2., .05), 200),
            ((1000., 0., 20., 10., 2., 1.), 0),
        ]
        for arguments, expected in cases:
            with self.subTest(arguments=arguments):
                self.assertEqual(common.calc_position_size(*arguments), expected)


class RebalancePriceTest(unittest.TestCase):
    def setUp(self):
        self.timestamp = pd.Timestamp('2026-01-06')

    def test_rebalance_keeps_signal_atr_weights_and_buys_actual_shares(self):
        market = {
            'A': pd.DataFrame({'close': [20.], 'raw_close': [10.]}, index=[self.timestamp]),
            'B': pd.DataFrame({'close': [80.], 'raw_close': [20.]}, index=[self.timestamp]),
        }
        positions = {'A': make_position(),
                     'B': make_position(trade_qty=300, sig_atr=2., sig_entry=80., trade_raw_close=20.)}
        original = deepcopy((market, positions))
        result = common.rebalance_portfolio(market, positions, self.timestamp, 6000., .2)
        self.assertEqual(result, {
            'A': positions['A']._replace(trade_qty=400, trade_entry_time=self.timestamp),
            'B': positions['B']._replace(trade_qty=100, trade_entry_time=self.timestamp),
        })
        self.assertEqual(positions, original[1])
        for symbol in market:
            assert_frame_equal(market[symbol], original[0][symbol])

    def test_rebalance_clips_budget_using_raw_price_below_change_threshold(self):
        market = {'A': pd.DataFrame({'close': [20.], 'raw_close': [10.]}, index=[self.timestamp])}
        positions = {'A': make_position(trade_qty=300)}
        result = common.rebalance_portfolio(market, positions, self.timestamp, 1500., 100.)
        self.assertEqual(result, {
            'A': positions['A']._replace(trade_qty=100, trade_entry_time=self.timestamp),
        })

    def test_unchanged_quantity_restores_both_costs_and_time_but_keeps_stop(self):
        current = {'A': make_position()}
        candidates = {'A': current['A']._replace(
            sig_entry=24., trade_raw_close=12., trade_entry_time=self.timestamp, sig_stop=22.)}
        original = deepcopy((current, candidates))
        result = common.preserve_entries_for_unchanged_quantities(candidates, current)
        self.assertEqual(result, {'A': current['A']._replace(sig_stop=22.)})
        self.assertIsNot(result, candidates)
        self.assertEqual((current, candidates), original)

    def test_stops_and_retention_compare_signal_prices(self):
        market = {'A': pd.DataFrame({'close': [40.], 'raw_close': [10.]}, index=[self.timestamp])}
        positions = {'A': make_position(sig_atr=2., sig_stop=35., sig_take=50.)}
        stopped = common.calc_stop_positions(market, positions, self.timestamp, 2.)
        self.assertEqual(stopped['A'].sig_stop, 36.)
        self.assertEqual(stopped['A'].trade_raw_close, 10.)
        self.assertEqual(legacy.select_retained_positions(market, stopped, self.timestamp), stopped)
        self.assertEqual(momentum.select_retained_positions(
            market, stopped, pd.Series({'A': 1.}), self.timestamp, 1), stopped)


class RawSettlementPriceTest(unittest.TestCase):
    def setUp(self):
        self.timestamp = pd.Timestamp('2026-01-06')

    def test_equity_and_complete_marks_use_raw_prices_without_changing_cost(self):
        market = {
            'A': pd.DataFrame({'close': [33.], 'raw_close': [11.]}, index=[self.timestamp]),
            'B': pd.DataFrame({'close': [80.], 'raw_close': [20.]},
                              index=[self.timestamp - pd.Timedelta(days=1)]),
        }
        positions = {'A': make_position(), 'B': make_position(trade_raw_close=20.)}
        marks = {'A': 10., 'B': 20., 'STALE': 7.}
        original = deepcopy((market, positions, marks))
        for _ in range(2):
            equity, next_marks = accounting.calc_equity_close(
                market, positions, marks, self.timestamp, 1000.)
            self.assertEqual(equity, 1100.)
            self.assertEqual(next_marks, {'A': 11., 'B': 20., 'STALE': 7.})
            self.assertIsNot(next_marks, marks)
        next_marks['A'] = 999.
        self.assertEqual((positions, marks), original[1:])
        for symbol in market:
            assert_frame_equal(market[symbol], original[0][symbol])

    def test_adjusted_price_change_does_not_change_raw_equity(self):
        market = {'A': pd.DataFrame({'close': [30.], 'raw_close': [10.]}, index=[self.timestamp])}
        self.assertEqual(accounting.calc_equity_close(
            market, {'A': make_position()}, {'A': 10.}, self.timestamp, 1000.),
            (1000., {'A': 10.}))

    def test_duplicate_and_missing_previous_mark_use_raw_price(self):
        market = {'A': pd.DataFrame({'close': [33., 36.], 'raw_close': [11., 12.]},
                                   index=[self.timestamp, self.timestamp])}
        positions = {'A': make_position()}
        for previous, expected_equity in [({'A': 10.}, 1200.), ({}, 1000.)]:
            with self.subTest(previous=previous):
                self.assertEqual(accounting.calc_equity_close(
                    market, positions, previous, self.timestamp, 1000.),
                    (expected_equity, {'A': 12.}))

    def test_invalid_raw_prices_do_not_fall_back_to_adjusted_close(self):
        for values in [{'close': [33.]},
                       {'close': [33.], 'raw_close': ['invalid']},
                       {'close': [33.], 'raw_close': [float('nan')]}]:
            with self.subTest(values=values):
                market = {'A': pd.DataFrame(values, index=[self.timestamp])}
                marks = {'A': 10.}
                equity, next_marks = accounting.calc_equity_close(
                    market, {'A': make_position()}, marks, self.timestamp, 1000.)
                self.assertTrue(pd.isna(equity))
                self.assertTrue(pd.isna(next_marks['A']))
                self.assertEqual(marks, {'A': 10.})


class RawTradeSnapshotPriceTest(unittest.TestCase):
    def setUp(self):
        self.timestamp = pd.Timestamp('2026-01-06')
        self.market = {'A': pd.DataFrame({'close': [36.], 'raw_close': [12.]},
                                         index=[self.timestamp])}

    def test_exits_and_rebalances_use_full_signed_quantity_and_raw_cost(self):
        for quantity, side, pnl, exit_reason in [(100, 1, 200., '止盈'), (-100, -1, -200., '止损')]:
            current = {'A': make_position(trade_qty=quantity, side=side, sig_entry=30.)}
            changed = {'A': current['A']._replace(
                trade_qty=quantity * 2, sig_entry=36., trade_raw_close=12.,
                trade_entry_time=self.timestamp)}
            for candidates, reason in [({}, exit_reason), (changed, '切换仓位')]:
                with self.subTest(quantity=quantity, reason=reason):
                    original = deepcopy((current, candidates, self.market))
                    expected = [common.Trade(
                        'A', side, pd.Timestamp('2026-01-05'), self.timestamp, pnl, reason)]
                    for _ in range(2):
                        self.assertEqual(common.calc_trade_records(
                            self.market, self.timestamp, candidates, current), expected)
                    self.assertEqual((current, candidates), original[:2])
                    assert_frame_equal(self.market['A'], original[2]['A'])

    def test_snapshot_values_actual_shares_at_raw_price(self):
        for quantity, value, cash in [(100, 1200., 800.), (-100, -1200., 3200.)]:
            with self.subTest(quantity=quantity):
                positions = {'A': make_position(trade_qty=quantity)}
                original = deepcopy((positions, self.market))
                self.assertEqual(common.build_portfolio_snapshot(
                    self.market, positions, self.timestamp, 2000.), [
                        common.PortfolioRow(self.timestamp, 'A', quantity, value),
                        common.PortfolioRow(self.timestamp, 'cash', cash, cash),
                    ])
                self.assertEqual(positions, original[0])
                assert_frame_equal(self.market['A'], original[1]['A'])


class DualPriceBacktestTest(unittest.TestCase):
    def test_both_backtests_use_raw_prices_from_opening_to_exit(self):
        dates = pd.date_range('2026-01-05', periods=6)
        market = {'A': pd.DataFrame({
            'close': [10., 11., 13., 14., 12., 11.],
            'raw_close': [5., 5.5, 6.5, 7., 6., 5.5],
            'high': [11., 12., 14., 15., 13., 12.],
            'low': [9., 10., 12., 13., 11., 10.],
        }, index=dates)}
        params = dict(
            init_equity=10000., window_atr=2, window_short=1, window_long=2,
            window_vol=2, atr_stop=1., top_num_reserve=1, hold_max_num=2,
            max_risk_per_trade=1., annual_factor=252, target_vol=.3,
            min_lev=1., max_lev=1., pos_change_threshold=.2,
            window_extreme=2, window_avg=2, atr_drawdown=1., atr_take=10.,
            corr_threshold=.9,
        )
        # 第三天以原始价 6.5 买入 1500 股，现金 250；第六天以 5.5 退出。
        expected_portfolio = pd.DataFrame({
            'symbol': ['A', 'cash'] * 6,
            'quantity': [0., 10000., 0., 10000., 1500., 250.,
                         1500., 250., 1500., 250., 0., 8500.],
            'value': [0., 10000., 0., 10000., 9750., 250.,
                      10500., 250., 9000., 250., 0., 8500.],
        }, index=pd.DatetimeIndex(dates.repeat(2), name='datetime'))
        expected_curve = pd.DataFrame({
            'equity': [10000., 10000., 10000., 10750., 9250., 8500.],
        }, index=pd.DatetimeIndex(dates, name='datetime'))
        expected_trades = pd.DataFrame({
            'symbol': ['A'], 'side': [1], 'entry_time': [dates[2]],
            'exit_time': [dates[5]], 'pnl': [-1500.], 'exit_reason': ['止损'],
        })
        original_market, original_params = deepcopy((market, params))
        for module in (legacy, momentum):
            with self.subTest(module=module.__name__):
                for _ in range(2):
                    with redirect_stdout(StringIO()):
                        portfolio, curve, trades = module.backtest(market, params)
                    assert_frame_equal(portfolio, expected_portfolio, check_freq=False)
                    assert_frame_equal(curve, expected_curve, check_freq=False)
                    assert_frame_equal(trades, expected_trades)
                    assert_frame_equal(market['A'], original_market['A'])
                    self.assertEqual(params, original_params)
