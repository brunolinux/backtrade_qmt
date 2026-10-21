from copy import deepcopy
import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

import strategy_momentum as strategy
import strategy_momentum_v2 as strategy_v2
import strategy_common


class PreprocessInputsTest(unittest.TestCase):
    def test_preprocess_returns_independent_sorted_deduplicated_market(self):
        dates = pd.to_datetime(['2026-01-07', '2026-01-05', '2026-01-06', '2026-01-06'])
        prices = [13., 10., 11., 12.]
        frame = pd.DataFrame({'raw_close': [6.5, 5., 5.5, 6.], 'close': prices, 'high': [p + 1 for p in prices],
                              'low': [p - 1 for p in prices]}, index=dates)
        original = frame.copy(deep=True)
        market = {'A': frame}
        for module, args in [(strategy, (2, 2, 2)), (strategy_v2, (2, 1, 2, 2))]:
            with self.subTest(module=module.__name__):
                processed = module.preprocess(market, *args)
                self.assertIs(market['A'], frame)
                assert_frame_equal(frame, original)
                self.assertIsNot(processed, market)
                self.assertEqual(processed['A'].index.tolist(), sorted(set(dates)))
                self.assertEqual(processed['A']['close'].tolist(), [10., 12., 13.])
                self.assertEqual(processed['A']['raw_close'].tolist(), [5., 6., 6.5])
                self.assertEqual(processed['A']['atr'].iloc[1:].tolist(), [2.5, 2.5])
                if module is strategy:
                    self.assertEqual(processed['A']['ma'].iloc[1:].tolist(), [11., 12.5])
                    self.assertEqual(processed['A']['sig_long'].tolist(), [False] * 3)
                else:
                    self.assertAlmostEqual(processed['A']['factor'].iloc[-1], 1.798071529)
                repeated = module.preprocess(market, *args)
                assert_frame_equal(processed['A'], repeated['A'])
                processed['A'].iloc[0, 0] = 999.
                assert_frame_equal(frame, original)

    def test_preprocess_empty_market_returns_fresh_dictionary(self):
        for module, args in [(strategy, (2, 2, 2)), (strategy_v2, (2, 1, 2, 2))]:
            with self.subTest(module=module.__name__):
                market = {}
                processed = module.preprocess(market, *args)
                self.assertEqual(processed, {})
                self.assertIsNot(processed, market)


class BuySignalInputsTest(unittest.TestCase):
    def test_old_buy_selection_sorts_locally_and_is_repeatable(self):
        time = pd.Timestamp('2026-01-06')
        signals = [('WEAK', 1, .5, 10., 1., 10.), ('STRONG', 1, 2., 20., 1., 20.)]
        original = deepcopy(signals)
        results = []
        for _ in range(2):
            positions, marks = strategy.calc_buy_pos(signals, time, 10000., 1, 2., 3., .05)
            self.assertEqual(signals, original)
            self.assertEqual(positions, {'STRONG': strategy_common.Position(
                side=1, trade_raw_close=20., sig_entry=20., trade_entry_time=time, sig_stop=18., sig_take=23., sig_atr=1., trade_qty=200,
            )})
            self.assertEqual(marks, {'STRONG': 20.})
            results.append((positions, marks))
        self.assertEqual(results[0], results[1])
        self.assertEqual(strategy.calc_buy_pos(signals, time, 10., 1, 2., 3., .05), ({}, {}))

    def test_old_take_survives_state_transitions_and_still_exits_at_target(self):
        entry_time = pd.Timestamp('2026-01-05')
        timestamp = pd.Timestamp('2026-01-06')
        positions, _ = strategy.calc_buy_pos(
            [('A', 1, 1., 10., 1., 10.)], entry_time, 10000., 1, 2., 5., .05)
        self.assertIsInstance(positions['A'], strategy_common.Position)
        self.assertEqual(positions['A'].sig_take, 15.)
        market = {'A': pd.DataFrame({'raw_close': [12.], 'close': [12.]}, index=[timestamp])}
        stopped = strategy.calc_stop_positions(market, positions, timestamp, 2.)
        retained = strategy.select_retained_positions(market, stopped, timestamp)
        allocated = strategy.rebalance_portfolio(market, retained, timestamp, 6000., .2)
        normalized = strategy.preserve_entries_for_unchanged_quantities(allocated, retained)
        for result in (stopped, retained, allocated, normalized):
            self.assertEqual(result['A'].sig_take, 15.)
            self.assertIsNot(result, positions)
        self.assertEqual(positions['A'].sig_stop, 8.)
        market['A'].loc[timestamp, 'close'] = 15.
        self.assertEqual(strategy.select_retained_positions(market, normalized, timestamp), {})


