from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pandas as pd
from openpyxl import load_workbook

import backtest_etf_v2 as script
from strategy_common import Trade


class BacktestScriptTest(unittest.TestCase):
    def test_script_writes_workbook_and_keeps_historical_csv(self):
        timestamp = pd.Timestamp('2026-01-06')
        portfolio = pd.DataFrame([
            (timestamp, '159650', 100., 262.6),
            (timestamp, 'cash', 737.4, 737.4),
        ], columns=['datetime', 'symbol', 'quantity', 'value']).set_index('datetime')
        trades = pd.DataFrame([], columns=Trade._fields)
        curve = pd.DataFrame({'equity': [1000.]}, index=[timestamp])
        with TemporaryDirectory() as temp:
            history = Path(temp) / 'trade.csv'
            history.write_text('historical data', encoding='utf-8')
            with patch.object(script, 'getETFFundsInfo', return_value=pd.DataFrame(
                    {'name': ['示例基金']}, index=['159650'])), \
                    patch.object(script, 'getFundsDataDict', return_value={}), \
                    patch.object(script, 'backtest', return_value=(portfolio, curve, trades)), \
                    patch('matplotlib.pyplot.show'), patch.object(pd.DataFrame, 'plot'):
                script.main(output_dir=temp)
            self.assertEqual(sorted(path.name for path in Path(temp).iterdir()),
                             ['backtest_results.xlsx', 'trade.csv'])
            self.assertEqual(history.read_text(encoding='utf-8'), 'historical data')
            workbook = load_workbook(Path(temp) / 'backtest_results.xlsx')
            self.assertEqual(list(workbook['portfolio_qty'].values),
                             [('datetime', '159650.SZ'), (timestamp.to_pydatetime(), 100)])
            self.assertEqual(workbook['portfolio_value']['D2'].value, 1000.)
            workbook.close()
