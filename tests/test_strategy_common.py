from copy import deepcopy
import unittest

import pandas as pd
from pandas.testing import assert_frame_equal, assert_series_equal

import strategy_momentum as legacy
import strategy_common as common


class PositionTest(unittest.TestCase):
    def test_named_fields_and_optional_take(self):
        position = common.Position(qty=100, side=1, entry=10.,
                                   entry_time=pd.Timestamp('2026-01-05'), stop=9., atr=1.)
        self.assertEqual(position.qty, 100)
        self.assertIsNone(position.take)
        self.assertEqual(position._fields,
                         ('qty', 'side', 'entry', 'entry_time', 'stop', 'atr', 'take'))
        with self.assertRaises(TypeError):
            common.Position(qty=100)
        with self.assertRaises(TypeError):
            _ = position['qty']
        with self.assertRaises(AttributeError):
            position.stop = 12.

    def test_replacement_preserves_original_and_all_other_fields(self):
        original = common.Position(qty=-100, side=-1, entry=10.,
                                   entry_time=pd.Timestamp('2026-01-05'),
                                   stop=9., atr=1., take=15.)
        changed = original._replace(stop=11.)
        self.assertEqual(original.stop, 9.)
        self.assertEqual(changed.stop, 11.)
        self.assertEqual(changed._asdict(), dict(original._asdict(), stop=11.))


class PriceRiskBaselineTest(unittest.TestCase):
    module = legacy

    def test_getv_uses_last_duplicate_and_returns_nan_for_unreadable_values(self):
        frame = pd.DataFrame({'close': [10., 12.]}, index=[1, 1])
        original = frame.copy(deep=True)
        self.assertEqual(self.module.getv(frame, 1, 'close'), 12.)
        for time, col in [(2, 'close'), (1, 'missing')]:
            self.assertTrue(pd.isna(self.module.getv(frame, time, col)))
        invalid = pd.DataFrame({'close': ['invalid']}, index=[1])
        self.assertTrue(pd.isna(self.module.getv(invalid, 1, 'close')))
        assert_frame_equal(frame, original)

    def test_atr_uses_true_range_and_rolling_mean_without_mutating_prices(self):
        frame = pd.DataFrame({'high': [11., 14., 15.], 'low': [9., 12., 10.],
                              'close': [10., 13., 11.]})
        original = frame.copy(deep=True)
        # True ranges: 2, 4, 5; two-day rolling means: NaN, 3, 4.5.
        assert_series_equal(self.module.atr(frame, 2), pd.Series([float('nan'), 3., 4.5]))
        assert_frame_equal(frame, original)

    def test_correlation_uses_log_returns_and_skips_missing_columns(self):
        market = {
            'A': pd.DataFrame({'close': [1., 2., 8., 16.]}),
            'B': pd.DataFrame({'close': [16., 8., 2., 1.]}),
            'MISSING': pd.DataFrame({'other': [1., 2., 3., 4.]}),
        }
        original = deepcopy(market)
        expected = pd.DataFrame([[1., -1.], [-1., 1.]], index=['A', 'B'], columns=['A', 'B'])
        assert_frame_equal(self.module.calc_corr_matrix(market), expected)
        for sym in market:
            assert_frame_equal(market[sym], original[sym])

    def test_quantity_and_position_size_preserve_lot_risk_and_capital_limits(self):
        self.assertEqual(self.module.calc_quantity(299.9, 100), 200)
        self.assertEqual(self.module.calc_quantity(-299.9, 100), -200)
        self.assertEqual(self.module.calc_position_size(10000., 1., 10., 2., .05), 200)
        self.assertEqual(self.module.calc_position_size(1000., 1., 3., 1., 1.), 300)
        self.assertEqual(self.module.calc_position_size(1000., 0., 3., 1., 1.), 0)

    def test_leverage_preserves_warmup_scaling_and_bounds(self):
        calc = self.module.calc_leverage_by_vol
        self.assertEqual(calc([100.], 3, 1, .1, .3, 2.), 1.)
        # Log returns 1 and 2 have std 0.5; target 0.25 gives approximately 0.5.
        history = [1., 2.718281828459045, 20.085536923187668]
        original = history.copy()
        self.assertAlmostEqual(calc(history, 3, 1, .25, .3, 2.), .499999000002)
        self.assertEqual(calc(history, 3, 1, .01, .3, 2.), .3)
        self.assertEqual(calc([100., 100., 100.], 3, 1, .1, .3, 2.), 2.)
        self.assertEqual(history, original)


