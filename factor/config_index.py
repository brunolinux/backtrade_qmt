from factor.util import *


FundsDict = {
    "000016": ("上证50", "2004-01-02", 0, 0),
    "000300": ("沪深300", "2005-04-08", 0, 0),
    "000905": ("中证500", "2007-01-15", 0, 0),
    "399006": ("创业板", "2010-06-01", 0, 0),
    "000688": ("科创50", "2020-07-23", 0, 0),
    "399001": ("深成指数", "1995-01-23", 0, 0)
}

def getIndexFundsInfo() -> pd.DataFrame:
    out = []
    for key, item in FundsDict.items():
        one = {
            "symbol": key, 
            "name": item[0],
            "start_date": item[1], 
            "is_t0": item[2], 
            "is_lof": item[3],
        }
        out.append(one)

    df_out = pd.DataFrame(out)
    df_out["start_date"] = pd.to_datetime(df_out["start_date"], format="%Y-%m-%d")
    df_out.set_index("symbol", inplace=True)
    return df_out

