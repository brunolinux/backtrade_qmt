from copy import deepcopy
from contextlib import redirect_stdout
from io import StringIO
import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

import strategy_momentum_v2 as momentum
from strategy_common import Position, PortfolioRow, Trade


class BacktestResultsTest(unittest.TestCase):
    def test_named_rows_keep_result_tables_identical_to_positional_rows(self):
        timestamp = pd.Timestamp('2026-01-06')
        portfolio_row = PortfolioRow(datetime=timestamp, symbol='A', quantity=100, value=1200.)
        equity_row = momentum.EquityRow(datetime=timestamp, equity=1500.)
        trade = Trade('A', 1, timestamp, timestamp, 200., '止盈')
        self.assertEqual(portfolio_row._fields, ('datetime', 'symbol', 'quantity', 'value'))
        self.assertEqual(equity_row._fields, ('datetime', 'equity'))
        self.assertEqual(trade._fields,
                         ('symbol', 'side', 'entry_time', 'exit_time', 'pnl', 'exit_reason'))
        self.assertEqual((portfolio_row.symbol, equity_row.equity), ('A', 1500.))
        named_rows = ([portfolio_row], [equity_row], [trade])
        before = deepcopy(named_rows)
        named_tables = momentum.build_backtest_results(*named_rows)
        positional_tables = momentum.build_backtest_results(
            [(timestamp, 'A', 100, 1200.)], [(timestamp, 1500.)], [tuple(trade)])
        for named_table, positional_table in zip(named_tables, positional_tables):
            assert_frame_equal(named_table, positional_table)
        self.assertEqual(named_rows, before)

    def test_empty_results_preserve_columns_index_and_dtypes(self):
        rows = ([], [], [])
        results = momentum.build_backtest_results(*rows)
        expected = (
            pd.DataFrame(columns=['symbol', 'quantity', 'value'],
                         index=pd.Index([], name='datetime', dtype=object)),
            pd.DataFrame(columns=['equity'],
                         index=pd.Index([], name='datetime', dtype=object)),
            pd.DataFrame(columns=['symbol', 'side', 'entry_time', 'exit_time', 'pnl', 'exit_reason']),
        )
        for actual, table in zip(results, expected):
            assert_frame_equal(actual, table)
        self.assertEqual(rows, ([], [], []))

    def test_nonempty_results_preserve_values_order_and_input_records(self):
        timestamp = pd.Timestamp('2026-01-06')
        entry_time = pd.Timestamp('2026-01-05')
        rows = ([(timestamp, 'A', 100, 1200.), (timestamp, 'cash', 300., 300.)],
                [(timestamp, 1500.)],
                [Trade('A', 1, entry_time, timestamp, 200., '止盈')])
        before = deepcopy(rows)
        portfolio, curve, trades = momentum.build_backtest_results(*rows)
        expected_portfolio = pd.DataFrame(
            {'symbol': ['A', 'cash'], 'quantity': [100., 300.], 'value': [1200., 300.]},
            index=pd.DatetimeIndex([timestamp, timestamp], name='datetime'))
        expected_curve = pd.DataFrame(
            {'equity': [1500.]}, index=pd.DatetimeIndex([timestamp], name='datetime'))
        expected_trades = pd.DataFrame({
            'symbol': ['A'], 'side': [1], 'entry_time': [entry_time],
            'exit_time': [timestamp], 'pnl': [200.], 'exit_reason': ['止盈'],
        })
        for actual, expected in zip((portfolio, curve, trades),
                                    (expected_portfolio, expected_curve, expected_trades)):
            assert_frame_equal(actual, expected)
        self.assertEqual(rows, before)


