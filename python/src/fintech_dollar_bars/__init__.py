"""Fintech Dollar Bars — notional-clock bar construction.

A small, well-specified, cross-language reference implementation of Dollar Bars:
aggregating a finalized trade tape into bars that each accumulate at least
``targetDollar`` of traded notional (price x volume), using exact fixed-point
arithmetic so membership decisions match across languages.

Companion article (canonical): https://thefintechbuilder.com/market-data-engineering/bar-construction/dollar-bars/
Catalog topic id: D01-F01-A04  (Domain D01 — Market Data Engineering / Family D01-F01 — Bar Construction)
"""

from __future__ import annotations

from .core import DollarBarsValidationError, construct_bars
from .streaming import StreamingDollarBarBuilder
from .yahoo import load_trades

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "DollarBarsValidationError",
    "construct_bars",
    "StreamingDollarBarBuilder",
    "load_trades",
]
