"""Data model for the Vend Finder overlay (no GUI code, unit-testable).

The data file is the same TSV the proxy script writes (data/vend_finder.tsv):

    world <TAB> updated_at <TAB> x <TAB> y <TAB> item_id <TAB> price <TAB> item_name

`price` uses Growtopia's vending convention: > 0 means "price World Locks per
item", < 0 means "-price items per World Lock". `updated_at` is Unix seconds.
"""
from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass, replace
from typing import Iterable

HEADER = "# world\tscanned_at\tx\ty\titem_id\tprice\titem_name"

WL_PER_DL = 100
WL_PER_BGL = 10000

# Units offered in the "add" form: label -> function(amount) -> signed price
UNITS = {
    "WL / adet": lambda n: n,
    "DL / adet": lambda n: n * WL_PER_DL,
    "BGL / adet": lambda n: n * WL_PER_BGL,
    "adet / WL": lambda n: -n,
}

SORTS = ("Ucuzdan pahaliya", "Pahalidan ucuza", "En yeni once", "En eski once")

# label -> max age in seconds (None = no limit)
AGE_FILTERS = {
    "Tum zamanlar": None,
    "Son 1 saat": 3600,
    "Son 24 saat": 86400,
    "Son 3 gun": 3 * 86400,
    "Son 7 gun": 7 * 86400,
    "Son 30 gun": 30 * 86400,
}


@dataclass(frozen=True)
class Offer:
    world: str
    item_name: str
    price: int
    updated_at: int
    x: int = 0
    y: int = 0
    item_id: int = 0

    @property
    def key(self) -> tuple:
        """Identity of a vending machine: same world, same tile."""
        if self.x or self.y:
            return (self.world, self.x, self.y)
        # Manually added offers without coordinates: one per world + item.
        return (self.world, "item", self.item_name.lower())

    @property
    def wl_per_item(self) -> float:
        if self.price > 0:
            return float(self.price)
        if self.price < 0:
            return 1.0 / -self.price
        return float("inf")


def clean_text(value) -> str:
    return "".join(" " if c in "\t\r\n`" else c for c in str(value)).strip()


def normalize_world(name: str) -> str:
    return clean_text(name).upper()


def make_price(amount: float, unit: str) -> int:
    if unit not in UNITS:
        raise ValueError(f"Bilinmeyen birim: {unit}")
    if amount <= 0:
        raise ValueError("Fiyat 0'dan buyuk olmali")
    price = UNITS[unit](amount)
    if price != int(price):
        raise ValueError("Fiyat tam sayi WL olmali (or. 1.5 DL = 150 WL olur, 1.555 DL olmaz)")
    return int(price)


def format_locks(wl: int) -> str:
    bgl, rest = divmod(wl, WL_PER_BGL)
    dl, wl_rest = divmod(rest, WL_PER_DL)
    parts = []
    if bgl:
        parts.append(f"{bgl} BGL")
    if dl:
        parts.append(f"{dl} DL")
    if wl_rest or not parts:
        parts.append(f"{wl_rest} WL")
    return " ".join(parts)


def format_price(price: int) -> str:
    if price < 0:
        return f"{-price} adet / WL"
    return f"{format_locks(price)} / adet"


