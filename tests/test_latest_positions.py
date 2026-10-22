from datetime import date
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

import print_latest_positions as report


class LatestPositionsReadTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'results.xlsx'
        self.quantities = pd.DataFrame({
            'datetime': [date(2026, 10, 22), date(2026, 10, 21)],
            '159650.SZ': [500., 100.], '518880.SH': [0., 200.],
            '512800.SH': [133400., 0.], '159941.SZ': [-100., 0.],
        })
        self.values = pd.DataFrame({
            'datetime': [date(2026, 10, 22), date(2026, 10, 23)],
            'cash': [38204.9, 999.],
            'total_value': [239253.9, 888888.],
        })

    def write_workbook(self, quantities=None, values=None):
        with pd.ExcelWriter(self.path, engine='openpyxl') as writer:
            (self.quantities if quantities is None else quantities).to_excel(
                writer, sheet_name='portfolio_qty', index=False)
            (self.values if values is None else values).to_excel(
                writer, sheet_name='portfolio_value', index=False)

    def test_latest_date_and_matching_cash_preserve_file_bytes(self):
        self.write_workbook()
        before = self.path.read_bytes()
        state = report.read_latest_positions(self.path)
        self.assertEqual(state.source_date, date(2026, 10, 22))
        self.assertEqual(state.positions, (
            ('159650.SZ', 500), ('518880.SH', 0),
            ('512800.SH', 133400), ('159941.SZ', -100)))
        self.assertEqual(state.cash, 38204.9)
        self.assertEqual(state.total_value, 239253.9)
        self.assertEqual(self.path.read_bytes(), before)

    def test_date_only_quantities_are_a_valid_cash_only_state(self):
        self.write_workbook(quantities=self.quantities[['datetime']])
        state = report.read_latest_positions(self.path)
        self.assertEqual(state.positions, ())
        self.assertEqual(state.cash, 38204.9)

    def test_missing_file_and_sheets_are_reported(self):
        with self.assertRaisesRegex(ValueError, 'results.xlsx'):
            report.read_latest_positions(self.path)
        self.quantities.to_excel(self.path, sheet_name='portfolio_qty', index=False)
        with self.assertRaisesRegex(ValueError, 'portfolio_value'):
            report.read_latest_positions(self.path)

    def test_empty_or_missing_columns_are_reported(self):
        for quantities, values in [
                (self.quantities.iloc[:0], self.values),
                (self.quantities.drop(columns='datetime'), self.values),
                (self.quantities, self.values.drop(columns='cash')),
                (self.quantities, self.values.drop(columns='datetime'))]:
            with self.subTest(columns=list(quantities.columns)):
                self.write_workbook(quantities, values)
                with self.assertRaises(ValueError):
                    report.read_latest_positions(self.path)

    def test_invalid_or_duplicate_dates_are_rejected_in_both_sheets(self):
        for sheet in ['quantities', 'values']:
            for dates in [['bad date', '2026-10-21'],
                          [None, '2026-10-21'],
                          ['NaT', '2026-10-21'],
                          [20261022, 20261021],
                          ['2026-10-22 09:00', '2026-10-22 15:00']]:
                with self.subTest(sheet=sheet, dates=dates):
                    quantities, values = self.quantities.copy(), self.values.copy()
                    frame = quantities if sheet == 'quantities' else values
                    frame['datetime'] = dates
                    self.write_workbook(quantities, values)
                    with self.assertRaisesRegex(ValueError, '日期'):
                        report.read_latest_positions(self.path)

    def test_missing_or_nonfinite_matching_cash_is_rejected(self):
        for cash in [None, float('inf'), 'bad cash']:
            with self.subTest(cash=cash):
                values = self.values.astype(object)
                values.loc[0, 'cash'] = cash
                self.write_workbook(values=values)
                with self.assertRaisesRegex(ValueError, 'cash'):
                    report.read_latest_positions(self.path)
        self.write_workbook(values=self.values.iloc[1:])
        with self.assertRaisesRegex(ValueError, 'cash'):
            report.read_latest_positions(self.path)

    def test_invalid_latest_quantities_are_not_silently_filtered(self):
        for quantity in [None, float('inf'), 100.5, 150, -150, 'bad quantity']:
            with self.subTest(quantity=quantity):
                quantities = self.quantities.astype(object)
                quantities.loc[0, '159650.SZ'] = quantity
                self.write_workbook(quantities=quantities)
                with self.assertRaisesRegex(ValueError, '159650.SZ'):
                    report.read_latest_positions(self.path)

    def test_missing_or_nonfinite_matching_total_value_is_rejected_without_output(self):
        invalid_tables = [self.values.drop(columns='total_value')]
        for amount in [None, float('inf'), 'bad total']:
            values = self.values.astype(object)
            values.loc[0, 'total_value'] = amount
            invalid_tables.append(values)
        for values in invalid_tables:
            with self.subTest(values=values):
                self.write_workbook(values=values)
                with self.assertRaisesRegex(ValueError, 'total_value'):
                    report.read_latest_positions(self.path)
                client = FixedCalendar(pd.DataFrame({'cal_date': ['20261023'], 'is_open': [1]}))
                code, stdout, stderr = self.run_command(['--workbook', str(self.path)], client)
                self.assertNotEqual(code, 0)
                self.assertEqual(stdout, '')
                self.assertIn('total_value', stderr)
                self.assertEqual(client.requests, [])

    def test_invalid_and_unsuffixed_codes_are_rejected(self):
        for code in ['159650', '159650.SH', 'ETF_A', 'cash']:
            with self.subTest(code=code):
                self.write_workbook(quantities=self.quantities.rename(columns={'159650.SZ': code}))
                with self.assertRaisesRegex(ValueError, code):
                    report.read_latest_positions(self.path)

    def run_command(self, argv, client=None):
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = report.main(argv, calendar_client=client)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_command_output_and_source_file_remain_exact(self):
        self.write_workbook()
        before = self.path.read_bytes()
        client = FixedCalendar(pd.DataFrame({'cal_date': ['20261023'], 'is_open': [1]}), noise='API log')
        code, stdout, stderr = self.run_command(['--workbook', str(self.path)], client)
        self.assertEqual((code, stderr), (0, ''))
        self.assertEqual(stdout, 'SIGNAL_DATE = dt.date(2026, 10, 22)\nTRADE_DATE = dt.date(2026, 10, 23)\n'
                         'TARGET_QUANTITIES = {\n    "159650.SZ": 500,\n    "512800.SH": 133400,\n}\n'
                         'TOTAL_VALUE = 239253.90\n现金: 38204.90\n总市值: 239253.90\n')
        self.assertEqual(self.path.read_bytes(), before)

    def test_default_path_is_independent_of_current_directory(self):
        self.write_workbook()
        original_cwd = Path.cwd()
        client = FixedCalendar(pd.DataFrame({'cal_date': ['20261023'], 'is_open': [1]}))
        self.assertEqual(report.DEFAULT_WORKBOOK,
                         Path(report.__file__).resolve().parent / 'data/output_v2/backtest_results.xlsx')
        try:
            os.chdir(self.temp.name)
            with patch.object(report, 'DEFAULT_WORKBOOK', self.path):
                code, stdout, stderr = self.run_command([], client)
            self.assertEqual((code, stderr), (0, ''))
            self.assertTrue(stdout.startswith('SIGNAL_DATE = dt.date(2026, 10, 22)\n'
                                              'TRADE_DATE = dt.date(2026, 10, 23)\n'))
            # 显式相对路径从调用目录解析。
            self.assertEqual(self.run_command(['--workbook', 'results.xlsx'], client)[0], 0)
        finally:
            os.chdir(original_cwd)

    def test_command_failures_do_not_leave_partial_stdout(self):
        self.write_workbook()
        client = FixedCalendar(error=RuntimeError('secret-token'), noise='secret-token')
        code, stdout, stderr = self.run_command(['--workbook', str(self.path)], client)
        self.assertNotEqual(code, 0)
        self.assertEqual(stdout, '')
        self.assertIn('交易日历', stderr)
        self.assertNotIn('secret-token', stderr)
        self.path.unlink()
        code, stdout, stderr = self.run_command(['--workbook', str(self.path)], client)
        self.assertNotEqual(code, 0)
        self.assertEqual(stdout, '')
        self.assertIn('results.xlsx', stderr)

    def test_missing_authentication_has_no_partial_report(self):
        self.write_workbook()
        with patch.dict(os.environ, {}, clear=True), patch('dotenv.load_dotenv'):
            code, stdout, stderr = self.run_command(['--workbook', str(self.path)])
        self.assertNotEqual(code, 0)
        self.assertEqual(stdout, '')
        self.assertIn('TushareToken', stderr)


