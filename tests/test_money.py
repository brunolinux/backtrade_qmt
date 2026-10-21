import math
import unittest

from money import calc_notional, calc_price_pnl, round_money, sum_money


class MoneyTest(unittest.TestCase):
    def test_half_cents_round_away_from_zero(self):
        for value, expected in [(1.005, 1.01), (-1.005, -1.01), (2.675, 2.68)]:
            with self.subTest(value=value):
                self.assertEqual(round_money(value), expected)

    def test_prices_are_not_rounded_before_amounts(self):
        self.assertEqual(calc_notional(100, 2.626), 262.6)
        self.assertEqual(calc_price_pnl(100, 2.627, 2.626), .1)
        self.assertEqual(calc_price_pnl(1, 2.675, 0), 2.68)

    def test_sum_rounds_each_independent_amount(self):
        self.assertEqual(sum_money([.005, .005]), .02)
        self.assertEqual(sum_money([.1, .2, -.3]), 0)
        self.assertEqual(sum_money([]), 0)

    def test_nonfinite_values_are_not_fabricated_or_rejected(self):
        self.assertTrue(math.isnan(round_money(float('nan'))))
        self.assertTrue(math.isnan(sum_money([1, float('nan')])))
        self.assertTrue(math.isnan(calc_price_pnl(100, float('nan'), 2.626)))
        self.assertEqual(round_money(float('inf')), float('inf'))
        self.assertTrue(math.isnan(sum_money([float('inf'), -float('inf')])))
