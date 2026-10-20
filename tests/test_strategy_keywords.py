from copy import deepcopy
import unittest

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

import strategy_common as common
import portfolio_accounting as accounting
import strategy_momentum_v2 as momentum


class PriceRiskKeywordsTest(unittest.TestCase):
    def test_value_reading_and_lot_rounding_use_named_arguments(self):
        frame = pd.DataFrame({'close': [10., 12.]}, index=[1, 1])
        original = frame.copy(deep=True)
        self.assertEqual(common.getv(dataframe=frame, index_label=1, column='close'), 12.)
        self.assertTrue(pd.isna(common.getv(dataframe=frame, index_label=2, column='close')))
        self.assertTrue(pd.isna(common.getv(dataframe=frame, index_label=1, column='missing')))
        self.assertEqual(common.calc_quantity(quantity=299.9, lot_size=100), 200)
        self.assertEqual(common.calc_quantity(quantity=-299.9, lot_size=100), -200)
        with self.assertRaises(TypeError):
            common.calc_quantity(quantity=299.9, min_num=100)
        assert_frame_equal(frame, original)

    def test_atr_default_window_and_named_correlation_price_column(self):
        frame = pd.DataFrame({'high': [11.] * 11, 'low': [9.] * 11, 'close': [10.] * 11})
        original = frame.copy(deep=True)
        result = common.atr(price_data=frame)
        self.assertTrue(result.iloc[:9].isna().all())
        self.assertEqual(result.iloc[9:].tolist(), [2., 2.])
        market = {
            'A': pd.DataFrame({'trade_close': [1., 2., 8., 16.]}),
            'B': pd.DataFrame({'trade_close': [16., 8., 2., 1.]}),
        }
        expected = pd.DataFrame([[1., -1.], [-1., 1.]], index=['A', 'B'], columns=['A', 'B'])
        assert_frame_equal(common.calc_corr_matrix(market_data=market, price_column='trade_close'), expected)
        assert_frame_equal(frame, original)

    def test_risk_ratio_and_annual_volatility_keywords_preserve_results(self):
        self.assertEqual(common.calc_position_size(
            equity=10000., atr_value=1., price=10., stop_atr_multiple=2.,
            max_trade_risk_ratio=.05), 200)
        history = [1., 2.718281828459045, 20.085536923187668]
        original = history.copy()
        leverage = common.calc_leverage_by_vol(
            equity_history=history, volatility_window=3, periods_per_year=1,
            target_annual_volatility=.25, min_leverage=.3, max_leverage=2.)
        self.assertAlmostEqual(leverage, .499999000002)
        self.assertEqual(common.calc_leverage_by_vol(
            equity_history=[100.], volatility_window=3, periods_per_year=252,
            target_annual_volatility=.1, min_leverage=2., max_leverage=3.), 1.)
        self.assertEqual(history, original)


