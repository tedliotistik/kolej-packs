"""Ask the Discord "Vend Finder" bot for prices with your own Discord account.

WARNING: automating a user account ("selfbot") is against Discord's Terms of
Service and the account can be banned. Your token gives full access to your
account: keep it only in config.json on your own PC and never share it.

How it works: for every search it sends the bot's slash command once (exactly
like typing it), waits for the bot's reply and parses the listings from the
embed. One command per search, with a cooldown and a short cache, so it never
bulk-downloads the bot's database.

The client identifies itself honestly (it does not pretend to be the official
Discord app). If Discord rejects that, this module reports the error.
"""
from __future__ import annotations

import json
import os
import random
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

API_BASE = "https://discord.com/api/v9"
GATEWAY_URL = "wss://gateway.discord.gg/?v=9&encoding=json"
USER_AGENT = "VendFinderOverlay/1.0"
DISCORD_EPOCH_MS = 1420070400000

# Message flag set while a bot is still "thinking" about a deferred reply.
FLAG_LOADING = 1 << 7

WL_PER_DL = 100
WL_PER_BGL = 10000


class DiscordError(Exception):
    pass


# ---------------------------------------------------------------------------
# Parsing the bot's embed
# ---------------------------------------------------------------------------

@dataclass
class Listing:
    item_name: str
    world: str
    price: int            # same convention as vend_core: >0 WL each, <0 items per WL
    updated_at: int
    x: int = 0
    y: int = 0
    accessible: bool | None = None


CUSTOM_EMOJI = re.compile(r"<a?:(\w+):\d+>")
NUMBER = r"(\d[\d,.]*)"
AMOUNT_EMOJI = re.compile(NUMBER + r"\**\s*<a?:(\w+):\d+>")
PER_EMOJI = re.compile(NUMBER + r"\**\s*(?:/|per|for)\s*\**\s*(?:1\s*)?<a?:(\w+):\d+>", re.I)
WORLD = re.compile(r"[\U0001F30D\U0001F30E\U0001F30F]\s*(?:<a?:\w+:\d+>\s*)?\**\s*([A-Za-z0-9]{1,24})\b")
COORDS = re.compile(r"\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)")
TIMESTAMP = re.compile(r"<t:(\d{9,11})(?::[a-zA-Z])?>")
MARKDOWN = re.compile(r"[*_`~|]")


def lock_unit(emoji_name: str) -> int | None:
    """World Lock value of a lock emoji, guessed from its name."""
    n = re.sub(r"[^a-z]", "", emoji_name.lower())
    if "bgl" in n or "bluegem" in n or "gemlock" in n:
        return WL_PER_BGL
    if "diamond" in n or n.startswith("dl") or n.endswith("dl"):
        return WL_PER_DL
    if "worldlock" in n or n.startswith("wl") or n.endswith("wl"):
        return 1
    return None


def _num(text: str) -> float:
    return float(text.replace(",", ""))


def price_from_text(text: str) -> int | None:
    """Price in vend_core's convention from a listing line, or None."""
    m = PER_EMOJI.search(text)
    if m:
        count, unit = _num(m.group(1)), lock_unit(m.group(2))
        if unit and count > 0:
            per_item_wl = unit / count
            if per_item_wl >= 1:
                return max(1, round(per_item_wl))
            return -max(1, round(count / unit))

    cut = re.split(r"\beach\b|\bper\b|/", text, maxsplit=1, flags=re.I)[0]
    total = 0
    for amount, emoji in AMOUNT_EMOJI.findall(cut):
        unit = lock_unit(emoji)
        if unit is None:
            continue
        total += int(round(_num(amount) * unit))
    return total or None


def parse_listing_line(line: str, item_name: str, now: int) -> Listing | None:
    world = WORLD.search(line)
    price = price_from_text(line)
    if not world or not price:
        return None
    coords = COORDS.search(line)
    ts = TIMESTAMP.search(line)
    accessible = True if "✅" in line else False if ("❌" in line or "❎" in line) else None
    return Listing(
        item_name=item_name,
        world=world.group(1).upper(),
        price=price,
        updated_at=int(ts.group(1)) if ts else now,
        x=int(coords.group(1)) if coords else 0,
        y=int(coords.group(2)) if coords else 0,
        accessible=accessible,
    )


def clean_title(title: str) -> str:
    title = CUSTOM_EMOJI.sub("", title or "")
    return " ".join(MARKDOWN.sub("", title).split())


