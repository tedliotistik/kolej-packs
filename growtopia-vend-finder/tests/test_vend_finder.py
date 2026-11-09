"""Tests for scripts/vend_finder.lua using a mocked GTProxy Lua environment.

Run:  pip install lupa pytest && pytest growtopia-vend-finder/tests
"""
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")
from lupa import LuaRuntime  # noqa: E402

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "vend_finder.lua"

MOCKS = r"""
mock = { files = {}, logs = {}, sent = {}, events = {}, commands = {}, executed = {},
         tasks = {}, clock = 1000000, world_name = "", vendings = {} }

storage = {
    read = function(name) return mock.files[name] end,
    write = function(name, content) mock.files[name] = content; return true end,
    now = function() return mock.clock end,
    path = function() return "data" end,
}
logger = {
    info = function(m) table.insert(mock.logs, m) end,
    error = function(m) table.insert(mock.logs, "ERROR " .. m) end,
}
LogPacket = { new = function() return {} end }
send = { to_client = function(p) table.insert(mock.sent, p.msg) end }
event = { on = function(name, fn) mock.events[name] = fn end }
command = {
    register = function(name, desc, fn) mock.commands[name] = fn end,
    get_prefix = function() return "\1/" end,  -- mimic GTProxy's 2-char bug
    execute = function(s) table.insert(mock.executed, s); return true end,
}
scheduler = {
    schedule = function(ms, fn) table.insert(mock.tasks, fn); return #mock.tasks end,
    is_pending = function(id) return false end,
    cancel = function(id) end,
}
world = {
    get_name = function(self) return mock.world_name end,
    get_vendings = function(self) return mock.vendings end,
}
local names = { [2] = "Dirt", [3] = "Dirt Seed", [5640] = "Magplant 5000", [242] = "World Lock" }
item_database = { get_item = function(self, id)
    if names[id] then return { item_name = names[id] } end
    return nil
end }

function run_tasks()
    local t = mock.tasks; mock.tasks = {}
    for _, fn in ipairs(t) do fn() end
end

function run_cmd(name, ...)
    mock.sent = {}
    return mock.commands[name]({ args = { ... } })
end
"""


def make_runtime(test_mode=False):
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(MOCKS)
    if test_mode:
        lua.execute("VEND_FINDER_TEST = true")
    return lua


def load_module():
    lua = make_runtime(test_mode=True)
    vf = lua.execute(SCRIPT.read_text(encoding="utf-8"))
    return lua, vf


def lua_list(lua, values):
    return lua.table_from([lua.table_from(v) for v in values])


def to_py(seq):
    return [seq[i] for i in range(1, len(seq) + 1)]


def test_price_per_item_and_format():
    lua, vf = load_module()
    assert vf.price_per_item(5) == 5
    assert vf.price_per_item(-4) == 0.25
    assert vf.format_locks(1) == "1 WL"
    assert vf.format_locks(100) == "1 DL"
    assert vf.format_locks(4059) == "40 DL 59 WL"
    assert vf.format_locks(12345) == "1 BGL 23 DL 45 WL"
    assert vf.format_price(-200) == "`2200/WL``"
    assert vf.format_price(250) == "`22 DL 50 WL``"


def test_format_age():
    _, vf = load_module()
    assert vf.format_age(10) == "az once"
    assert vf.format_age(125) == "2 dk once"
    assert vf.format_age(4 * 3600 + 5) == "4 sa once"
    assert vf.format_age(3 * 86400) == "3 gun once"


def test_serialize_roundtrip_and_cleaning():
    lua, vf = load_module()
    worlds = lua.eval("""{
        BUYDIRT = { scanned_at = 50, vends = { { x = 1, y = 2, item_id = 2, price = -200, name = "Di\\trt" } } },
        AAA = { scanned_at = 60, vends = { { x = 3, y = 4, item_id = 5640, price = 300, name = "Magplant 5000" } } },
    }""")
    text = vf.serialize(worlds)
    assert "\t\t" not in text  # tab inside the name was replaced
    back = vf.deserialize(text)
    assert back["BUYDIRT"].scanned_at == 50
    v = back["BUYDIRT"].vends[1]
    assert (v.x, v.y, v.item_id, v.price, v.name) == (1, 2, 2, -200, "Di rt")
    assert back["AAA"].vends[1].price == 300
    # Garbage lines are ignored.
    assert len(list(vf.deserialize("bad line\n#comment\n").keys())) == 0


def test_build_vends_skips_empty_and_unpriced():
    lua, vf = load_module()
    raw = lua_list(lua, [
        {"x": 0, "y": 0, "item_id": 0, "price": 5},       # empty machine
        {"x": 1, "y": 0, "item_id": 2, "price": 0},       # no price set
        {"x": 2, "y": 0, "item_id": 2, "price": -150},
        {"x": 3, "y": 0, "item_id": 99999, "price": 1},   # unknown item id
    ])
    name_of = lua.eval("function(id) local i = item_database:get_item(id); return i and i.item_name or ('Item #' .. id) end")
    vends = to_py(vf.build_vends(raw, name_of))
    assert [(v.x, v.name) for v in vends] == [(2, "Dirt"), (3, "Item #99999")]