class SharedPriceRiskTest(PriceRiskBaselineTest):
    @classmethod
    def setUpClass(cls):
        import strategy_common
        cls.module = strategy_common


class PortfolioBaselineTest(unittest.TestCase):
    module = legacy

    def setUp(self):
        self.time = pd.Timestamp('2026-01-06')
        self.entry_time = pd.Timestamp('2026-01-05')

    def position(self, **changes):
        result = dict(qty=100, side=1, entry=10., entry_time=self.entry_time,
                      stop=9., atr=1.)
        result.update(changes)
        return common.Position(**result)

    def market(self):
        return {
            'A': pd.DataFrame({'close': [12.]}, index=[self.time]),
            'SUSPENDED': pd.DataFrame({'close': [7.]}, index=[self.entry_time]),
            'UNHELD': pd.DataFrame({'close': [99.]}, index=[self.time]),
        }

    def test_stop_only_rises_and_suspended_holdings_are_unchanged(self):
        market = self.market()
        original_market = deepcopy(market)
        positions = {'A': self.position(), 'SUSPENDED': self.position()}
        original_positions = deepcopy(positions)
        old_record = positions['A']
        updated = self.module.calc_stop_positions(market, positions, self.time, 2.)
        self.assertEqual(updated, {'A': self.position(stop=10.),
                                   'SUSPENDED': self.position()})
        self.assertEqual(positions, original_positions)
        self.assertEqual(old_record, self.position())
        repeated = self.module.calc_stop_positions(market, positions, self.time, 2.)
        self.assertEqual(updated, repeated)
        lower_stop = self.module.calc_stop_positions(market, updated, self.time, 4.)
        self.assertEqual(lower_stop['A'].stop, 10.)
        self.assertIsNot(updated, positions)
        updated['A'] = updated['A']._replace(stop=999.)
        updated['OUTPUT_ONLY'] = updated.pop('SUSPENDED')._replace(qty=0)
        self.assertEqual(positions, original_positions)
        empty = {}
        result = self.module.calc_stop_positions({}, empty, self.time, 2.)
        self.assertEqual(result, {})
        self.assertIsNot(result, empty)
        for sym in market:
            assert_frame_equal(market[sym], original_market[sym])

    def test_portfolio_rebalance_returns_new_mapping_and_respects_threshold(self):
        market = self.market()
        original_market = deepcopy(market)
        positions = {'A': self.position(), 'SUSPENDED': self.position()}
        original = deepcopy(positions)
        updated = self.module.rebalance_portfolio(market, positions, self.time, 6000., .2)
        self.assertEqual(updated, {
            'A': self.position(qty=200, entry=12., entry_time=self.time),
            'SUSPENDED': self.position(),
        })
        self.assertEqual(positions, original)
        for sym in market:
            assert_frame_equal(market[sym], original_market[sym])
        self.assertIsNot(updated, positions)
        updated['A'] = updated['A']._replace(qty=999)
        updated['SUSPENDED'] = updated['SUSPENDED']._replace(stop=999.)
        self.assertEqual(positions, original)
        unchanged = self.module.rebalance_portfolio(market, {'A': self.position()}, self.time, 1440., .2)
        self.assertEqual(unchanged, {'A': self.position(entry=12., entry_time=self.time)})
        self.assertEqual(self.module.rebalance_portfolio({}, {}, self.time, 1000., .2), {})

    def test_budget_shortage_clips_even_below_threshold_and_preserves_take(self):
        original = {'A': self.position(take=15.)}
        result = self.module.rebalance_portfolio(
            self.market(), original, self.time, 600., 100.)
        self.assertEqual(result, {})
        result = self.module.rebalance_portfolio(
            self.market(), original, self.time, 3000., .2)
        self.assertEqual(result, {'A': self.position(
            qty=200, entry=12., entry_time=self.time, take=15.)})
        clipped = self.module.rebalance_portfolio(
            self.market(), {'A': self.position(qty=200, take=15.)}, self.time, 1800., 100.)
        self.assertEqual(clipped, {'A': self.position(
            qty=100, entry=12., entry_time=self.time, take=15.)})
        self.assertEqual(original, {'A': self.position(take=15.)})

    def test_trade_records_and_unchanged_quantity_normalization(self):
        market = self.market()
        old = {'A': self.position()}
        original = deepcopy(old)
        records = self.module.calc_trade_records(market, self.time, {}, old)
        self.assertEqual(records, [('A', 1, self.entry_time, self.time, 200., '止盈')])
        self.assertIsInstance(records[0], self.module.Trade)
        new = {'A': self.position(entry=12., entry_time=self.time)}
        candidate = deepcopy(new)
        self.assertEqual(self.module.calc_trade_records(market, self.time, new, old), [])
        normalized = self.module.preserve_entries_for_unchanged_quantities(new, old)
        self.assertEqual(normalized, original)
        self.assertEqual(new, candidate)
        self.assertEqual(old, original)

    def test_portfolio_info_preserves_rows_cash_and_inputs(self):
        market = self.market()
        positions = {'A': self.position(), 'SUSPENDED': self.position()}
        original = deepcopy(positions)
        rows = self.module.build_portfolio_snapshot(market, positions, self.time, 2000.)
        self.assertEqual(rows, [(self.time, 'A', 100, 1200.),
                                (self.time, 'SUSPENDED', 0, 0),
                                (self.time, 'UNHELD', 0, 0),
                                (self.time, 'cash', 800., 800.)])
        self.assertTrue(all(isinstance(row, common.PortfolioRow) for row in rows))
        self.assertIsInstance(rows[0], tuple)
        self.assertEqual(rows[0]._fields, ('datetime', 'symbol', 'quantity', 'value'))
        self.assertEqual((rows[0].datetime, rows[0].symbol, rows[0].quantity, rows[0].value),
                         (self.time, 'A', 100, 1200.))
        self.assertEqual((rows[-1].symbol, rows[-1].quantity, rows[-1].value),
                         ('cash', 800., 800.))
        self.assertEqual(positions, original)


class SharedCompatibilityTest(unittest.TestCase):
    def test_old_and_v2_trade_records_use_shared_type(self):
        import strategy_common
        import strategy_momentum_v2

        time = pd.Timestamp('2026-01-06')
        entry_time = pd.Timestamp('2026-01-05')
        market = {'A': pd.DataFrame({'close': [12.]}, index=[time])}
        old = {'A': common.Position(qty=100, side=1, entry=10., entry_time=entry_time,
                                    stop=9., atr=1.)}
        for module in (legacy, strategy_momentum_v2):
            with self.subTest(module=module.__name__):
                record, = module.calc_trade_records(market, time, {}, old)
                self.assertIsInstance(record, strategy_common.Trade)
                self.assertEqual((record.symbol, record.pnl, record.exit_reason),
                                 ('A', 200., '止盈'))


class SharedPortfolioTest(PortfolioBaselineTest):
    @classmethod
    def setUpClass(cls):
        import strategy_common
        cls.module = strategy_common


if __name__ == '__main__':
    unittest.main()