def parse_embed(embed: dict, fallback_item: str, now: int | None = None) -> list[Listing]:
    now = int(time.time()) if now is None else now
    item = clean_title(embed.get("title", "")) or fallback_item
    texts = [embed.get("description") or ""]
    for f in embed.get("fields") or []:
        texts.append(f"{f.get('name', '')}\n{f.get('value', '')}")
    out = []
    for text in texts:
        for line in text.splitlines():
            listing = parse_listing_line(line, item, now)
            if listing:
                out.append(listing)
    return out


def parse_message(message: dict, fallback_item: str, now: int | None = None) -> list[Listing]:
    out = []
    for embed in message.get("embeds") or []:
        out.extend(parse_embed(embed, fallback_item, now))
    return out


def page_info(message: dict) -> tuple[int, int] | None:
    for embed in message.get("embeds") or []:
        text = MARKDOWN.sub("", (embed.get("description") or "") + " " + ((embed.get("footer") or {}).get("text") or ""))
        m = re.search(r"Page\s*(\d+)\s*/\s*(\d+)", text, re.I)
        if m:
            return int(m.group(1)), int(m.group(2))
    return None


NEXT_LABELS = ("next", "sonraki", "ileri", "▶", "➡", "›", "»", ">", "⏩")


def find_next_button(message: dict) -> dict | None:
    for row in message.get("components") or []:
        for comp in row.get("components") or []:
            if comp.get("type") != 2 or comp.get("disabled") or not comp.get("custom_id"):
                continue
            label = (comp.get("label") or "").strip().lower()
            emoji = (comp.get("emoji") or {}).get("name") or ""
            cid = comp["custom_id"].lower()
            if any(t in label or t == emoji for t in NEXT_LABELS) or "next" in cid:
                return comp
    return None


def parse_channel_link(link: str) -> tuple[str, str]:
    m = re.search(r"channels/(\d+)/(\d+)", link or "")
    if not m:
        raise DiscordError("Kanal linki gecersiz. Kanala sag tik -> 'Linki Kopyala' ile alin.")
    return m.group(1), m.group(2)


def make_nonce() -> str:
    return str((int(time.time() * 1000) - DISCORD_EPOCH_MS) << 22 | random.getrandbits(22))


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

def default_http(method: str, url: str, token: str, body: dict | None = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(2):
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": token,
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        })
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                payload = json.loads(raw) if raw else None
            except ValueError:
                payload = raw.decode(errors="replace")
            if exc.code == 429 and attempt == 0 and isinstance(payload, dict):
                time.sleep(min(float(payload.get("retry_after", 1)), 10))
                continue
            return exc.code, payload
    return 429, None


def default_ws_factory(url: str):
    import websocket  # websocket-client
    return websocket.create_connection(url, timeout=30, header=[f"User-Agent: {USER_AGENT}"])


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

@dataclass
class Command:
    application_id: str
    id: str
    version: str
    name: str
    option_name: str
    raw: dict = field(repr=False, default_factory=dict)