class LatestPositionsFormatTest(unittest.TestCase):
    def test_exact_output_preserves_positive_position_order(self):
        state = report.LatestPositions(date(2026, 10, 22), (
            ('159650.SZ', 500), ('518880.SH', 0),
            ('512800.SH', 133400), ('159941.SZ', -100)), 38204.9, 239253.9)
        output = report.format_positions_report(state, date(2026, 10, 23))
        self.assertEqual(output,
                         'SIGNAL_DATE = dt.date(2026, 10, 22)\nTRADE_DATE = dt.date(2026, 10, 23)\n'
                         'TARGET_QUANTITIES = {\n    "159650.SZ": 500,\n    "512800.SH": 133400,\n}\n'
                         'TOTAL_VALUE = 239253.90\n现金: 38204.90\n总市值: 239253.90')
        scope = {'dt': SimpleNamespace(date=date), '__builtins__': {}}
        exec(output.split('\n现金:')[0], scope)
        self.assertEqual(scope['SIGNAL_DATE'], state.source_date)
        self.assertEqual(scope['TRADE_DATE'], date(2026, 10, 23))
        self.assertEqual(scope['TARGET_QUANTITIES'], {'159650.SZ': 500, '512800.SH': 133400})
        self.assertEqual(scope['TOTAL_VALUE'], 239253.9)

    def test_empty_dictionary_and_money_use_half_up_not_float_rounding(self):
        for positions in [(), (('159650.SZ', 0), ('518880.SH', -100))]:
            for cash, total, expected_cash, expected_total in [
                (1.005, 2.675, '1.01', '2.68'),
                (-1.005, -2.675, '-1.01', '-2.68'),
                (0, 2000., '0.00', '2000.00'),
            ]:
                with self.subTest(positions=positions, cash=cash):
                    state = report.LatestPositions(date(2026, 10, 22), positions, cash, total)
                    self.assertEqual(report.format_positions_report(state, date(2026, 10, 23)),
                                     'SIGNAL_DATE = dt.date(2026, 10, 22)\n'
                                     'TRADE_DATE = dt.date(2026, 10, 23)\nTARGET_QUANTITIES = {\n}\n'
                                     f'TOTAL_VALUE = {expected_total}\n现金: {expected_cash}\n总市值: {expected_total}')

    def test_source_date_and_next_date_have_unpadded_month_and_day(self):
        for source, next_date, expected in [
            (date(2026, 1, 8), date(2026, 1, 9),
             'SIGNAL_DATE = dt.date(2026, 1, 8)\nTRADE_DATE = dt.date(2026, 1, 9)\n'),
            (date(2026, 12, 31), date(2027, 1, 4),
             'SIGNAL_DATE = dt.date(2026, 12, 31)\nTRADE_DATE = dt.date(2027, 1, 4)\n'),
        ]:
            with self.subTest(source=source):
                state = report.LatestPositions(source, (), 0., 2000.)
                self.assertEqual(report.format_positions_report(state, next_date), expected +
                                 'TARGET_QUANTITIES = {\n}\nTOTAL_VALUE = 2000.00\n现金: 0.00\n总市值: 2000.00')


