"""Tests for scripts/auto_tile.lua with a mocked GTProxy Lua environment."""
import struct
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")
from lupa import LuaRuntime  # noqa: E402

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "auto_tile.lua"

MOCKS = r"""
mock = { sent = {}, raw = {}, events = {}, commands = {}, periodic = {}, canceled = {} }
logger = { info = function() end }
LogPacket = { new = function() return {} end }
send = { to_client = function(p) table.insert(mock.sent, p.msg) end }
packet = { send_raw = function(bytes, to_server) table.insert(mock.raw, { bytes = bytes, to_server = to_server }) end }
event = { on = function(name, fn) mock.events[name] = fn end }
command = { register = function(name, desc, fn) mock.commands[name] = fn end }
scheduler = {
    schedule_periodic = function(ms, fn) table.insert(mock.periodic, { ms = ms, fn = fn }); return #mock.periodic end,
    cancel = function(id) mock.canceled[id] = true end,
}
item_database = { get_item = function(self, id) if id == 2 then return { item_name = "Dirt" } end end }

function ac(...) mock.sent = {}; return mock.commands.ac({ args = { ... } }) end
function fire(bytes) mock.events.ServerBoundPacket({ get_data = function(self) return bytes end }) end
function tick() local t = mock.periodic[#mock.periodic]; if mock.canceled[#mock.periodic] then return nil end; return t.fn() end
"""


def tile_packet(x, y, item_id, msg_type=4, pkt_type=3):
    body = bytearray(56)
    body[0] = pkt_type
    struct.pack_into("<i", body, 8, item_id)       # item_net_id
    struct.pack_into("<ff", body, 24, 320.0, 640.0)  # player position (kept as-is)
    struct.pack_into("<ii", body, 44, x, y)
    return struct.pack("<I", msg_type) + bytes(body)


def setup():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(MOCKS)
    lua.execute(SCRIPT.read_text(encoding="utf-8"))
    return lua


def fire(lua, raw):
    lua.globals().fire(lua.table_from(list(raw)))


def sent(lua):
    s = lua.globals().mock.sent
    return [s[i] for i in range(1, len(s) + 1)]


def test_parse_tile_click():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(MOCKS + "AUTO_TILE_TEST = true")
    at = lua.execute(SCRIPT.read_text(encoding="utf-8"))
    c = at.parse_tile_click(lua.table_from(list(tile_packet(12, 34, 18))))
    assert (c.x, c.y, c.item_id) == (12, 34, 18)
    assert at.describe(c) == "(12, 34) yumruk"
    c2 = at.parse_tile_click(lua.table_from(list(tile_packet(1, 2, 2))))
    assert at.describe(c2) == "(1, 2) Dirt"
    assert at.parse_tile_click(lua.table_from(list(tile_packet(1, 2, 18, pkt_type=0)))) is None   # movement
    assert at.parse_tile_click(lua.table_from(list(tile_packet(1, 2, 18, msg_type=3)))) is None
    assert at.parse_tile_click(lua.table_from([4, 0, 0, 0, 3])) is None


def test_record_and_replay_exact_bytes():
    lua = setup()
    g = lua.globals()
    assert set(g.mock.events.keys()) == {"ServerBoundPacket", "JoinRequest", "ClientDisconnect", "ServerDisconnect"}

    p1, p2 = tile_packet(5, 6, 18), tile_packet(5, 7, 2)
    fire(lua, p1)                       # not recording -> ignored
    lua.execute('ac("kaydet")')
    fire(lua, p1)
    fire(lua, tile_packet(0, 0, 18, pkt_type=0))   # non-tile packet ignored
    fire(lua, p2)
    lua.execute('ac("bitti")')
    assert "2 tiklama" in sent(lua)[0]
    fire(lua, tile_packet(9, 9, 18))    # recording off again -> ignored

    assert lua.execute('return ac("basla", "50", "2")') is True
    assert g.mock.periodic[1].ms == 100           # clamped to the minimum
    results = [lua.execute("return tick()") for _ in range(4)]
    assert results == [True, True, True, False]   # 2 clicks x 2 rounds then stop
    raw = g.mock.raw
    replayed = [bytes(raw[i].bytes[j] for j in range(1, len(raw[i].bytes) + 1)) for i in range(1, len(raw) + 1)]
    assert replayed == [p1, p2, p1, p2]
    assert all(raw[i].to_server for i in range(1, len(raw) + 1))
    assert "Tamamlandi" in sent(lua)[-1]


def test_stop_world_change_and_clear():
    lua = setup()
    g = lua.globals()
    assert lua.execute('return ac("basla")') is False
    assert "Kayitli tiklama yok" in sent(lua)[0]

    lua.execute('ac("kaydet")')
    fire(lua, tile_packet(1, 1, 18))
    lua.execute('ac("basla")')
    assert g.mock.periodic[1].ms == 250
    lua.execute('ac("dur")')
    assert g.mock.canceled[1] is True

    lua.execute('ac("basla")')
    g.mock.events.JoinRequest(None)
    assert g.mock.canceled[2] is True
    assert "dunya degisti" in sent(lua)[-1]
    lua.execute('ac("liste")')
    assert "Kayitli tiklama yok" in sent(lua)[0]

    lua.execute('ac("kaydet")')
    for i in range(25):
        fire(lua, tile_packet(i, 0, 18))
    lua.execute('ac("liste")')
    assert len(sent(lua)) == 20
    lua.execute('ac("temizle")')
    lua.execute('ac("liste")')
    assert "Kayitli tiklama yok" in sent(lua)[0]
    assert lua.execute('return ac("nonsense")') is False
