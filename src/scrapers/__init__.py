"""Scraper registry. Add a new source by importing and registering here."""
from typing import Callable

from . import ashby, greenhouse, lever, personio
from ._base import NormalizedJob

SCRAPERS: dict[str, Callable[[str], list[NormalizedJob]]] = {
    greenhouse.SOURCE: greenhouse.fetch,
    lever.SOURCE: lever.fetch,
    ashby.SOURCE: ashby.fetch,
    personio.SOURCE: personio.fetch,
}

__all__ = ["SCRAPERS", "NormalizedJob"]