class FixedCalendar:
    def __init__(self, rows=None, error=None, noise=''):
        self.rows = rows
        self.error = error
        self.noise = noise
        self.requests = []

    def trade_cal(self, **kwargs):
        self.requests.append(kwargs)
        if self.noise:
            print(self.noise)
        if self.error:
            raise self.error
        return self.rows


class NextTradeDateTest(unittest.TestCase):
    def test_earliest_open_date_excludes_source_and_ignores_return_order(self):
        client = FixedCalendar(pd.DataFrame({
            'cal_date': ['20261026', '20261022', '20261024', '20261023'],
            'is_open': [1, 1, 0, 1],
        }))
        self.assertEqual(report.query_next_trade_date(date(2026, 10, 22), client), date(2026, 10, 23))
        self.assertEqual(client.requests, [{
            'exchange': 'SSE', 'start_date': '20261023', 'end_date': '20261122',
            'is_open': '1', 'fields': 'cal_date,is_open',
        }])

    def test_weekends_holidays_and_year_boundary_use_calendar(self):
        for source, rows, expected in [
            (date(2026, 10, 23), ['20261024', '20261025', '20261026'], date(2026, 10, 26)),
            (date(2026, 9, 30), ['20261001', '20261007', '20261008'], date(2026, 10, 8)),
            (date(2026, 12, 31), ['20270101', '20270103', '20270104'], date(2027, 1, 4)),
        ]:
            with self.subTest(source=source):
                client = FixedCalendar(pd.DataFrame({'cal_date': rows, 'is_open': ['0', '0', '1']}))
                self.assertEqual(report.query_next_trade_date(source, client), expected)

    def test_invalid_or_unavailable_calendar_fails(self):
        for rows in [None, pd.DataFrame(), pd.DataFrame({'cal_date': ['20261023']}),
                     pd.DataFrame({'cal_date': ['bad date'], 'is_open': [1]}),
                     pd.DataFrame({'cal_date': ['20261023'], 'is_open': [None]}),
                     pd.DataFrame({'cal_date': ['20261023'], 'is_open': [2]}),
                     pd.DataFrame({'cal_date': ['20261023'], 'is_open': [0]}),
                     pd.DataFrame({'cal_date': ['20261201'], 'is_open': [1]})]:
            with self.subTest(rows=rows), self.assertRaisesRegex(ValueError, '交易日历'):
                report.query_next_trade_date(date(2026, 10, 22), FixedCalendar(rows))

    def test_provider_noise_and_exception_details_are_not_exposed(self):
        client = FixedCalendar(error=RuntimeError('secret-token-in-request'), noise='secret-token-in-log')
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            with self.assertRaises(ValueError) as failure:
                report.query_next_trade_date(date(2026, 10, 22), client)
        self.assertNotIn('secret-token', str(failure.exception))
        self.assertEqual(stdout.getvalue(), '')
        self.assertEqual(stderr.getvalue(), '')


