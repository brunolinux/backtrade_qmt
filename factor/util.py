import os.path as osp
import pandas as pd
import enum

class CodeType(enum.Enum):
    Stock = 0
    ETF   = 1
    Index = 2

def getCodeFileName(symbol, code_type: CodeType):
    path = osp.dirname(osp.abspath(__file__))
    subdir = code_type.name
    return osp.join(path, "..", "data", "input", subdir, "{}.csv".format(symbol))


def readOHLCFile(symbol, code_type: CodeType):
    file_name = getCodeFileName(symbol, code_type)
    if osp.exists(file_name):
        df = pd.read_csv(file_name, index_col=0)
        df = df.convert_dtypes(dtype_backend="numpy_nullable")
        df.index = pd.to_datetime(df.index)
        return df 
    else:
        return pd.DataFrame()


def getFundsDataDict(funds: pd.DataFrame, code_type: CodeType):
    out_dict = {}
    for symbol in funds.index:
        df = readOHLCFile(symbol, code_type)
        out_dict[symbol] = df
    return out_dict