class PortfolioKeywordsTest(unittest.TestCase):
    def setUp(self):
        self.timestamp = pd.Timestamp('2026-01-06')
        self.entry_time = pd.Timestamp('2026-01-05')
        self.position = dict(qty=100, side=1, entry=10., entry_time=self.entry_time,
                             stop=9., atr=1.)
        self.market = {
            'A': pd.DataFrame({'close': [12.]}, index=[self.timestamp]),
            'B': pd.DataFrame({'close': [7.]}, index=[self.entry_time]),
        }

    def test_stop_allocation_budget_and_snapshot_keywords(self):
        positions = {'A': self.position.copy(), 'B': self.position.copy()}
        original = deepcopy(positions)
        stops = common.calc_stop_positions(
            market_data=self.market, positions=positions, timestamp=self.timestamp,
            stop_atr_multiple=2.)
        self.assertEqual(stops['A']['stop'], 10.)
        self.assertEqual(stops['B'], self.position)
        allocated = common.rebalance_portfolio(
            market_data=self.market, positions=positions, timestamp=self.timestamp,
            allocation_budget=6000., quantity_change_threshold_ratio=.2)
        self.assertEqual(allocated['A']['qty'], 200)
        self.assertEqual(allocated['A']['entry'], 12.)
        self.assertEqual(allocated['B'], self.position)
        self.assertEqual(common.build_portfolio_snapshot(
            market_data=self.market, positions=positions, timestamp=self.timestamp,
            equity=2000.), [(self.timestamp, 'A', 100, 1200.),
                            (self.timestamp, 'B', 0, 0),
                            (self.timestamp, 'cash', 800., 800.)])
        self.assertEqual(positions, original)

    def test_candidate_and_current_positions_keywords(self):
        current = {'A': self.position.copy()}
        candidates = {'A': dict(self.position, entry=12., entry_time=self.timestamp)}
        original = deepcopy((current, candidates))
        normalized = common.normalize_positions(
            candidate_positions=candidates, current_positions=current)
        self.assertEqual(normalized, current)
        self.assertEqual(common.calc_trade_records(
            market_data=self.market, timestamp=self.timestamp,
            candidate_positions=normalized, current_positions=current), [])
        changed = {'A': dict(candidates['A'], qty=200)}
        records = common.calc_trade_records(
            market_data=self.market, timestamp=self.timestamp,
            candidate_positions=changed, current_positions=current)
        self.assertEqual(records, [('A', 1, self.entry_time, self.timestamp, 200., '切换仓位')])
        self.assertIsInstance(records[0], common.Trade)
        self.assertEqual((current, candidates), original)


class AccountingKeywordsTest(unittest.TestCase):
    def test_equity_and_complete_marks_with_named_arguments(self):
        timestamp = pd.Timestamp('2026-01-06')
        market = {
            'A': pd.DataFrame({'close': [11., 12.]}, index=[timestamp, timestamp]),
            'B': pd.DataFrame({'close': [20.]}, index=[timestamp - pd.Timedelta(days=1)]),
            'C': pd.DataFrame({'close': [15.]}, index=[timestamp]),
        }
        positions = {'A': {'qty': 100}, 'B': {'qty': 50}, 'C': {'qty': 100}}
        previous = {'A': 10., 'B': 20., 'STALE': 7.}
        original = deepcopy((market, positions, previous))
        equity, marks = accounting.calc_equity_close(
            market_data=market, positions=positions, prev_close=previous,
            timestamp=timestamp, prev_equity=1000.)
        self.assertEqual(equity, 1200.)
        self.assertEqual(marks, {'A': 12., 'B': 20., 'C': 15., 'STALE': 7.})
        self.assertEqual(accounting.calc_mark_to_market_equity(
            quantities={'A': 100}, current_close={'A': 12.},
            prev_close=previous, prev_equity=1000.), 1200.)
        self.assertEqual(accounting.build_close_marks(
            current_close={'A': 12., 'C': 15.}, prev_close=previous), marks)
        for symbol in market:
            assert_frame_equal(market[symbol], original[0][symbol])
        self.assertEqual((positions, previous), original[1:])