class DailyPositionsTest(unittest.TestCase):
    def setUp(self):
        self.timestamp = pd.Timestamp('2026-01-06')
        self.entry_time = pd.Timestamp('2026-01-05')
        self.params = dict(atr_stop=2., top_num_reserve=3, hold_max_num=1,
                           max_risk_per_trade=1., window_vol=3, annual_factor=252,
                           target_vol=.3, min_lev=1., max_lev=1., pos_change_threshold=.2)
        self.position = Position(trade_qty=100, side=1, trade_raw_close=10., sig_entry=10., trade_entry_time=self.entry_time,
                                 sig_stop=8., sig_atr=1.)

    def market(self, **quotes):
        return {symbol: pd.DataFrame({'raw_close': [price], 'close': [price], 'atr': [1.], 'factor': [score]},
                                     index=[self.timestamp])
                for symbol, (price, score) in quotes.items()}

    def calculate(self, market, positions, marks, params, equity=10000.):
        history = [equity]
        before = deepcopy((market, positions, marks, history, params))
        first = momentum.calc_daily_positions(
            market_data=market, positions=positions, close_marks=marks,
            timestamp=self.timestamp, equity=equity, equity_history=history, params=params)
        second = momentum.calc_daily_positions(
            market, positions, marks, self.timestamp, equity, history, params)
        self.assertEqual(first, second)
        self.assertIsNot(first[0], positions)
        self.assertIsNot(first[1], marks)
        first[0]['OUTPUT_ONLY'] = self.position
        first[1]['OUTPUT_ONLY'] = 999.
        del first[0]['OUTPUT_ONLY'], first[1]['OUTPUT_ONLY']
        for symbol in market:
            assert_frame_equal(market[symbol], before[0][symbol])
        self.assertEqual((positions, marks, history, params), before[1:])
        return first

    def test_full_portfolio_raises_stop_without_rebalancing(self):
        positions, marks, trades = self.calculate(
            self.market(A=(12., 1.)), {'A': self.position}, {'A': 12., 'STALE': 7.}, self.params)
        self.assertEqual(positions, {'A': self.position._replace(sig_stop=10.)})
        self.assertEqual(marks, {'A': 12., 'STALE': 7.})
        self.assertEqual(trades, [])

    def test_available_slot_rebalances_even_when_scan_finds_only_held_symbol(self):
        positions, marks, trades = self.calculate(
            self.market(A=(12., 1.)), {'A': self.position}, {'A': 12., 'STALE': 7.},
            dict(self.params, hold_max_num=2))
        self.assertEqual(positions, {'A': self.position._replace(
            trade_qty=800, trade_raw_close=12., sig_entry=12., trade_entry_time=self.timestamp, sig_stop=10.)})
        self.assertEqual(marks, {'A': 12., 'STALE': 7.})
        self.assertEqual(trades, [Trade('A', 1, self.entry_time, self.timestamp, 200., '切换仓位')])

    def test_exits_precede_rebalance_and_marks_include_suspended_and_new_holdings(self):
        market = self.market(A=(8., 1.), B=(20., 3.), C=(12., 2.))
        market['D'] = pd.DataFrame({'raw_close': [7.], 'close': [7.]}, index=[self.entry_time])
        original = {'A': self.position._replace(sig_stop=9.), 'C': self.position,
                    'D': self.position._replace(trade_raw_close=7., sig_entry=7., sig_stop=6.)}
        previous = {'A': 8., 'C': 12., 'D': 7., 'STALE': 99.}
        params = dict(self.params, hold_max_num=3)
        positions, marks, trades = self.calculate(market, original, previous, params)
        self.assertEqual(positions, {
            'C': self.position._replace(trade_qty=200, trade_raw_close=12., sig_entry=12., trade_entry_time=self.timestamp, sig_stop=10.),
            'D': original['D'],
            'B': Position(trade_qty=100, side=1, trade_raw_close=20., sig_entry=20., trade_entry_time=self.timestamp, sig_stop=18., sig_atr=1.),
        })
        self.assertEqual(marks, dict(previous, B=20.))
        self.assertEqual(trades, [
            Trade('A', 1, self.entry_time, self.timestamp, -200., '止损'),
            Trade('C', 1, self.entry_time, self.timestamp, 200., '切换仓位'),
        ])
        positions, marks, _ = self.calculate(market, original, previous, params, equity=1000.)
        self.assertEqual(positions, {'D': original['D']})
        self.assertEqual(marks, dict(previous, B=20.))


