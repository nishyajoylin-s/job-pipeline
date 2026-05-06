"""Scraper registry. Add a new source by importing and registering here."""
from typing import Callable

from . import ashby, greenhouse, lever, personio, workable, smartrecruiters
from ._base import NormalizedJob

SCRAPERS: dict[str, Callable[[str], list[NormalizedJob]]] = {
    greenhouse.SOURCE: greenhouse.fetch,
    lever.SOURCE: lever.fetch,
    ashby.SOURCE: ashby.fetch,
    personio.SOURCE: personio.fetch,
    workable.SOURCE: workable.fetch,
    smartrecruiters.SOURCE: smartrecruiters.fetch,
}

__all__ = ["SCRAPERS", "NormalizedJob"]