from langchain_core.tools import tool
from typing import Annotated
from tradingagents.dataflows.interface import route_to_vendor


@tool
def get_stock_data(
    symbol: Annotated[str, "ticker symbol of the company"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """
    Retrieve local market data (OHLCV/futures rows) for a given instrument.
    Uses the configured core_stock_apis vendor; in Alan's local fork this defaults
    to alan_db, backed by metals_data.db, shfe_options.db, and tushare.db.
    Args:
        symbol (str): Instrument symbol, e.g. CU, AU, AG, AL, ZN, NI, copper, gold
        start_date (str): Start date in yyyy-mm-dd format
        end_date (str): End date in yyyy-mm-dd format
    Returns:
        str: A formatted dataframe containing local market data for the instrument.
    """
    return route_to_vendor("get_stock_data", symbol, start_date, end_date)