def format_age(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return "az once"
    if seconds < 3600:
        return f"{seconds // 60} dk once"
    if seconds < 86400:
        return f"{seconds // 3600} sa once"
    return f"{seconds // 86400} gun once"


def format_date(ts: int) -> str:
    return time.strftime("%d.%m.%Y %H:%M", time.localtime(ts))


def parse_tsv(text: str) -> list[Offer]:
    offers = []
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        f = line.split("\t")
        if len(f) < 6:
            continue
        try:
            world = normalize_world(f[0])
            updated_at, x, y, item_id, price = (int(float(v)) for v in f[1:6])
        except ValueError:
            continue
        name = clean_text(f[6]) if len(f) > 6 else ""
        if not world or price == 0:
            continue
        offers.append(Offer(world, name or f"Item #{item_id}", price, updated_at, x, y, item_id))
    return offers


def to_tsv(offers: Iterable[Offer]) -> str:
    rows = sorted(offers, key=lambda o: (o.world, o.y, o.x, o.item_name.lower()))
    lines = [HEADER]
    for o in rows:
        lines.append("\t".join(str(v) for v in (
            o.world, o.updated_at, o.x, o.y, o.item_id, o.price, clean_text(o.item_name))))
    return "\n".join(lines) + "\n"


class VendStore:
    """Offers kept in memory and saved to a TSV file. Reloads if the file changes."""

    def __init__(self, path: str):
        self.path = path
        self.offers: list[Offer] = []
        self._mtime = None
        self.reload_if_changed(force=True)

    def _file_mtime(self):
        try:
            return os.stat(self.path).st_mtime_ns
        except OSError:
            return None

    def reload_if_changed(self, force: bool = False) -> bool:
        mtime = self._file_mtime()
        if not force and mtime == self._mtime:
            return False
        self._mtime = mtime
        if mtime is None:
            self.offers = []
            return True
        with open(self.path, encoding="utf-8", errors="replace") as fh:
            self.offers = parse_tsv(fh.read())
        return True

    def save(self) -> None:
        folder = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".vend_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(to_tsv(self.offers))
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
        self._mtime = self._file_mtime()

    def upsert(self, offer: Offer) -> None:
        """Add an offer, replacing the previous one for the same machine."""
        self.reload_if_changed()
        self.offers = [o for o in self.offers if o.key != offer.key] + [offer]
        self.save()

    def remove(self, offers: Iterable[Offer]) -> None:
        self.reload_if_changed()
        gone = set(offers)
        self.offers = [o for o in self.offers if o not in gone]
        self.save()

    def remove_world(self, world: str) -> int:
        self.reload_if_changed()
        world = normalize_world(world)
        before = len(self.offers)
        self.offers = [o for o in self.offers if o.world != world]
        self.save()
        return before - len(self.offers)

    def touch(self, offers: Iterable[Offer], now: int | None = None) -> None:
        """Mark offers as re-checked now (price still the same)."""
        now = int(time.time()) if now is None else now
        self.reload_if_changed()
        targets = set(offers)
        self.offers = [replace(o, updated_at=now) if o in targets else o for o in self.offers]
        self.save()

    def item_names(self) -> list[str]:
        return sorted({o.item_name for o in self.offers}, key=str.lower)


def search(
    offers: Iterable[Offer],
    query: str = "",
    sort: str = SORTS[0],
    max_age: int | None = None,
    world: str = "",
    min_wl: float | None = None,
    max_wl: float | None = None,
    now: int | None = None,
) -> list[Offer]:
    """Filter and sort offers.

    If any item name equals the query exactly (ignoring case) only those are
    returned, otherwise every item whose name contains the query.
    """
    now = int(time.time()) if now is None else now
    q = " ".join(query.lower().split())
    w = world.strip().upper()

    pool = []
    for o in offers:
        if max_age is not None and now - o.updated_at > max_age:
            continue
        if w and w not in o.world:
            continue
        if min_wl is not None and o.wl_per_item < min_wl:
            continue
        if max_wl is not None and o.wl_per_item > max_wl:
            continue
        pool.append(o)

    if q:
        exact = [o for o in pool if o.item_name.lower() == q]
        pool = exact or [o for o in pool if q in o.item_name.lower()]

    if sort == "Pahalidan ucuza":
        key = lambda o: (-o.wl_per_item, -o.updated_at, o.world)
    elif sort == "En yeni once":
        key = lambda o: (-o.updated_at, o.wl_per_item, o.world)
    elif sort == "En eski once":
        key = lambda o: (o.updated_at, o.wl_per_item, o.world)
    else:
        key = lambda o: (o.wl_per_item, -o.updated_at, o.world)
    return sorted(pool, key=key)
