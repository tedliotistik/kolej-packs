"""Tests for overlay/discord_source.py with a fake Discord gateway and REST API."""
import json
import queue
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "overlay"))

import discord_source as ds  # noqa: E402

NOW = 1_762_700_000

# Modelled on the bot's embed in the user's screenshot.
PAGE1 = (
    "Page **1** / **2** · **4** listings · Sort: **date**\n"
    "Filter: **all worlds** *(access icons shown per listing)*\n\n"
    "> **40** <:dl:111> **59** <:wl:222> each · \U0001F30E **MARTGENZ** · \U0001F4CD `(69, 52)` · "
    "⏰ <t:1762685000:R> · ✅\n"
    "> **20** <:dl:111> each · \U0001F30E **BN02** · \U0001F4CD `(5, 51)` · ⏰ <t:1762686000:R> · ✅\n"
    "> **1** <:bgl:333> each · \U0001F30E **SETS** · \U0001F4CD `(31, 36)` · ⏰ <t:1762600000:R> · ❌\n"
)
PAGE2 = (
    "Page **2** / **2** · **4** listings · Sort: **date**\n\n"
    "> **5** / <:wl:222> · \U0001F30E **CHEAPS** · \U0001F4CD `(1, 2)` · ⏰ <t:1762690000:R> · ✅\n"
)


def test_lock_units():
    assert ds.lock_unit("wl") == 1
    assert ds.lock_unit("WorldLock") == 1
    assert ds.lock_unit("gt_wl") == 1
    assert ds.lock_unit("dl") == 100
    assert ds.lock_unit("diamond_lock") == 100
    assert ds.lock_unit("bgl") == 10000
    assert ds.lock_unit("blue_gem_lock") == 10000
    assert ds.lock_unit("globe") is None


def test_price_from_text():
    assert ds.price_from_text("**40** <:dl:1> **59** <:wl:2> each") == 4059
    assert ds.price_from_text("**75** <:dl:1> each") == 7500
    assert ds.price_from_text("**1** <:bgl:1> each") == 10000
    assert ds.price_from_text("**5** / <:wl:2> · ") == -5           # 5 items per WL
    assert ds.price_from_text("**200** per <:wl:2>") == -200
    assert ds.price_from_text("**2** per <:dl:2>") == 50             # 50 WL each
    assert ds.price_from_text("no price here") is None


def test_parse_embed_from_screenshot():
    listings = ds.parse_embed({"title": "**Bodvar**", "description": PAGE1}, "bodvar", now=NOW)
    assert [(l.item_name, l.world, l.price, l.x, l.y, l.updated_at, l.accessible) for l in listings] == [
        ("Bodvar", "MARTGENZ", 4059, 69, 52, 1762685000, True),
        ("Bodvar", "BN02", 2000, 5, 51, 1762686000, True),
        ("Bodvar", "SETS", 10000, 31, 36, 1762600000, False),
    ]
    assert ds.page_info({"embeds": [{"description": PAGE1}]}) == (1, 2)
    # Listings in fields are read too.
    fields = ds.parse_embed({"title": "X", "fields": [{"name": "1.", "value": PAGE2.splitlines()[2]}]}, "x", now=NOW)
    assert [(l.world, l.price) for l in fields] == [("CHEAPS", -5)]


def test_find_next_button_and_channel_link():
    msg = {"components": [{"type": 1, "components": [
        {"type": 2, "custom_id": "prev", "label": "Prev", "disabled": True},
        {"type": 2, "custom_id": "p_next", "emoji": {"name": "▶"}},
    ]}]}
    assert ds.find_next_button(msg)["custom_id"] == "p_next"
    assert ds.parse_channel_link("https://discord.com/channels/123/456") == ("123", "456")
    with pytest.raises(ds.DiscordError):
        ds.parse_channel_link("nope")