class MomentumIndicatorKeywordsTest(unittest.TestCase):
    def test_preprocessing_windows_with_named_arguments(self):
        frame = pd.DataFrame({'close': [10., 12., 13.], 'high': [11., 13., 14.],
                              'low': [9., 11., 12.]}, index=pd.date_range('2026-01-01', periods=3))
        original = frame.copy(deep=True)
        result = momentum.preprocess(
            market_data={'A': frame}, atr_window=2, short_window=1,
            long_window=2, volatility_window=2)['A']
        self.assertTrue(pd.isna(result['atr'].iloc[0]))
        self.assertEqual(result['atr'].iloc[1:].tolist(), [2.5, 2.5])
        expected_factor = ((1. / 12.) * .7 + .3 * .3) / ((.2 - 1. / 12.) / np.sqrt(2))
        self.assertAlmostEqual(result['factor'].iloc[2], expected_factor)
        self.assertTrue(result['factor'].iloc[:2].isna().all())
        assert_frame_equal(frame, original)
        self.assertIsNot(result, frame)

    def test_custom_and_default_factor_columns_skip_missing_quotes_and_nan(self):
        timestamp = pd.Timestamp('2026-01-06')
        market = {
            'A': pd.DataFrame({'score': [2.], 'factor': [3.]}, index=[timestamp]),
            'B': pd.DataFrame({'score': [3.], 'factor': [2.]}, index=[timestamp]),
            'C': pd.DataFrame({'score': [np.nan], 'factor': [np.nan]}, index=[timestamp]),
            'D': pd.DataFrame({'score': [100.], 'factor': [100.]}, index=[timestamp - pd.Timedelta(days=1)]),
        }
        original = deepcopy(market)
        ranked = momentum.rank_factor(market_data=market, timestamp=timestamp, factor_column='score')
        pd.testing.assert_series_equal(ranked, pd.Series({'B': 3., 'A': 2.}))
        default = momentum.rank_factor(market_data=market, timestamp=timestamp)
        pd.testing.assert_series_equal(default, pd.Series({'A': 3., 'B': 2.}))
        for symbol in market:
            assert_frame_equal(market[symbol], original[symbol])


class MomentumSelectionKeywordsTest(unittest.TestCase):
    def setUp(self):
        self.timestamp = pd.Timestamp('2026-01-06')
        self.market = {
            symbol: pd.DataFrame({'close': [price], 'atr': [atr]}, index=[self.timestamp])
            for symbol, price, atr in [('A', 10., 1.), ('B', 20., 2.),
                                       ('C', 30., 3.), ('D', 40., 4.)]
        }
        self.ranks = pd.Series({'A': 3., 'B': 2., 'C': -1., 'D': -2.})
        self.position = dict(qty=100, side=1, entry=10.,
                             entry_time=self.timestamp - pd.Timedelta(days=1),
                             stop=9., atr=1.)

    def test_retention_rank_boundary_and_suspension(self):
        self.market['C'].index = [self.timestamp - pd.Timedelta(days=1)]
        positions = {symbol: self.position.copy() for symbol in ['A', 'B', 'C']}
        original = deepcopy(positions)
        retained = momentum.select_retained_positions(
            market_data=self.market, positions=positions, ranked_factors=self.ranks,
            timestamp=self.timestamp, retention_rank_limit=1)
        self.assertEqual(set(retained), {'A', 'C'})
        self.assertIsNot(retained['A'], positions['A'])
        self.assertIsNot(retained['C'], positions['C'])
        self.assertEqual(positions, original)
        positions['A']['stop'] = 10.
        self.assertEqual(set(momentum.select_retained_positions(
            market_data=self.market, positions=positions, ranked_factors=self.ranks,
            timestamp=self.timestamp, retention_rank_limit=1)), {'C'})

    def test_held_symbol_consumes_candidate_limit_and_negative_factor_stops_scan(self):
        held = {'A': self.position.copy()}
        original = deepcopy((self.market, held, self.ranks))
        arguments = dict(market_data=self.market, held_positions=held,
                         ranked_factors=self.ranks, timestamp=self.timestamp,
                         equity=10000., stop_atr_multiple=2., max_trade_risk_ratio=.05)
        self.assertEqual(momentum.calc_buy_pos(**arguments, candidate_limit=1), ({}, {}))
        expected = ({'B': dict(qty=100, side=1, entry=20., entry_time=self.timestamp,
                              stop=16., atr=2.)}, {'B': 20.})
        self.assertEqual(momentum.calc_buy_pos(**arguments, candidate_limit=2), expected)
        self.assertEqual(momentum.calc_buy_pos(**arguments, candidate_limit=4), expected)
        for symbol in self.market:
            assert_frame_equal(self.market[symbol], original[0][symbol])
        self.assertEqual(held, original[1])
        pd.testing.assert_series_equal(self.ranks, original[2])


if __name__ == '__main__':
    unittest.main()
