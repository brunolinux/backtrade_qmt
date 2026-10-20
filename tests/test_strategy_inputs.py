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
        frame = pd.DataFrame({'close': prices, 'high': [p + 1 for p in prices],
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
        signals = [('WEAK', 1, .5, 10., 1.), ('STRONG', 1, 2., 20., 1.)]
        original = deepcopy(signals)
        results = []
        for _ in range(2):
            positions, marks = strategy.calc_buy_pos(signals, time, 10000., 1, 2., 3., .05)
            self.assertEqual(signals, original)
            self.assertEqual(positions, {'STRONG': dict(
                side=1, entry=20., entry_time=time, stop=18., take=23., atr=1., qty=200,
            )})
            self.assertEqual(marks, {'STRONG': 20.})
            results.append((positions, marks))
        self.assertEqual(results[0], results[1])


class RetainedPositionsTest(unittest.TestCase):
    def test_both_strategies_return_independent_retained_records(self):
        time = pd.Timestamp('2026-01-06')
        market = {
            'A': pd.DataFrame({'close': [12.]}, index=[time]),
            'B': pd.DataFrame({'close': [10.]}, index=[time - pd.Timedelta(days=1)]),
        }
        positions = {sym: dict(qty=100, entry=10., entry_time=time - pd.Timedelta(days=1),
                               stop=9., take=15., atr=1., side=1) for sym in market}
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
                result['A']['qty'] = 999
                result['B']['stop'] = 999.
                self.assertEqual(positions, original)
                for sym in market:
                    assert_frame_equal(market[sym], original_market[sym])


class NormalizePositionsTest(unittest.TestCase):
    def test_normalization_preserves_inputs_and_returns_detached_records(self):
        old_time = pd.Timestamp('2026-01-05')
        new_time = pd.Timestamp('2026-01-06')
        old_record = dict(qty=100, entry=10., entry_time=old_time)
        cases = [
            ({'A': old_record}, dict(qty=100, entry=12., entry_time=new_time), old_record),
            ({'A': old_record}, dict(qty=100, entry=12., entry_time=old_time),
             dict(qty=100, entry=12., entry_time=old_time)),
            ({'A': old_record}, dict(qty=200, entry=12., entry_time=new_time),
             dict(qty=200, entry=12., entry_time=new_time)),
            ({}, dict(qty=100, entry=12., entry_time=new_time),
             dict(qty=100, entry=12., entry_time=new_time)),
        ]
        for old, candidate, expected in cases:
            with self.subTest(old=old, candidate=candidate):
                new = {'A': candidate}
                original = deepcopy((old, new))
                result = strategy_common.normalize_positions(new, old)
                self.assertEqual(result, {'A': expected})
                self.assertEqual((old, new), original)
                self.assertEqual(strategy_common.normalize_positions(new, old), result)
                result['A']['entry'] = 999.
                self.assertEqual((old, new), original)
        new = {}
        result = strategy_common.normalize_positions(new, {'A': old_record})
        self.assertEqual(result, {})
        self.assertIsNot(result, new)


if __name__ == '__main__':
    unittest.main()