class FakeDiscord:
    """Fake gateway + REST that behaves like the bot in the screenshot."""

    APP = "900"

    def __init__(self):
        self.inbox = queue.Queue()
        self.sent = []
        self.posts = []
        self.seq = 0

    # websocket-like
    def ws_factory(self, url):
        self.inbox.put({"op": 10, "d": {"heartbeat_interval": 41250}})
        return self

    def recv(self):
        return json.dumps(self.inbox.get(timeout=5))

    def send(self, raw):
        msg = json.loads(raw)
        self.sent.append(msg)
        if msg["op"] == 2:
            self.dispatch("READY", {"session_id": "sess1", "user": {"id": "1"}})

    def close(self):
        self.inbox.put(None)

    def dispatch(self, t, d):
        self.seq += 1
        self.inbox.put({"op": 0, "t": t, "s": self.seq, "d": d})

    # REST
    def http(self, method, url, token, body=None):
        assert token == "TOKEN"
        if url.endswith("/guilds/10/application-command-index"):
            return 200, {
                "applications": [{"id": self.APP, "name": "Vend Finder"}, {"id": "800", "name": "Other Bot"}],
                "application_commands": [
                    {"id": "c0", "application_id": "800", "version": "1", "name": "vend", "type": 1,
                     "options": [{"type": 3, "name": "q", "required": True}]},
                    {"id": "c1", "application_id": self.APP, "version": "7", "name": "help", "type": 1},
                    {"id": "c2", "application_id": self.APP, "version": "7", "name": "vend", "type": 1,
                     "options": [{"type": 3, "name": "item", "required": True},
                                 {"type": 3, "name": "world"}]},
                ],
            }
        if url.endswith("/interactions"):
            self.posts.append(body)
            assert body["session_id"] == "sess1"
            threading.Thread(target=self._respond, args=(body,), daemon=True).start()
            return 204, None
        return 404, {"message": "unknown"}

    def _respond(self, body):
        if body["type"] == 2:
            self.dispatch("INTERACTION_CREATE", {"id": "i1", "nonce": body["nonce"]})
            base = {"id": "m1", "channel_id": "20", "interaction_metadata": {"id": "i1"}}
            self.dispatch("MESSAGE_CREATE", dict(base, flags=128, embeds=[]))  # "thinking..."
            self.dispatch("MESSAGE_UPDATE", dict(base, flags=0, embeds=[{"title": "Bodvar", "description": PAGE1}],
                                                 components=[{"type": 1, "components": [
                                                     {"type": 2, "custom_id": "next:2", "label": "Next"}]}]))
        else:
            assert body["message_id"] == "m1" and body["data"]["custom_id"] == "next:2"
            self.dispatch("INTERACTION_SUCCESS", {"id": "i2", "nonce": body["nonce"]})
            self.dispatch("MESSAGE_UPDATE", {"id": "m1", "channel_id": "20", "flags": 0,
                                             "embeds": [{"title": "Bodvar", "description": PAGE2}],
                                             "components": []})


def make_client(fake, tmp_path, **kw):
    return ds.DiscordVendClient(
        token="TOKEN", channel_link="https://discord.com/channels/10/20",
        dump_dir=str(tmp_path), http=fake.http, ws_factory=fake.ws_factory, reply_timeout=5, **kw)


def test_full_search_with_paging(tmp_path):
    fake = FakeDiscord()
    client = make_client(fake, tmp_path)
    try:
        listings = client.search("bodvar")
    finally:
        client.close()

    identify = next(m for m in fake.sent if m["op"] == 2)
    assert identify["d"]["properties"]["browser"] == "VendFinderOverlay"  # honest client name

    cmd = fake.posts[0]
    assert cmd["type"] == 2 and cmd["application_id"] == "900" and cmd["guild_id"] == "10"
    assert cmd["data"]["name"] == "vend" and cmd["data"]["version"] == "7"
    assert cmd["data"]["options"] == [{"type": 3, "name": "item", "value": "bodvar"}]
    assert fake.posts[1]["type"] == 3
    assert len(fake.posts) == 2  # stopped after the last page

    assert [(l.world, l.price) for l in listings] == [
        ("MARTGENZ", 4059), ("BN02", 2000), ("SETS", 10000), ("CHEAPS", -5)]
    dump = json.loads((tmp_path / "discord_last_reply.json").read_text(encoding="utf-8"))
    assert dump["query"] == "bodvar" and len(dump["pages"]) == 2
    assert (tmp_path / "discord_commands.json").exists()


def test_max_pages_one_and_missing_command(tmp_path):
    fake = FakeDiscord()
    client = make_client(fake, tmp_path, max_pages=1)
    try:
        assert len(client.search("bodvar")) == 3
        assert len(fake.posts) == 1
    finally:
        client.close()

    fake2 = FakeDiscord()
    client2 = make_client(fake2, tmp_path, bot_name="Nope Bot")
    try:
        with pytest.raises(ds.DiscordError, match="arama komutu bulunamadi"):
            client2.search("x")
    finally:
        client2.close()


def test_searcher_cooldown_cache_and_errors(tmp_path):
    results = queue.Queue()

    class StubClient:
        calls = 0

        def search(self, q):
            StubClient.calls += 1
            if q == "boom":
                raise ds.DiscordError("bad")
            return [ds.Listing("Dirt", "W", 1, NOW)]

        def close(self):
            pass

    s = ds.DiscordSearcher(StubClient(), lambda q, r, e: results.put((q, r, e)), cooldown=0, cache_seconds=60)
    assert s.submit("  ") == "Aramak icin esya adi yazin."
    assert s.submit("dirt") is None
    q, r, e = results.get(timeout=2)
    assert q == "dirt" and e is None and r[0].world == "W"
    while s.busy:
        pass
    assert s.submit("DIRT") is None          # cached: no new call
    results.get(timeout=2)
    assert StubClient.calls == 1
    assert s.submit("boom") is None
    q, r, e = results.get(timeout=2)
    assert r is None and e == "bad"

    slow = ds.DiscordSearcher(StubClient(), lambda *a: None, cooldown=60)
    slow._last = __import__("time").monotonic()
    assert "Cok hizli" in slow.submit("x")