class RetainedPositionsTest(unittest.TestCase):
    def test_both_strategies_return_independent_retained_mappings(self):
        time = pd.Timestamp('2026-01-06')
        market = {
            'A': pd.DataFrame({'raw_close': [12.], 'close': [12.]}, index=[time]),
            'B': pd.DataFrame({'raw_close': [10.], 'close': [10.]}, index=[time - pd.Timedelta(days=1)]),
        }
        positions = {sym: strategy_common.Position(
            trade_qty=100, trade_raw_close=10., sig_entry=10., trade_entry_time=time - pd.Timedelta(days=1),
            sig_stop=9., sig_take=15., sig_atr=1., side=1) for sym in market}
        original = deepcopy(positions)
        original_market = deepcopy(market)
        for module in (strategy, strategy_v2):
            with self.subTest(module=module.__name__):
                if module is strategy:
                    result = module.select_retained_positions(market, positions, time)
                else:
                    ranks = pd.Series({'A': 2.})
                    result = module.select_retained_positions(market, positions, ranks, time, 1)
                self.assertEqual(result, original)
                self.assertIsNot(result, positions)
                result['A'] = result['A']._replace(trade_qty=999)
                result['OUTPUT_ONLY'] = result.pop('B')._replace(sig_stop=999.)
                self.assertEqual(positions, original)
                for sym in market:
                    assert_frame_equal(market[sym], original_market[sym])


class NormalizePositionsTest(unittest.TestCase):
    def test_normalization_preserves_inputs_and_returns_new_mapping(self):
        old_time = pd.Timestamp('2026-01-05')
        new_time = pd.Timestamp('2026-01-06')
        old_record = strategy_common.Position(trade_qty=100, side=1, trade_raw_close=10., sig_entry=10.,
                                             trade_entry_time=old_time, sig_stop=9., sig_atr=1., sig_take=15.)
        cases = [
            ({'A': old_record}, old_record._replace(trade_raw_close=12., sig_entry=12., trade_entry_time=new_time), old_record),
            ({'A': old_record}, old_record._replace(trade_raw_close=12., sig_entry=12.), old_record._replace(trade_raw_close=12., sig_entry=12.)),
            ({'A': old_record}, old_record._replace(trade_qty=200, trade_raw_close=12., sig_entry=12., trade_entry_time=new_time),
             old_record._replace(trade_qty=200, trade_raw_close=12., sig_entry=12., trade_entry_time=new_time)),
            ({}, old_record._replace(trade_raw_close=12., sig_entry=12., trade_entry_time=new_time),
             old_record._replace(trade_raw_close=12., sig_entry=12., trade_entry_time=new_time)),
            ({'A': old_record}, old_record._replace(trade_raw_close=12., sig_entry=12., trade_entry_time=new_time, sig_take=20.),
             old_record._replace(sig_take=20.)),
        ]
        for old, candidate, expected in cases:
            with self.subTest(old=old, candidate=candidate):
                new = {'A': candidate}
                original = deepcopy((old, new))
                result = strategy_common.preserve_entries_for_unchanged_quantities(new, old)
                self.assertEqual(result, {'A': expected})
                self.assertEqual((old, new), original)
                self.assertEqual(strategy_common.preserve_entries_for_unchanged_quantities(new, old), result)
                self.assertIsNot(result, new)
                result['OUTPUT_ONLY'] = result.pop('A')._replace(trade_raw_close=999., sig_entry=999.)
                self.assertEqual((old, new), original)
        new = {}
        result = strategy_common.preserve_entries_for_unchanged_quantities(new, {'A': old_record})
        self.assertEqual(result, {})
        self.assertIsNot(result, new)


if __name__ == '__main__':
    unittest.main()