def test_search_exact_beats_partial_and_sorts_by_price():
    lua, vf = load_module()
    worlds = lua.eval("""{
        A = { scanned_at = 10, vends = {
            { x = 1, y = 1, item_id = 2, price = 1, name = "Dirt" },
            { x = 2, y = 1, item_id = 3, price = -500, name = "Dirt Seed" } } },
        B = { scanned_at = 20, vends = { { x = 5, y = 5, item_id = 2, price = -200, name = "Dirt" } } },
        C = { scanned_at = 30, vends = { { x = 6, y = 6, item_id = 2, price = -200, name = "Dirt" } } },
    }""")
    res = to_py(vf.search(worlds, "  DIRT "))
    # Exact name match only; cheapest first; equal price -> newest scan first.
    assert [(r.world, r.price) for r in res] == [("C", -200), ("B", -200), ("A", 1)]
    res = to_py(vf.search(worlds, "seed"))
    assert [r.name for r in res] == ["Dirt Seed"]
    assert len(vf.search(worlds, "")) == 0
    assert len(vf.search(worlds, "magplant")) == 0


def full_install():
    lua = make_runtime()
    lua.execute(SCRIPT.read_text(encoding="utf-8"))
    return lua


def test_scan_command_and_warp_flow():
    lua = full_install()
    mock = lua.globals().mock
    assert set(mock.commands.keys()) >= {"vend", "find", "vgo", "vendworlds", "venddel", "vendhelp"}

    # Enter a world with two vends.
    lua.execute("""
        mock.world_name = "MAGSHOP"
        mock.vendings = {
            { x = 10, y = 20, item_id = 5640, price = 250 },
            { x = 11, y = 20, item_id = 2, price = -180 },
            { x = 12, y = 20, item_id = 0, price = 0 },
        }
        mock.events.SendMapData({})
        run_tasks()
    """)
    assert "MAGSHOP" in mock.files["vend_finder.tsv"]
    assert any("2`` vend kaydedildi" in m for m in to_py(mock.sent))

    lua.execute("mock.clock = mock.clock + 7200")
    lua.execute('run_cmd("vend", "magplant")')
    out = to_py(mock.sent)
    assert "1`` ilan" in out[0]
    assert "2 DL 50 WL" in out[1] and "MAGSHOP" in out[1] and "(10, 20)" in out[1] and "2 sa once" in out[1]

    # /find is an alias.
    lua.execute('run_cmd("find", "Magplant", "5000")')
    assert "MAGSHOP" in to_py(mock.sent)[1]

    # /vgo warps through GTProxy's /warp command with the correct prefix.
    lua.execute('run_cmd("vgo", "1")')
    assert to_py(mock.executed) == ["/warp MAGSHOP"]

    # Persisted data survives a reload.
    lua2 = make_runtime()
    lua2.globals().mock.files["vend_finder.tsv"] = mock.files["vend_finder.tsv"]
    lua2.execute(SCRIPT.read_text(encoding="utf-8"))
    lua2.execute('run_cmd("vend", "dirt")')
    assert "180/WL" in to_py(lua2.globals().mock.sent)[1]


def test_world_without_vends_is_forgotten_and_venddel():
    lua = full_install()
    mock = lua.globals().mock
    lua.execute("""
        mock.world_name = "SHOPA"
        mock.vendings = { { x = 1, y = 1, item_id = 2, price = 3 } }
        mock.events.SendMapData({}); run_tasks()
        mock.world_name = "SHOPB"
        mock.events.SendMapData({}); run_tasks()
        -- SHOPA's owner removed the vends
        mock.world_name = "SHOPA"
        mock.vendings = {}
        mock.events.SendMapData({}); run_tasks()
    """)
    data = mock.files["vend_finder.tsv"]
    assert "SHOPA" not in data and "SHOPB" in data

    lua.execute('run_cmd("venddel", "shopb")')
    assert "SHOPB" not in mock.files["vend_finder.tsv"]
    lua.execute('run_cmd("vend", "dirt")')
    assert "kayitli vend yok" in to_py(mock.sent)[0]


def test_usage_messages():
    lua = full_install()
    mock = lua.globals().mock
    assert lua.execute('return run_cmd("vend")') is False
    assert "Kullanim" in to_py(mock.sent)[0]
    assert lua.execute('return run_cmd("vgo", "3")') is False
    assert lua.execute('return run_cmd("vendworlds")') is True
    assert "Henuz" in to_py(mock.sent)[0]


def test_disabled_without_patch():
    lua = make_runtime()
    lua.execute("world.get_vendings = nil")
    lua.execute(SCRIPT.read_text(encoding="utf-8"))
    mock = lua.globals().mock
    assert len(list(mock.commands.keys())) == 0
    assert any("missing the vend finder patch" in m for m in to_py(mock.logs))