class CalendarConfigurationTest(unittest.TestCase):
    def test_existing_environment_takes_precedence_and_url_is_optional(self):
        for url in [None, 'http://calendar.invalid']:
            with self.subTest(url=url):
                environment = {'TushareToken': 'test-token'}
                if url:
                    environment['TushareIP'] = url
                client = SimpleNamespace()
                with patch.dict(os.environ, environment, clear=True), \
                        patch('dotenv.load_dotenv') as load, \
                        patch('tushare.pro_api', return_value=client) as create:
                    actual = report.create_calendar_client()
                self.assertIs(actual, client)
                create.assert_called_once_with('test-token')
                load.assert_called_once_with(Path(report.__file__).resolve().parent / '.env', override=False)
                if url:
                    self.assertEqual(client._DataApi__http_url, url)
                else:
                    self.assertFalse(hasattr(client, '_DataApi__http_url'))

    def test_initialization_errors_are_sanitized(self):
        with patch.dict(os.environ, {'TushareToken': 'secret-token'}, clear=True), \
                patch('dotenv.load_dotenv'), \
                patch('tushare.pro_api', side_effect=RuntimeError('secret-token')):
            with self.assertRaises(ValueError) as failure:
                report.create_calendar_client()
        self.assertNotIn('secret-token', str(failure.exception))

    def test_import_does_not_read_workbook_load_env_or_query_network(self):
        command = '''
from unittest.mock import patch
with patch('pandas.ExcelFile', side_effect=AssertionError('workbook read')), \\
     patch('dotenv.load_dotenv', side_effect=AssertionError('config load')), \\
     patch('tushare.pro_api', side_effect=AssertionError('network client')):
    import print_latest_positions
'''
        result = subprocess.run([sys.executable, '-c', command],
                                cwd=Path(report.__file__).resolve().parent,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr, '')
