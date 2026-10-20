import ast
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd

import strategy_momentum as strategy


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
            "entry": 10.0,
            "entry_time": self.entry_time,
            "stop": 9.0,
            "atr": 0.5,
            "qty": 100,
            "side": 1,
        }
        position.update(changes)
        return position

    def market(self, price):
        return {"ETF_A": pd.DataFrame({"close": [price]}, index=[self.exit_time])}

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
                records = strategy.update_trades(
                    self.market(price), self.exit_time, {},
                    {"ETF_A": self.position()},
                )
                self.assert_trade(records, pnl, reason)

    def test_rebalance_preserves_existing_full_position_pnl(self):
        new_pos = {"ETF_A": self.position(
            qty=200, entry=12.0, entry_time=self.exit_time,
        )}
        records = strategy.update_trades(
            self.market(12.0), self.exit_time, new_pos,
            {"ETF_A": self.position()},
        )
        self.assert_trade(records, 200.0, "切换仓位")
        self.assertEqual(new_pos["ETF_A"]["qty"], 200)
        self.assertEqual(new_pos["ETF_A"]["entry_time"], self.exit_time)

    def test_same_day_and_zero_quantity_close_do_not_generate_trades(self):
        for position in [self.position(entry_time=self.exit_time),
                         self.position(qty=0)]:
            with self.subTest(position=position):
                self.assertEqual(strategy.update_trades(
                    self.market(12.0), self.exit_time, {}, {"ETF_A": position},
                ), [])

    def test_same_entry_time_and_zero_old_quantity_rebalance_are_skipped(self):
        for old_position, new_position in [
            (self.position(), self.position(qty=200)),
            (self.position(qty=0), self.position(
                qty=200, entry=12.0, entry_time=self.exit_time,
            )),
        ]:
            with self.subTest(old_position=old_position):
                self.assertEqual(strategy.update_trades(
                    self.market(12.0), self.exit_time,
                    {"ETF_A": new_position}, {"ETF_A": old_position},
                ), [])

    def test_unchanged_quantity_restores_original_entry_information(self):
        original = self.position()
        new_pos = {"ETF_A": self.position(entry=12.0, entry_time=self.exit_time)}
        records = strategy.update_trades(
            self.market(12.0), self.exit_time, new_pos, {"ETF_A": original},
        )
        self.assertEqual(records, [])
        self.assertEqual(new_pos["ETF_A"], original)

    def test_both_backtests_preserve_empty_and_nonempty_trade_tables(self):
        records = strategy.update_trades(
            self.market(12.0), self.exit_time, {}, {"ETF_A": self.position()},
        )
        baseline = [("ETF_A", 1, self.entry_time, self.exit_time, 200.0, "止盈")]
        for filename in ["strategy_momentum.py", "strategy_momentum_v2.py"]:
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
        records = strategy.update_trades(
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
