"""Exercise the embedded strategy with fake QMT APIs; never connect a client."""

import ast
from copy import deepcopy
from contextlib import redirect_stdout
import datetime as dt
from io import StringIO
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
import threading
from unittest.mock import Mock


SCRIPT = Path(__file__).resolve().parents[1] / "qmt_passorder.py"


def load_strategy():
    spec = importlib.util.spec_from_file_location("qmt_strategy_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    module.get_trade_detail_data = Mock(side_effect=AssertionError("unexpected account read"))
    module.passorder = Mock(side_effect=AssertionError("unexpected real order"))
    spec.loader.exec_module(module)
    return module


def position(code, total, available):
    symbol, exchange = code.split(".")
    return SimpleNamespace(m_strInstrumentID=symbol, m_strExchangeID=exchange,
                           m_nVolume=total, m_nCanUseVolume=available)


class FakeContext:
    def __init__(self):
        self.accounts = []
        self.timers = []
        self.lifecycle = "init"
        self.days = ["20261016", "20261019"]

    def set_account(self, account):
        self.accounts.append(account)

    def get_trading_dates(self, code, start, end, count, period):
        if self.lifecycle != "after_init":
            raise AssertionError("calendar is unavailable in init")
        return [day for day in self.days if day <= end][-count:]

    def run_time(self, *args):
        self.timers.append(args)


class StrategyTestCase(unittest.TestCase):
    def setUp(self):
        self.strategy = load_strategy()
        self.strategy.ACCOUNT_ID = "testaccount"
        self.strategy.TARGET_QUANTITIES = {"159650.SZ": 400, "512800.SH": 100}
        self.strategy.TOTAL_VALUE = 10000
        self.clock = dt.datetime(2026, 10, 19, 9, 34, tzinfo=dt.timezone(dt.timedelta(hours=8)))
        self.strategy._now = lambda: self.clock
        self.account = SimpleNamespace(m_dBalance=10000., m_dAvailable=0., m_dInstrumentValue=10000.)
        self.positions = [position("159650.SZ", 300, 300), position("512800.SH", 300, 300)]
        self.queries = []

        def query(account, kind, category):
            self.queries.append((account, kind, category))
            if category == "ACCOUNT":
                return [self.account]
            if category == "POSITION":
                return self.positions
            raise AssertionError("unexpected query " + category)

        self.strategy.get_trade_detail_data = query
        self.orders = []
        self.strategy.passorder = lambda *args: self.orders.append(args)
        self.context = FakeContext()
        self.output = StringIO()
        self.redirect = redirect_stdout(self.output)
        self.redirect.__enter__()
        self.addCleanup(self.redirect.__exit__, None, None, None)

    def start(self):
        try:
            self.strategy.init(self.context)
        except SystemExit:
            # An invalid static configuration can exit before after_init.
            return
        self.context.lifecycle = "after_init"
        self.strategy.after_init(self.context)


class InitializationTest(StrategyTestCase):
    def test_valid_account_with_equal_assets_and_no_available_cash(self):
        self.assertTrue(callable(getattr(self.strategy, "init", None)), "initialization missing")
        self.start()
        self.assertEqual(self.context.accounts, ["testaccount"])
        self.assertTrue(self.strategy._state.ready)
        self.assertEqual([q[2] for q in self.queries], ["ACCOUNT", "POSITION"])
        self.assertEqual(self.orders, [])

    def test_beijing_clock_is_explicit(self):
        strategy = load_strategy()
        self.assertEqual(strategy._now().utcoffset(), dt.timedelta(hours=8))

    def test_invalid_configs_never_schedule_or_submit(self):
        cases = [
            ("ACCOUNT_ID", "xxx"), ("ACCOUNT_ID", ""),
            ("TRADE_DATE", dt.date(2026, 10, 20)),
            ("SIGNAL_DATE", dt.date(2026, 10, 15)),
            ("TRADE_DATE", "20261019"),
            ("TARGET_QUANTITIES", {"159650.SH": 100}),
            ("TARGET_QUANTITIES", {"600000.SH": 100}),
            ("TARGET_QUANTITIES", {"159650.SZ": True}),
            ("TARGET_QUANTITIES", {"159650.SZ": 100.0}),
            ("TARGET_QUANTITIES", {"159650.SZ": -100}),
            ("TARGET_QUANTITIES", {"159650.SZ": 50}),
            ("TARGET_QUANTITIES", []),
            ("TOTAL_VALUE", 10001), ("TOTAL_VALUE", 0),
            ("TOTAL_VALUE", float("nan")), ("TOTAL_VALUE", float("inf")),
            ("TOTAL_VALUE", True),
        ]
        for name, value in cases:
            with self.subTest(name=name, value=value):
                original = getattr(self.strategy, name)
                setattr(self.strategy, name, value)
                self.context = FakeContext()
                self.start()
                self.assertFalse(self.strategy._state.ready)
                self.assertEqual(self.context.timers, [])
                self.assertEqual(self.orders, [])
                setattr(self.strategy, name, original)
        self.assertIn("Initialization failed", self.output.getvalue())

    def test_missing_calendar_and_nontrading_day_are_rejected(self):
        for days in ([], ["20261016"], ["20261015", "20261019"]):
            with self.subTest(days=days):
                self.context = FakeContext()
                self.context.days = days
                self.start()
                self.assertFalse(self.strategy._state.ready)
                self.assertEqual(self.context.timers, [])

    def test_invalid_account_fields_or_positions_are_rejected(self):
        for field in ("m_dBalance", "m_dAvailable", "m_dInstrumentValue"):
            for value in (None, float("nan"), float("inf"), -1):
                with self.subTest(field=field, value=value):
                    original = getattr(self.account, field)
                    setattr(self.account, field, value)
                    self.context = FakeContext()
                    self.start()
                    self.assertFalse(self.strategy._state.ready)
                    self.assertEqual(self.context.timers, [])
                    setattr(self.account, field, original)
        for total, available in ((-1, 0), (100, 101), (100, -1), (100.5, 100)):
            self.positions = [position("159650.SZ", total, available)]
            self.context = FakeContext()
            self.start()
            self.assertFalse(self.strategy._state.ready)
            self.assertEqual(self.context.timers, [])

    def test_account_query_failure_disables_execution(self):
        self.strategy.get_trade_detail_data = Mock(side_effect=RuntimeError("offline"))
        self.start()
        self.assertFalse(self.strategy._state.ready)
        self.assertEqual(self.context.timers, [])
        self.assertIn("offline", self.output.getvalue())


class PlanTest(StrategyTestCase):
    def test_initial_differences_are_new_immutable_plans(self):
        self.assertTrue(callable(getattr(self.strategy, "build_plans", None)), "planner missing")
        holdings = {"159650.SZ": self.strategy.Holding(300, 300),
                    "512800.SH": self.strategy.Holding(600, 600)}
        targets = {"159650.SZ": 400, "512800.SH": 400}
        before = deepcopy((holdings, targets))
        sells, buys = self.strategy.build_plans(holdings, targets)
        self.assertEqual(tuple(sells), (("512800.SH", 24, 200),))
        self.assertEqual(tuple(buys), (("159650.SZ", 23, 100),))
        self.assertIsInstance(sells, tuple)
        self.assertIsInstance(buys, tuple)
        self.assertEqual((holdings, targets), before)

    def test_lots_liquidation_and_sellable_limits(self):
        scenarios = [
            (600, 100, 400, 100, 0),
            (650, 650, 400, 200, 0),
            (650, 650, 0, 650, 0),
            (650, 550, None, 550, 0),
            (650, 0, 0, 0, 0),
            (350, 350, 400, 0, 0),
            (250, 250, 400, 0, 100),
            (400, 400, 400, 0, 0),
        ]
        for total, available, target, sell_qty, buy_qty in scenarios:
            with self.subTest(total=total, available=available, target=target):
                holdings = {"159650.SZ": self.strategy.Holding(total, available)}
                targets = {} if target is None else {"159650.SZ": target}
                sells, buys = self.strategy.build_plans(holdings, targets)
                self.assertEqual(sum(p.quantity for p in sells), sell_qty)
                self.assertEqual(sum(p.quantity for p in buys), buy_qty)

    def test_snapshot_rejects_duplicate_positions_before_any_order(self):
        self.positions = [position("512800.SH", 300, 300),
                          position("159650.SZ", 100, 50),
                          position("159650.SZ", 200, 150)]
        self.start()
        self.assertFalse(self.strategy._state.ready)
        self.assertEqual(self.context.timers, [])
        self.assertEqual(self.orders, [])
        self.assertIn("159650.SZ", self.output.getvalue())
        self.assertIn("duplicate", self.output.getvalue().lower())

    def test_snapshot_keeps_distinct_etfs_as_separate_holdings(self):
        self.start()
        self.assertEqual(self.strategy._state.snapshot.holdings, {
            "159650.SZ": (300, 300), "512800.SH": (300, 300)})

    def test_empty_targets_liquidate_all_supported_sellable_holdings(self):
        self.strategy.TARGET_QUANTITIES = {}
        self.start()
        self.assertEqual(self.strategy._state.sell_plan, (
            ("159650.SZ", 24, 300), ("512800.SH", 24, 300)))
        self.assertEqual(self.strategy._state.buy_plan, ())
        self.assertIn("Initial account", self.output.getvalue())
        self.assertIn("Sell plan", self.output.getvalue())


class TimerTest(StrategyTestCase):
    def at(self, hour, minute, second):
        self.clock = self.clock.replace(hour=hour, minute=minute, second=second)
        self.strategy.refresh(self.context)

    def test_strict_thresholds_repeated_calls_and_empty_handlebar(self):
        self.start()
        self.assertEqual(len(self.context.timers), 1, "timer is not registered")
        self.assertEqual(self.context.timers[0][:2], ("refresh", "3nSecond"))
        self.strategy.handlebar(self.context)
        self.assertEqual(self.orders, [])
        self.at(9, 35, 0)
        self.assertEqual(self.orders, [])
        self.at(9, 35, 3)
        self.at(9, 35, 6)
        self.assertEqual([(o[0], o[3], o[6]) for o in self.orders], [(24, "512800.SH", 200)])
        self.at(9, 36, 0)
        self.assertEqual(len(self.orders), 1)
        self.at(9, 36, 3)
        self.at(9, 37, 0)
        self.assertEqual([(o[0], o[3], o[6]) for o in self.orders], [
            (24, "512800.SH", 200), (23, "159650.SZ", 100)])

    def test_delayed_callback_sells_then_buys_without_waiting(self):
        self.start()
        self.at(9, 36, 3)
        self.assertEqual([o[0] for o in self.orders], [24, 23])

    def test_frozen_plan_survives_account_and_config_changes(self):
        self.start()
        queries = list(self.queries)
        self.positions.clear()
        self.account.m_dAvailable = 99999
        self.strategy.TARGET_QUANTITIES.clear()
        self.at(9, 36, 3)
        self.assertEqual([o[6] for o in self.orders], [200, 100])
        self.assertEqual(self.queries, queries)

    def test_empty_plans_and_repeated_after_init_submit_nothing(self):
        self.positions = []
        self.strategy.TARGET_QUANTITIES = {}
        self.start()
        self.strategy.after_init(self.context)
        self.at(9, 36, 3)
        self.at(9, 37, 0)
        self.assertEqual(self.orders, [])
        self.assertEqual(len(self.context.timers), 1)

    def test_synchronous_exception_does_not_retry_or_stop_next_symbol(self):
        self.start()

        def submit(*args):
            self.orders.append(args)
            if args[0] == 24:
                raise RuntimeError("submission offline")

        self.strategy.passorder = submit
        self.at(9, 36, 3)
        self.at(9, 37, 0)
        self.assertEqual([o[0] for o in self.orders], [24, 23])
        self.assertIn("submission offline", self.output.getvalue())

    def test_market_payload_and_full_quantity_with_zero_cash(self):
        self.start()
        self.at(9, 36, 3)
        sell, buy = self.orders
        self.assertEqual(sell[:7], (24, 1101, "testaccount", "512800.SH", 42, 0, 200))
        self.assertEqual(buy[:7], (23, 1101, "testaccount", "159650.SZ", 47, -1, 100))
        for order in self.orders:
            self.assertEqual(order[8], 2)
            self.assertIs(order[10], self.context)
            self.assertIn("20261019", order[9])
        self.assertNotEqual(sell[9], buy[9])

    def test_reentrant_and_concurrent_timer_does_not_interleave_phases(self):
        self.start()
        entered = threading.Event()
        release = threading.Event()

        def submit(*args):
            self.orders.append(args)
            self.strategy.refresh(self.context)
            if args[0] == 24:
                entered.set()
                if not release.wait(2):
                    raise RuntimeError("test failed to release order")

        self.strategy.passorder = submit
        self.clock = self.clock.replace(minute=36, second=3)
        worker = threading.Thread(target=self.strategy.refresh, args=(self.context,), daemon=True)
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            self.strategy.refresh(self.context)
            self.assertEqual([o[0] for o in self.orders], [24])
        finally:
            release.set()
            worker.join(2)
        self.assertFalse(worker.is_alive(), "timer deadlock")
        self.assertEqual([o[0] for o in self.orders], [24, 23])

    def test_state_survives_context_replacement_without_custom_attributes(self):
        class QmtContext(FakeContext):
            def __setattr__(self, name, value):
                if name == "qmt_state":
                    raise TypeError("QMT must not deepcopy trading state or thread locks")
                super().__setattr__(name, value)

        self.context = QmtContext()
        self.start()
        self.at(9, 36, 3)
        self.context = QmtContext()
        self.at(9, 37, 0)
        self.assertEqual([o[0] for o in self.orders], [24, 23])


class CallbackTest(StrategyTestCase):
    def submit_all(self):
        self.start()
        self.clock = self.clock.replace(minute=36, second=3)
        self.strategy.refresh(self.context)
        self.output.seek(0)
        self.output.truncate(0)

    def event(self, order, **fields):
        return SimpleNamespace(m_strAccountID="testaccount", m_strRemark=order[9], **fields)

    def test_native_callbacks_filter_account_and_registered_remark(self):
        self.assertTrue(callable(getattr(self.strategy, "order_callback", None)), "callbacks missing")
        self.submit_all()
        order = self.orders[0]
        before = (self.strategy._state.sell_plan, self.strategy._state.buy_plan)
        for event in (
                SimpleNamespace(m_strAccountID="other", m_strRemark=order[9]),
                SimpleNamespace(m_strAccountID="testaccount", m_strRemark="other-strategy"),
                SimpleNamespace(m_strRemark=order[9]), SimpleNamespace()):
            self.strategy.order_callback(self.context, event)
            self.strategy.deal_callback(self.context, event)
        self.assertEqual(self.output.getvalue(), "")
        self.strategy.order_callback(self.context, self.event(
            order, m_nOrderStatus=57, m_strCancelInfo="insufficient funds", m_nVolumeTraded=0))
        output = self.output.getvalue()
        self.assertIn("REJECTED", output)
        self.assertIn("insufficient funds", output)
        self.assertIn("512800.SH", output)
        self.assertIn("SELL", output)
        self.assertEqual((self.strategy._state.sell_plan, self.strategy._state.buy_plan), before)
        self.assertEqual(len(self.orders), 2)

    def test_deal_prices_quantities_and_new_old_missing_fees(self):
        self.submit_all()
        for fields, fee in (({"m_dCommission": 1.25, "m_dComission": 99}, "1.25"),
                            ({"m_dComission": 2.5}, "2.50"),
                            ({"m_dCommission": 0}, "0.00"),
                            ({"m_dCommission": None, "m_dComission": 3}, "3.00"),
                            ({"m_dCommission": float("nan")}, "unknown"), ({}, "unknown")):
            with self.subTest(fields=fields):
                self.output.seek(0)
                self.output.truncate(0)
                self.strategy.deal_callback(self.context, self.event(
                    self.orders[1], m_dPrice=1.237, m_nVolume=50, **fields))
                text = self.output.getvalue()
                self.assertIn("Deal", text)
                self.assertIn("BUY 159650.SZ", text)
                self.assertIn("price=1.237", text)
                self.assertIn("shares=50", text)
                self.assertIn("fee=" + fee, text)

    def test_partial_deal_cancel_and_missing_optional_fields_never_resubmit(self):
        self.submit_all()
        order = self.orders[1]
        self.strategy.deal_callback(self.context, self.event(order, m_dPrice=1.237, m_nVolume=50))
        self.strategy.order_callback(self.context, self.event(order, m_nOrderStatus=53, m_nVolumeTraded=50))
        self.strategy.deal_callback(self.context, self.event(order))
        self.strategy.order_callback(self.context, self.event(order))
        self.strategy.refresh(self.context)
        self.assertEqual(len(self.orders), 2)
        self.assertIn("PART_CANCELLED", self.output.getvalue())
        self.assertIn("price=unknown", self.output.getvalue())

    def test_qmt_error_argument_shape_is_filtered_and_reported(self):
        self.submit_all()
        order = self.orders[1]
        args = SimpleNamespace(accountID="testaccount", orderCode="SZ159650", opType=23,
                               strategyName=self.strategy.STRATEGY_NAME + "_&&&_" + order[9])
        self.strategy.orderError_callback(self.context, args, "insufficient funds")
        self.assertIn("Order error", self.output.getvalue())
        self.assertIn("BUY 159650.SZ", self.output.getvalue())
        self.assertIn("insufficient funds", self.output.getvalue())
        self.output.seek(0)
        self.output.truncate(0)
        args.accountID = "other"
        self.strategy.orderError_callback(self.context, args, "ignore")
        args.accountID = "testaccount"
        args.strategyName = "other_&&&_" + order[9]
        self.strategy.orderError_callback(self.context, args, "ignore")
        self.assertEqual(self.output.getvalue(), "")

    def test_synchronous_error_callback_during_buy_continues_with_other_buys(self):
        self.positions = []
        self.start()

        def submit(*args):
            self.orders.append(args)
            error = SimpleNamespace(accountID=args[2], orderCode=args[3], opType=args[0],
                                    strategyName=args[7] + "_&&&_" + args[9])
            self.strategy.orderError_callback(self.context, error, "insufficient funds")
            self.strategy.order_callback(self.context, self.event(args, m_nOrderStatus=57))
            self.strategy.refresh(self.context)

        self.strategy.passorder = submit
        self.clock = self.clock.replace(minute=36, second=3)
        self.strategy.refresh(self.context)
        self.strategy.refresh(self.context)
        self.assertEqual([(o[3], o[6]) for o in self.orders], [("159650.SZ", 400), ("512800.SH", 100)])
        self.assertEqual(self.output.getvalue().count("Order error"), 2)


class ScriptCompatibilityTest(unittest.TestCase):
    def test_script_exists_and_import_has_no_trading_side_effects(self):
        self.assertTrue(SCRIPT.is_file(), "embedded strategy has not been created")
        source_bytes = SCRIPT.read_bytes()
        source = source_bytes.decode("gb2312")
        self.assertEqual(source.encode("gb2312"), source_bytes)
        self.assertIn("coding: gb2312", source.splitlines()[0])
        ast.parse(source, feature_version=(3, 6))
        strategy = load_strategy()
        strategy.get_trade_detail_data.assert_not_called()
        strategy.passorder.assert_not_called()
        self.assertEqual(strategy.ACCOUNT_ID, "xxx")
        for name in ("SIGNAL_DATE", "TRADE_DATE", "TARGET_QUANTITIES", "TOTAL_VALUE"):
            self.assertTrue(hasattr(strategy, name), name)


if __name__ == "__main__":
    unittest.main()
