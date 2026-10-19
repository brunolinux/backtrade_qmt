import datetime
import time
import pandas as pd
import os
import dotenv
import tushare
from tushare.pro.client import DataApi

from factor.config_etf import getETFFundsInfo
from factor.config_stock import getStockFundsInfo
from factor.config_index import getIndexFundsInfo
from factor.util import CodeType, getCodeFileName, readOHLCFile

DEFAULT_SLEEP_SECONDS = 2


def _get_raw_data(pro, code, start_date, end_date, code_type: CodeType):
    """获取原始量价数据
    """
    if code_type == CodeType.ETF:
        df = pro.fund_daily(ts_code=code, start_date=start_date, end_date=end_date, 
                            fields="trade_date,open,high,low,close,vol,amount")
    elif code_type == CodeType.Stock:
        df = pro.daily(ts_code=code, start_date=start_date, end_date=end_date)
        if len(df) != 0:
            df = df[["trade_date", "open", "high", "low", "close", "vol", "amount"]]
    elif code_type == CodeType.Index:
        df = pro.index_daily(ts_code=code, start_date=start_date, end_date=end_date)
        if len(df) != 0:
            df = df[["trade_date", "open", "high", "low", "close", "vol", "amount"]]
    return df


def _get_adjfactor(pro, code, start_date, end_date, code_type: CodeType):
    """获取复权因子
    """
    if code_type == CodeType.ETF:
        df = pro.fund_adj(ts_code=code, start_date=start_date, end_date=end_date)
    elif code_type == CodeType.Stock:
        df = pro.adj_factor(ts_code=code, start_date=start_date, end_date=end_date)
    elif code_type == CodeType.Index:
        df = 1
    return df


def _process_raw_data(df_ohlc, df_adj_factor):
    """计算复权后数据
    """
    df_ohlc.loc[:, "date"] = pd.to_datetime(df_ohlc["trade_date"], format="%Y%m%d")
    df_ohlc = df_ohlc.set_index("date")
    df_ohlc.drop(columns=["trade_date"], inplace=True)

    # 两种情况, 指数不包含复权因子
    if isinstance(df_adj_factor, pd.DataFrame):
        df_adj_factor = df_adj_factor[["trade_date", "adj_factor"]]
        df_adj_factor.loc[:, "date"] = pd.to_datetime(df_adj_factor["trade_date"], format="%Y%m%d")
        df_adj_factor = df_adj_factor.set_index("date")
        df_adj_factor.drop(columns=["trade_date"], inplace=True)

        df = df_ohlc.join(df_adj_factor)
    else:
        df = df_ohlc.copy()
        df["adj_factor"] = 1.0

    df = df.dropna()
    
    df.loc[:, "raw_close"] = df["close"]

    df.loc[:, "open"] = df["open"] * df["adj_factor"]
    df.loc[:, "high"] = df["high"] * df["adj_factor"]
    df.loc[:, "low"] = df["low"] * df["adj_factor"]
    df.loc[:, "close"] = df["close"] * df["adj_factor"]
    return df


def _get_ts_prefix(code, code_type: CodeType):
    if code_type == CodeType.ETF:
        if code[0] == "1":
            prefix = "SZ"
        elif code[0] == "5":
            prefix = "SH"
        else:
            raise ValueError("ETF code is not supported")
    elif code_type == CodeType.Stock:
        sh_list = set(["600", "601", "603", "605", "688"])
        sz_list = set(["000", "001", "002", "003", "004", "300", "301"])

        head = code[:3]
        if head in sh_list:
            prefix = "SH"
        elif head in sz_list:
            prefix = "SZ"
        else:
            raise ValueError("Stock code is not supported")
    elif code_type == CodeType.Index:
        if code[0] == "3":
            prefix = "SZ"
        elif code[0] == "0":
            prefix = "SH"
        else:
            raise ValueError("Index code is not supported")
    return prefix


def get_tushare_data(pro, code: str, start_date: datetime.datetime, 
                    end_date: datetime.datetime, code_type: CodeType):

    prefix = _get_ts_prefix(code, code_type)
    ts_code = "{}.{}".format(code, prefix)

    total_days = (end_date - start_date).days

    # 该参数来自 tushare API 说明
    num_per_query = 2000
    
    queries = total_days // num_per_query + 1
    df_list = []

    cur_start_date = start_date
    for _ in range(queries):
        if cur_start_date >= end_date:
            break

        start_str = cur_start_date.strftime("%Y%m%d")
        cur_end_date = cur_start_date + datetime.timedelta(days=num_per_query-1)
        if cur_end_date > end_date:
            cur_end_date = end_date
        end_str = cur_end_date.strftime("%Y%m%d")

        df1 = _get_raw_data(pro, ts_code, start_str, end_str, code_type)
        time.sleep(DEFAULT_SLEEP_SECONDS)
        df2 = _get_adjfactor(pro, ts_code, start_str, end_str, code_type)
        time.sleep(DEFAULT_SLEEP_SECONDS)

        cur_start_date = cur_end_date

        if len(df1) == 0:
            continue

        df = _process_raw_data(df1, df2)
        df_list.append(df)
        
    if len(df_list) == 0:
        return pd.DataFrame()
    
    # 按列拼接
    df = pd.concat(df_list, axis=0)

    # 日期升序排列
    df = df.sort_index(ascending=True)

    # 排除重复日期
    df = df[~df.index.duplicated(keep="last")]
    return df


if __name__ == "__main__":
    # 加载环境变量
    dotenv.load_dotenv(verbose=True)

    # 创建 tushare 对象
    DataApi._DataApi__http_url = os.getenv("TushareIP")
    pro = tushare.pro_api(os.getenv("TushareToken"))

    # 当前时间
    end_date = datetime.datetime.now()

    etf_dict = getETFFundsInfo()
    stock_dict = getStockFundsInfo()
    index_dict = getIndexFundsInfo()

    # 同时下载 ETF & 股票
    funds_list = [
        (etf_dict, CodeType.ETF),
        # (stock_dict, CodeType.Stock),
        # (index_dict, CodeType.Index)
    ]

    for funds in funds_list:
        code_type = funds[1]
  
        for sym, info in funds[0].iterrows():
            file_name = getCodeFileName(sym, code_type)

            if not os.path.exists(file_name):
                old_df = None
                start_date = info["start_date"].to_pydatetime()
            else:
                old_df = readOHLCFile(sym, code_type)
                start_date = old_df.index[-1] + datetime.timedelta(days=1)

            if (start_date < end_date - datetime.timedelta(days=1)) or \
                (start_date < end_date and end_date.hour > 18):
                df = get_tushare_data(pro, sym, start_date, end_date, code_type)
                if old_df is not None:
                    df = pd.concat([old_df, df], axis=0)

                df = df.drop_duplicates()
                df.to_csv(file_name)

            print("{} {} over!!!!".format(code_type.name, sym))


