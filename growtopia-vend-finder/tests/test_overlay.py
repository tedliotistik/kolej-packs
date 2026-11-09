"""Tests for the overlay (overlay/vend_core.py and a GUI smoke test)."""
import os
import sys
from pathlib import Path

import pytest

OVERLAY = Path(__file__).resolve().parent.parent / "overlay"
sys.path.insert(0, str(OVERLAY))

import vend_core as core  # noqa: E402

NOW = 1_700_000_000


def offer(world, name, price, age=0, x=0, y=0):
    return core.Offer(world, name, price, NOW - age, x, y)


def test_price_helpers():
    assert core.make_price(250, "WL / adet") == 250
    assert core.make_price(1.5, "DL / adet") == 150
    assert core.make_price(2, "BGL / adet") == 20000
    assert core.make_price(200, "adet / WL") == -200
    with pytest.raises(ValueError):
        core.make_price(0, "WL / adet")
    with pytest.raises(ValueError):
        core.make_price(1.5, "adet / WL")
    assert core.format_price(250) == "2 DL 50 WL / adet"
    assert core.format_price(12345) == "1 BGL 23 DL 45 WL / adet"
    assert core.format_price(-200) == "200 adet / WL"
    assert core.format_age(4 * 3600) == "4 sa once"


def test_tsv_roundtrip_matches_proxy_format():
    # Exactly what scripts/vend_finder.lua writes.
    text = ("# world\tscanned_at\tx\ty\titem_id\tprice\titem_name\n"
            "MAGSHOP\t1000\t10\t20\t5640\t250\tMagplant 5000\n"
            "DIRTS\t2000\t1\t2\t2\t-180\tDirt\n"
            "broken line\n"
            "EMPTY\t3000\t1\t1\t2\t0\tDirt\n")
    offers = core.parse_tsv(text)
    assert [(o.world, o.item_name, o.price, o.updated_at, o.x, o.y) for o in offers] == [
        ("MAGSHOP", "Magplant 5000", 250, 1000, 10, 20),
        ("DIRTS", "Dirt", -180, 2000, 1, 2),
    ]
    assert core.parse_tsv(core.to_tsv(offers)) == sorted(offers, key=lambda o: o.world)
    weird = core.Offer("W", "Bad\tName`", 5, 1)
    assert core.parse_tsv(core.to_tsv([weird]))[0].item_name == "Bad Name"


def test_search_sort_and_filters():
    offers = [
        offer("AAA", "Dirt", 1, age=100),
        offer("BBB", "Dirt", -200, age=5000),
        offer("CCC", "Dirt", -200, age=10),
        offer("DDD", "Dirt Seed", -500, age=10),
        offer("EEE", "Magplant 5000", 250, age=10 * 86400),
    ]
    names = lambda res: [o.world for o in res]

    # exact match wins, cheapest first, ties -> newest first
    assert names(core.search(offers, " dirt ", now=NOW)) == ["CCC", "BBB", "AAA"]
    assert names(core.search(offers, "dirt", "Pahalidan ucuza", now=NOW)) == ["AAA", "CCC", "BBB"]
    assert names(core.search(offers, "dirt", "En yeni once", now=NOW)) == ["CCC", "AAA", "BBB"]
    assert names(core.search(offers, "dirt", "En eski once", now=NOW)) == ["BBB", "AAA", "CCC"]
    # partial match
    assert names(core.search(offers, "seed", now=NOW)) == ["DDD"]
    # age filter
    assert names(core.search(offers, "dirt", max_age=3600, now=NOW)) == ["CCC", "AAA"]
    # empty query lists everything (respecting filters)
    assert len(core.search(offers, "", max_age=86400, now=NOW)) == 4
    # world + price filter
    assert names(core.search(offers, "", world="cc", now=NOW)) == ["CCC"]
    assert names(core.search(offers, "", max_wl=0.5, now=NOW)) == ["DDD", "CCC", "BBB"]


def test_store_upsert_remove_touch_and_external_reload(tmp_path):
    path = tmp_path / "data" / "vend_finder.tsv"
    store = core.VendStore(str(path))
    assert store.offers == []

    store.upsert(core.Offer("SHOP", "Dirt", 5, 100))
    store.upsert(core.Offer("SHOP", "dirt", 3, 200))          # same world+item, no coords -> replaced
    store.upsert(core.Offer("SHOP", "Magplant", 300, 200, 4, 5))
    store.upsert(core.Offer("SHOP", "Magplant 5000", 280, 300, 4, 5))  # same tile -> replaced
    assert sorted((o.item_name, o.price) for o in store.offers) == [("Magplant 5000", 280), ("dirt", 3)]

    again = core.VendStore(str(path))
    assert set(again.offers) == set(store.offers)

    store.touch([o for o in store.offers if o.price == 3], now=999)
    assert {o.price: o.updated_at for o in core.VendStore(str(path)).offers}[3] == 999

    # The proxy script rewrites the file -> store picks it up.
    path.write_text("OTHER\t50\t1\t1\t2\t-100\tDirt\n", encoding="utf-8")
    os.utime(path, ns=(10**18, 10**18))
    assert store.reload_if_changed() is True
    assert [o.world for o in store.offers] == ["OTHER"]

    assert store.remove_world("other") == 1
    assert store.offers == []


def test_parse_hotkey():
    import vend_overlay as ov
    assert ov.parse_hotkey("F8") == (0, 0x77)
    assert ov.parse_hotkey("ctrl+shift+v") == (0x2 | 0x4, ord("V"))
    with pytest.raises(ValueError):
        ov.parse_hotkey("CTRL")
    with pytest.raises(ValueError):
        ov.parse_hotkey("F8+BLAH")


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="needs a display (xvfb-run)")
def test_gui_smoke(tmp_path):
    import time
    NOW = int(time.time())
    import tkinter as tk
    import vend_overlay as ov

    data = tmp_path / "vend_finder.tsv"
    data.write_text(core.to_tsv([
        core.Offer("MAGSHOP", "Magplant 5000", 250, NOW, 10, 20),
        core.Offer("CHEAPMAG", "Magplant 5000", 240, NOW - 3 * 86400),
        core.Offer("DIRTS", "Dirt", -180, NOW),
    ]), encoding="utf-8")
    cfg = dict(ov.DEFAULT_CONFIG, data_file=str(data))

    root = tk.Tk()
    app = ov.OverlayApp(root, cfg)
    try:
        app.search_var.set("magplant")
        rows = [app.tree.item(i, "values") for i in app.tree.get_children()]
        assert [r[2] for r in rows] == ["CHEAPMAG", "MAGSHOP"]
        assert rows[1][0] == "2 DL 50 WL / adet" and rows[1][3] == "10, 20"

        app.age_var.set("Son 24 saat")
        assert [app.tree.item(i, "values")[2] for i in app.tree.get_children()] == ["MAGSHOP"]

        app.age_var.set("Tum zamanlar")
        app.sort_var.set("Pahalidan ucuza")
        assert [app.tree.item(i, "values")[2] for i in app.tree.get_children()] == ["MAGSHOP", "CHEAPMAG"]

        # Add through the dialog.
        dlg = ov.OfferDialog(app)
        dlg.item.set("World Lock")
        dlg.world.set("wlshop")
        dlg.amount.set("1")
        dlg.unit.set("WL / adet")
        dlg.on_save()
        assert any(o.world == "WLSHOP" and o.price == 1 for o in core.VendStore(str(data)).offers)

        app.search_var.set("world lock")
        assert [app.tree.item(i, "values")[2] for i in app.tree.get_children()] == ["WLSHOP"]
        root.update()
    finally:
        app.close()