class DiscordVendClient:
    def __init__(self, token: str, channel_link: str, bot_name: str = "Vend Finder",
                 command_name: str = "", option_name: str = "", max_pages: int = 3,
                 dump_dir: str | None = None,
                 http: Callable = default_http, ws_factory: Callable = default_ws_factory,
                 api_base: str = API_BASE, gateway_url: str = GATEWAY_URL,
                 reply_timeout: float = 25.0):
        if not token:
            raise DiscordError("config.json icinde discord.token bos.")
        self.token = token.strip()
        self.guild_id, self.channel_id = parse_channel_link(channel_link)
        self.bot_name = bot_name.lower()
        self.command_name = command_name
        self.option_name = option_name
        self.max_pages = max(1, int(max_pages))
        self.dump_dir = dump_dir
        self.http = http
        self.ws_factory = ws_factory
        self.api_base = api_base
        self.gateway_url = gateway_url
        self.reply_timeout = reply_timeout

        self.ws = None
        self.session_id = None
        self.command: Command | None = None
        self._seq = None
        self._events: list[dict] = []
        self._cond = threading.Condition()
        self._closed = threading.Event()
        self._send_lock = threading.Lock()

    # -- gateway ------------------------------------------------------------
    def _send(self, payload: dict):
        with self._send_lock:
            self.ws.send(json.dumps(payload))

    def connect(self):
        if self.ws is not None and not self._closed.is_set():
            return
        self._closed.clear()
        self.ws = self.ws_factory(self.gateway_url)
        hello = json.loads(self.ws.recv())
        if hello.get("op") != 10:
            raise DiscordError(f"Beklenmeyen gateway cevabi: {hello}")
        interval = hello["d"]["heartbeat_interval"] / 1000.0
        self._send({"op": 2, "d": {
            "token": self.token,
            "properties": {"os": "Windows", "browser": "VendFinderOverlay", "device": "VendFinderOverlay"},
            "compress": False,
        }})
        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._heartbeat, args=(interval,), daemon=True).start()

        ready = self._wait(lambda e: e.get("t") == "READY" or e.get("op") == 9 or e.get("_closed"), 20)
        if not ready or ready.get("t") != "READY":
            self.close()
            raise DiscordError("Discord'a baglanilamadi (token gecersiz olabilir).")
        self.session_id = ready["d"]["session_id"]

    def _reader(self):
        try:
            while not self._closed.is_set():
                raw = self.ws.recv()
                if not raw:
                    break
                event = json.loads(raw)
                if event.get("s") is not None:
                    self._seq = event["s"]
                if event.get("op") == 0 and event.get("t") not in (
                        "READY", "INTERACTION_CREATE", "INTERACTION_SUCCESS", "INTERACTION_FAILURE",
                        "MESSAGE_CREATE", "MESSAGE_UPDATE"):
                    continue  # ignore the rest of the account's traffic
                with self._cond:
                    self._events.append(event)
                    del self._events[:-500]
                    self._cond.notify_all()
                if event.get("op") in (7, 9):  # reconnect / invalid session
                    break
        except Exception:
            pass
        finally:
            self._closed.set()
            with self._cond:
                self._events.append({"_closed": True})
                self._cond.notify_all()

    def _heartbeat(self, interval: float):
        while not self._closed.wait(interval):
            try:
                self._send({"op": 1, "d": self._seq})
            except Exception:
                self._closed.set()

    def _wait(self, predicate, timeout: float, start: int = 0):
        deadline = time.monotonic() + timeout
        with self._cond:
            idx = start
            while True:
                while idx < len(self._events):
                    ev = self._events[idx]
                    idx += 1
                    if predicate(ev):
                        return ev
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._cond.wait(remaining)

    def _mark(self) -> int:
        with self._cond:
            return len(self._events)

    def close(self):
        self._closed.set()
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass
        self.ws = None

    # -- REST ---------------------------------------------------------------
    def _api(self, method: str, path: str, body: dict | None = None):
        status, payload = self.http(method, self.api_base + path, self.token, body)
        if status >= 400:
            raise DiscordError(f"Discord API {status}: {payload}")
        return payload

    def _dump(self, name: str, data):
        if not self.dump_dir:
            return
        try:
            os.makedirs(self.dump_dir, exist_ok=True)
            with open(os.path.join(self.dump_dir, name), "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def discover_command(self) -> Command:
        if self.command:
            return self.command
        index = self._api("GET", f"/guilds/{self.guild_id}/application-command-index")
        self._dump("discord_commands.json", index)
        apps = {a["id"]: a for a in (index or {}).get("applications", [])}
        candidates = []
        for cmd in (index or {}).get("application_commands", []):
            app = apps.get(cmd.get("application_id"), {})
            if self.bot_name and self.bot_name not in (app.get("name") or "").lower():
                continue
            if cmd.get("type", 1) != 1:
                continue
            string_opts = [o for o in cmd.get("options") or [] if o.get("type") == 3]
            if not string_opts:
                continue
            if self.command_name and cmd["name"] != self.command_name:
                continue
            opt = next((o for o in string_opts if o["name"] == self.option_name), None) if self.option_name \
                else (next((o for o in string_opts if o.get("required")), None) or string_opts[0])
            if opt:
                candidates.append(Command(cmd["application_id"], cmd["id"], cmd["version"], cmd["name"], opt["name"], cmd))
        if not candidates:
            raise DiscordError(f"'{self.bot_name}' botunun arama komutu bulunamadi. "
                               "data/discord_commands.json dosyasina bakip config.json'da "
                               "discord.command ve discord.query_option'i ayarlayin.")
        preferred = ("vend", "find", "search", "ara", "price", "fiyat")
        candidates.sort(key=lambda c: next((i for i, p in enumerate(preferred) if p in c.name.lower()), 99))
        self.command = candidates[0]
        return self.command

    def _post_interaction(self, body: dict) -> str:
        nonce = make_nonce()
        body = dict(body, nonce=nonce, session_id=self.session_id)
        self._api("POST", "/interactions", body)
        return nonce

    # -- search -------------------------------------------------------------
    def _wait_reply(self, interaction_nonce: str, start: int, message_id: str | None = None,
                    previous_description: str | None = None) -> dict:
        created = self._wait(lambda e: e.get("_closed") or (
            e.get("t") in ("INTERACTION_CREATE", "INTERACTION_SUCCESS", "INTERACTION_FAILURE")
            and (e.get("d") or {}).get("nonce") == interaction_nonce), self.reply_timeout, start)
        if not created or created.get("_closed"):
            raise DiscordError("Bot komutu kabul etmedi ya da baglanti koptu.")
        if created["t"] == "INTERACTION_FAILURE":
            raise DiscordError("Discord komutu reddetti (INTERACTION_FAILURE).")
        iid = created["d"]["id"]

        def is_reply(e):
            if e.get("_closed"):
                return True
            if e.get("t") not in ("MESSAGE_CREATE", "MESSAGE_UPDATE"):
                return False
            m = e.get("d") or {}
            if m.get("channel_id") != self.channel_id:
                return False
            if message_id is not None:
                if m.get("id") != message_id:
                    return False
            else:
                meta = m.get("interaction_metadata") or m.get("interaction") or {}
                if meta.get("id") != iid:
                    return False
            if (m.get("flags") or 0) & FLAG_LOADING or not m.get("embeds"):
                return False
            if previous_description is not None:
                desc = (m["embeds"][0].get("description") or "")
                if desc == previous_description:
                    return False
            return True

        reply = self._wait(is_reply, self.reply_timeout, start)
        if not reply or reply.get("_closed"):
            raise DiscordError("Bot cevap vermedi (zaman asimi).")
        return reply["d"]

    def search(self, query: str) -> list[Listing]:
        self.connect()
        cmd = self.discover_command()
        start = self._mark()
        nonce = self._post_interaction({
            "type": 2,
            "application_id": cmd.application_id,
            "guild_id": self.guild_id,
            "channel_id": self.channel_id,
            "data": {
                "version": cmd.version, "id": cmd.id, "name": cmd.name, "type": 1,
                "options": [{"type": 3, "name": cmd.option_name, "value": query}],
            },
        })
        message = self._wait_reply(nonce, start)
        pages = [message]
        listings = parse_message(message, query)

        for _ in range(self.max_pages - 1):
            info = page_info(message)
            button = find_next_button(message)
            if not button or (info and info[0] >= info[1]):
                break
            start = self._mark()
            prev_desc = (message["embeds"][0].get("description") or "")
            nonce = self._post_interaction({
                "type": 3,
                "application_id": cmd.application_id,
                "guild_id": self.guild_id,
                "channel_id": self.channel_id,
                "message_id": message["id"],
                "message_flags": message.get("flags") or 0,
                "data": {"component_type": 2, "custom_id": button["custom_id"]},
            })
            try:
                message = self._wait_reply(nonce, start, message_id=message["id"], previous_description=prev_desc)
            except DiscordError:
                break
            pages.append(message)
            listings.extend(parse_message(message, query))

        self._dump("discord_last_reply.json", {"query": query, "command": cmd.name, "pages": pages})
        return listings


class DiscordSearcher:
    """Runs searches on a background thread with a cooldown and a small cache."""

    def __init__(self, client: DiscordVendClient, on_done: Callable[[str, list | None, str | None], None],
                 cooldown: float = 6.0, cache_seconds: float = 120.0):
        self.client = client
        self.on_done = on_done
        self.cooldown = cooldown
        self.cache_seconds = cache_seconds
        self._cache: dict[str, tuple[float, list]] = {}
        self._last = 0.0
        self._lock = threading.Lock()
        self.busy = False

    def submit(self, query: str) -> str | None:
        """Start a search. Returns an error/info message if it was not started."""
        query = " ".join(query.split())
        if not query:
            return "Aramak icin esya adi yazin."
        with self._lock:
            if self.busy:
                return "Discord aramasi zaten suruyor..."
            key = query.lower()
            cached = self._cache.get(key)
            if cached and time.monotonic() - cached[0] < self.cache_seconds:
                self.on_done(query, cached[1], None)
                return None
            wait = self.cooldown - (time.monotonic() - self._last)
            if wait > 0:
                return f"Cok hizli: {wait:.0f} sn sonra tekrar deneyin."
            self.busy = True
            self._last = time.monotonic()
        threading.Thread(target=self._run, args=(query,), daemon=True).start()
        return None

    def _run(self, query: str):
        try:
            listings = self.client.search(query)
            with self._lock:
                self._cache[query.lower()] = (time.monotonic(), listings)
            self.on_done(query, listings, None)
        except Exception as exc:  # report every failure to the UI
            self.client.close()
            self.on_done(query, None, str(exc))
        finally:
            with self._lock:
                self.busy = False
