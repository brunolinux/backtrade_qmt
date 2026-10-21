import ast
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd

import strategy_momentum as strategy
import strategy_momentum_v2 as strategy_v2
from strategy_common import Position


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRADE_COLUMNS = ["symbol", "side", "entry_time", "exit_time", "pnl", "exit_reason"]


def execute_statements(nodes, filename, scope):
    """执行实际转换和导出语句，避免启动行情加载及整个回测。"""
    module = ast.Module(body=nodes, type_ignores=[])
    exec(compile(module, str(filename), "exec"), scope)


class TradeRecordsTest(unittest.TestCase):
    def setUp(self):
        self.entry_time = pd.Timestamp("2026-01-05")
        self.exit_time = pd.Timestamp("2026-01-06")

    def position(self, **changes):
        position = {
            'trade_raw_close': 10.0, 'sig_entry': 10.0,
            'trade_entry_time': self.entry_time,
            'sig_stop': 9.0,
            'sig_atr': 0.5,
            'trade_qty': 100,
            "side": 1,
        }
        position.update(changes)
        return Position(**position)

    def market(self, price):
        return {"ETF_A": pd.DataFrame({'raw_close': [price], "close": [price]}, index=[self.exit_time])}

    def assert_trade(self, records, pnl, reason):
        expected = ("ETF_A", 1, self.entry_time, self.exit_time, pnl, reason)
        self.assertEqual(records, [expected])
        trade = records[0]
        self.assertTrue(hasattr(trade, "pnl"), "交易记录应支持具名字段访问")
        self.assertIsInstance(trade, strategy.Trade)
        self.assertEqual(
            (trade.symbol, trade.side, trade.entry_time, trade.exit_time,
             trade.pnl, trade.exit_reason),
            expected,
        )

    def test_close_records_preserve_profit_loss_and_reason(self):
        for price, pnl, reason in [(12.0, 200.0, "止盈"),
                                   (8.0, -200.0, "止损"),
                                   (10.0, 0.0, "止损")]:
            with self.subTest(price=price):
                records = strategy.calc_trade_records(
                    self.market(price), self.exit_time, {},
                    {"ETF_A": self.position()},
                )
                self.assert_trade(records, pnl, reason)

    def test_rebalance_preserves_existing_full_position_pnl(self):
        for qty in [200, 50]:
            with self.subTest(qty=qty):
                new_pos = {"ETF_A": self.position(
                    trade_qty=qty, trade_raw_close=12.0, sig_entry=12.0, trade_entry_time=self.exit_time,
                )}
                records = strategy.calc_trade_records(
                    self.market(12.0), self.exit_time, new_pos,
                    {"ETF_A": self.position()},
                )
                self.assert_trade(records, 200.0, "切换仓位")
                self.assertEqual(new_pos["ETF_A"].trade_qty, qty)
                self.assertEqual(new_pos["ETF_A"].trade_entry_time, self.exit_time)

    def test_same_day_and_zero_quantity_close_do_not_generate_trades(self):
        for position in [self.position(trade_entry_time=self.exit_time),
                         self.position(trade_qty=0)]:
            with self.subTest(position=position):
                self.assertEqual(strategy.calc_trade_records(
                    self.market(12.0), self.exit_time, {}, {"ETF_A": position},
                ), [])

    def test_same_entry_time_and_zero_old_quantity_rebalance_are_skipped(self):
        for old_position, new_position in [
            (self.position(), self.position(trade_qty=200)),
            (self.position(trade_qty=0), self.position(
                trade_qty=200, trade_raw_close=12.0, sig_entry=12.0, trade_entry_time=self.exit_time,
            )),
        ]:
            with self.subTest(old_position=old_position):
                self.assertEqual(strategy.calc_trade_records(
                    self.market(12.0), self.exit_time,
                    {"ETF_A": new_position}, {"ETF_A": old_position},
                ), [])

    def test_unchanged_quantity_restores_original_entry_information(self):
        original = self.position()
        new_pos = {"ETF_A": self.position(trade_raw_close=12.0, sig_entry=12.0, trade_entry_time=self.exit_time)}
        candidate = deepcopy(new_pos)
        normalized = strategy.preserve_entries_for_unchanged_quantities(new_pos, {"ETF_A": original})
        records = strategy.calc_trade_records(
            self.market(12.0), self.exit_time, normalized, {"ETF_A": original},
        )
        self.assertEqual(records, [])
        self.assertEqual(normalized["ETF_A"], original)
        self.assertEqual(new_pos, candidate)

    def test_record_calculation_preserves_all_inputs_and_is_repeatable(self):
        market = self.market(12.0)
        original_market = deepcopy(market)
        old_pos = {"ETF_A": self.position()}
        original_old = deepcopy(old_pos)
        for new_pos in [{}, {"ETF_A": self.position(trade_raw_close=12.0, sig_entry=12.0, trade_entry_time=self.exit_time)},
                        {"ETF_A": self.position(trade_qty=200, trade_raw_close=12.0, sig_entry=12.0, trade_entry_time=self.exit_time)}]:
            with self.subTest(new_pos=new_pos):
                original_new = deepcopy(new_pos)
                first = strategy.calc_trade_records(market, self.exit_time, new_pos, old_pos)
                second = strategy.calc_trade_records(market, self.exit_time, new_pos, old_pos)
                self.assertEqual(first, second)
                self.assertEqual(new_pos, original_new)
                self.assertEqual(old_pos, original_old)
                pd.testing.assert_frame_equal(market['ETF_A'], original_market['ETF_A'])

    def test_both_backtests_preserve_empty_and_nonempty_trade_tables(self):
        records = strategy.calc_trade_records(
            self.market(12.0), self.exit_time, {}, {"ETF_A": self.position()},
        )
        baseline = [("ETF_A", 1, self.entry_time, self.exit_time, 200.0, "止盈")]
        for filename in ["strategy_momentum.py", "strategy_momentum_v2.py"]:
            if filename == "strategy_momentum_v2.py":
                for values, expected_rows in [(records, baseline), ([], [])]:
                    with self.subTest(filename=filename, empty=not values):
                        _, _, trades = strategy_v2.build_backtest_results([], [], values)
                        expected = pd.DataFrame(expected_rows, columns=TRADE_COLUMNS)
                        pd.testing.assert_frame_equal(trades, expected)
                continue
            path = PROJECT_ROOT / filename
            tree = ast.parse(path.read_text(encoding="utf-8"))
            backtest = next(node for node in tree.body
                            if isinstance(node, ast.FunctionDef) and node.name == "backtest")
            # 直接运行调用方的 DataFrame 转换语句，保留实际列名和参数。
            conversion = next(node for node in backtest.body
                              if isinstance(node, ast.Assign)
                              and any(isinstance(target, ast.Name) and target.id == "trades"
                                      for target in node.targets)
                              and isinstance(node.value, ast.Call))
            for values, expected_rows in [(records, baseline), ([], [])]:
                with self.subTest(filename=filename, empty=not values):
                    scope = {"pd": pd, "trades": values}
                    execute_statements([conversion], path, scope)
                    expected = pd.DataFrame(expected_rows, columns=TRADE_COLUMNS)
                    pd.testing.assert_frame_equal(scope["trades"], expected)

    def test_csv_export_matches_ordinary_tuple_baseline(self):
        records = strategy.calc_trade_records(
            self.market(12.0), self.exit_time, {}, {"ETF_A": self.position()},
        )
        path = PROJECT_ROOT / "backtest_etf_v2.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        main = next(node for node in tree.body if isinstance(node, ast.If))
        prepare = next(node for node in main.body
                       if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == "trades"
                               for target in node.targets))
        export = next(node for node in main.body
                      if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                      and isinstance(node.value.func, ast.Attribute)
                      and isinstance(node.value.func.value, ast.Name)
                      and node.value.func.value.id == "trades"
                      and node.value.func.attr == "to_csv")
        for values, expected_rows in [
            (records, [("ETF_A", 1, self.entry_time, self.exit_time, 200.0, "止盈")]),
            ([], []),
        ]:
            with self.subTest(empty=not values), TemporaryDirectory() as temp:
                scope = {
                    "pd": pd,
                    "trades": pd.DataFrame(values, columns=TRADE_COLUMNS),
                    "symbols": {"ETF_A": "示例基金"},
                    "sub_dir": temp,
                }
                execute_statements([prepare, export], path, scope)
                expected = pd.DataFrame(expected_rows, columns=TRADE_COLUMNS)
                expected = pd.concat([
                    pd.Series(["示例基金"] * len(expected), name="symbol", dtype=object),
                    expected,
                ], axis=1)
                exported = (Path(temp) / "trade.csv").read_bytes()
                self.assertEqual(exported,
                                 expected.to_csv(index=False).encode("gb2312"))


if __name__ == "__main__":
    unittest.main()