class BacktestFlowTest(unittest.TestCase):
    def setUp(self):
        self.dates = pd.date_range('2026-01-05', periods=6)
        prices = [10., 11., 13., 14., 12., 11.]
        self.market = {'A': pd.DataFrame({
            'raw_close': prices, 'close': prices, 'high': [p + 1 for p in prices], 'low': [p - 1 for p in prices],
        }, index=self.dates)}
        self.params = dict(
            init_equity=10000., window_atr=2, window_short=1, window_long=2,
            window_vol=2, atr_stop=1., top_num_reserve=1, hold_max_num=2,
            max_risk_per_trade=1., annual_factor=252, target_vol=.3,
            min_lev=1., max_lev=1., pos_change_threshold=.2)

    def run_backtest(self, market, params, start_date=None):
        original_market, original_params = deepcopy((market, params))
        frames = market.copy()
        output = StringIO()
        with redirect_stdout(output):
            results = momentum.backtest(market_data=market, params=params, start_date=start_date)
        self.assertEqual(params, original_params)
        self.assertEqual(list(market), list(original_market))
        for symbol in market:
            self.assertIs(market[symbol], frames[symbol])
            assert_frame_equal(market[symbol], original_market[symbol])
        return results, output.getvalue()

    def test_current_equity_controls_leverage_only_when_portfolio_has_available_slots(self):
        params = dict(self.params, window_vol=3, min_lev=.3)
        for capacity, quantities, equities in [
            (1, [0., 0., 0., 700., 700., 0.], [10000.] * 4 + [8600., 7900.]),
            (2, [0., 0., 0., 700., 200., 0.], [10000.] * 4 + [8600., 8400.]),
        ]:
            with self.subTest(capacity=capacity):
                (portfolio, curve, trades), output = self.run_backtest(
                    self.market, dict(params, hold_max_num=capacity))
                # 当日权益从 10000 跌至 8600；含当日值的历史令杠杆降至 0.3。
                self.assertEqual(portfolio.loc[portfolio.symbol == 'A', 'quantity'].tolist(), quantities)
                self.assertEqual(curve.equity.tolist(), equities)
                if capacity == 1:
                    self.assertEqual(trades.pnl.tolist(), [-2100.])
                else:
                    self.assertEqual(trades.pnl.tolist(), [-1400., -200.])
                    self.assertEqual(trades.exit_reason.tolist(), ['切换仓位', '止损'])
                    self.assertEqual(trades.entry_time.tolist(), [self.dates[3], self.dates[4]])
                self.assertEqual(output, '预处理计算\n' + ''.join(
                    '{} over!!!!\n'.format(timestamp) for timestamp in self.dates))

    def test_start_date_is_inclusive_and_preprocessing_uses_prior_history(self):
        (portfolio, curve, trades), output = self.run_backtest(
            self.market, self.params, start_date=str(self.dates[2].date()))
        expected_portfolio = pd.DataFrame({
            'symbol': ['A', 'cash'] * 4,
            'quantity': [700., 900., 700., 900., 700., 900., 0., 8600.],
            'value': [9100., 900., 9800., 900., 8400., 900., 0., 8600.],
        }, index=pd.DatetimeIndex(self.dates[2:].repeat(2), name='datetime'))
        expected_curve = pd.DataFrame(
            {'equity': [10000., 10700., 9300., 8600.]},
            index=pd.DatetimeIndex(self.dates[2:], name='datetime'))
        expected_trades = pd.DataFrame({
            'symbol': ['A'], 'side': [1], 'entry_time': [self.dates[2]],
            'exit_time': [self.dates[5]], 'pnl': [-1400.], 'exit_reason': ['止损'],
        })
        assert_frame_equal(portfolio, expected_portfolio, check_freq=False)
        assert_frame_equal(curve, expected_curve, check_freq=False)
        assert_frame_equal(trades, expected_trades)
        self.assertEqual(output, '预处理计算\n' + ''.join(
            '{} over!!!!\n'.format(timestamp) for timestamp in self.dates[2:]))

    def test_empty_market_or_start_date_after_all_quotes_preserves_empty_tables(self):
        for market, start in [({}, None), (self.market, '2026-02-01')]:
            with self.subTest(empty=not market):
                results, output = self.run_backtest(market, self.params, start_date=start)
                expected = (
                    pd.DataFrame(columns=['symbol', 'quantity', 'value'],
                                 index=pd.Index([], name='datetime', dtype=object)),
                    pd.DataFrame(columns=['equity'],
                                 index=pd.Index([], name='datetime', dtype=object)),
                    pd.DataFrame(columns=['symbol', 'side', 'entry_time', 'exit_time', 'pnl', 'exit_reason']),
                )
                for actual, table in zip(results, expected):
                    assert_frame_equal(actual, table)
                self.assertEqual(output, '预处理计算\n')


if __name__ == '__main__':
    unittest.main()
