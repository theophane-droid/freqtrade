"""Bingx exchange subclass"""

import logging

import ccxt
from freqtrade.exchange import Exchange
from freqtrade.exchange.exchange_types import FtHas
from freqtrade.enums import CandleType, MarginMode, PriceType, TradingMode
from freqtrade.exchange.common import retrier
from freqtrade.exceptions import TemporaryError, OperationalException
from math import floor

from datetime import datetime

logger = logging.getLogger(__name__)


class Bingx(Exchange):
    """
    Bingx exchange class. Contains adjustments needed for Freqtrade to work
    with this exchange.
    """
    _supported_trading_mode_margin_pairs: list[tuple[TradingMode, MarginMode]] = [
        (TradingMode.FUTURES, MarginMode.CROSS),
        (TradingMode.FUTURES, MarginMode.ISOLATED),
    ]

    _ft_has: FtHas = {
        "ohlcv_candle_limit": 1000,
        "stoploss_on_exchange": True,
        "stoploss_order_types": {"limit": "limit", "market": "market"},
        "order_time_in_force": ["GTC", "IOC", "PO"],
        "trades_has_history": False,  # Endpoint doesn't seem to support pagination
        "l2_limit_range": [5, 10, 20, 50, 100, 500, 1000],
        "l2_limit_range_required": True,
        "exchange_has_overrides": {
            "fetchFundingHistory": True
        },
    }

    def _lev_prep(self, pair: str, leverage: float, side: str, accept_fail: bool = False):
        self.set_margin_mode(pair, self.margin_mode, accept_fail)
        side_param = "LONG" if side.lower() == "buy" else "SHORT"
        self._set_leverage(leverage, pair, side_param, accept_fail)

    def _set_leverage(self, leverage: float, pair: str | None = None, side: str = "", accept_fail: bool = False):
        if self._config["dry_run"] or not self.exchange_has("setLeverage"):
            return
        if self._ft_has.get("floor_leverage", False):
            leverage = floor(leverage)
        try:
            res = self._api.setLeverage(symbol=pair, leverage=leverage, params={'side': 'BOTH'})
            self._log_exchange_response("set_leverage", res)
        except ccxt.DDoSProtection as e:
            raise OperationalException(e) from e
        except (ccxt.BadRequest, ccxt.OperationRejected, ccxt.InsufficientFunds) as e:
            if not accept_fail:
                raise TemporaryError(
                    f"Could not set leverage due to {e.__class__.__name__}. Message: {e}"
                ) from e
        except (ccxt.OperationFailed, ccxt.ExchangeError) as e:
            raise TemporaryError(
                f"Could not set leverage due to {e.__class__.__name__}. Message: {e}"
            ) from e
        except ccxt.BaseError as e:
            raise OperationalException(e) from e
    
    @retrier
    def additional_exchange_init(self) -> None:
        """
        Additional exchange initialization logic.
        .api will be available at this point.
        Must be overridden in child methods if required.
        """
        try:
            if not self._config["dry_run"]:
                open_orders = self._api.fetch_open_orders()
                positions = self._api.fetch_positions()
                print(positions)
                if not positions and not open_orders and self.trading_mode == TradingMode.FUTURES:
                    self._api.set_position_mode(False)  # Ou une autre action nécessaire
                    self._log_exchange_response("set_position_mode", {"status": "skipped"})

        except ccxt.DDoSProtection as e:
            raise DDosProtection(e) from e
        except (ccxt.OperationFailed, ccxt.ExchangeError) as e:
            raise TemporaryError(f"Error in additional_exchange_init due to {e.__class__.__name__}. Message: {e}") from e
        except ccxt.BaseError as e:
            raise OperationalException(e) from e

    def get_funding_fees(self, pair: str, amount: float, is_short: bool, open_date: datetime) -> float:
        """
        Fetch funding fees, either from the exchange (live) or calculates them
        based on funding rate/mark price history
        :param pair: The quote/base pair of the trade
        :param is_short: trade direction
        :param amount: Trade amount
        :param open_date: Open date of the trade
        :return: funding fee since open_date
        :raises: ExchangeError if something goes wrong.
        """
        # BingX does not support funding history retrieval
        if self.trading_mode == TradingMode.FUTURES:
            return 0.05 # from the bingX doc for maker (TODO : update)
