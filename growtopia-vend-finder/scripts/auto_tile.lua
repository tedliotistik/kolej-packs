-- Auto Tile for GTProxy: record your own punch / place clicks and repeat them.
--
-- GTProxy cannot see the mouse; it sees the packet the game sends when you
-- click a tile (punch with fist / place a block / use an item on a tile).
-- This script records those packets exactly as the game sent them and sends
-- them again on a timer, so it keeps working while Growtopia is alt-tabbed.
--
--   /ac kaydet          start recording: click (punch/place) the tiles you want
--   /ac bitti           stop recording
--   /ac basla [ms] [n]  repeat the recorded clicks every <ms> (default 250),
--                       optionally stop after <n> rounds
--   /ac dur             stop repeating
--   /ac liste           show the recorded clicks
--   /ac temizle         forget the recorded clicks
--
-- The packets contain your character position at recording time, so do not
-- move while it runs. Repeating stops automatically when you leave the world
-- or disconnect.
--
-- WARNING: this is automation (botting). Growtopia bans for it more harshly
-- than for using a proxy at all. Use at your own risk.

local AT = {}

AT.DEFAULT_INTERVAL_MS = 250
AT.MIN_INTERVAL_MS = 100
AT.MAX_RECORDED = 20
AT.TAG = "`9[Auto Tile]``"

AT.recording = false
AT.clicks = {}        -- { { bytes = {...}, x = , y = , item_id = }, ... }
AT.task = nil
AT.rounds_left = nil
AT.next_index = 1

-- Raw client -> server packet layout (little endian):
--   [1..4]   message type (4 = NET_MESSAGE_GAME_PACKET)
--   [5]      game packet type (3 = PACKET_TILE_CHANGE_REQUEST)
--   [13..16] item id (18 = fist / punch)
--   [49..52] tile x, [53..56] tile y
local NET_MESSAGE_GAME_PACKET = 4
local PACKET_TILE_CHANGE_REQUEST = 3
local MIN_SIZE = 56

local function int32_at(bytes, first)
    local s = string.char(bytes[first], bytes[first + 1], bytes[first + 2], bytes[first + 3])
    return (string.unpack("<i4", s))
end

-- Returns { bytes, x, y, item_id } if the raw packet is a tile click, else nil.
function AT.parse_tile_click(bytes)
    if type(bytes) ~= "table" or #bytes < MIN_SIZE then
        return nil
    end
    if int32_at(bytes, 1) ~= NET_MESSAGE_GAME_PACKET or bytes[5] ~= PACKET_TILE_CHANGE_REQUEST then
        return nil
    end
    local copy = {}
    for i = 1, #bytes do copy[i] = bytes[i] end
    return {
        bytes = copy,
        item_id = int32_at(bytes, 13),
        x = int32_at(bytes, 49),
        y = int32_at(bytes, 53),
    }
end

function AT.describe(click)
    local what
    if click.item_id == 18 then
        what = "yumruk"
    else
        local item = item_database and item_database:get_item(click.item_id)
        what = (item and item.item_name ~= "" and item.item_name) or ("item #" .. click.item_id)
    end
    return string.format("(%d, %d) %s", click.x, click.y, what)
end

local function say(msg)
    local log = LogPacket.new()
    log.msg = msg
    send.to_client(log)
end

function AT.stop(reason)
    if AT.task then
        scheduler.cancel(AT.task)
        AT.task = nil
        say(AT.TAG .. " Durdu" .. (reason and (": " .. reason) or "."))
    end
end

local function tick()
    if #AT.clicks == 0 then
        AT.task = nil
        return false
    end

    local click = AT.clicks[AT.next_index]
    packet.send_raw(click.bytes, true)

    AT.next_index = AT.next_index + 1
    if AT.next_index > #AT.clicks then
        AT.next_index = 1
        if AT.rounds_left then
            AT.rounds_left = AT.rounds_left - 1
            if AT.rounds_left <= 0 then
                AT.task = nil
                say(AT.TAG .. " Tamamlandi.")
                return false
            end
        end
    end
    return true
end

function AT.start(interval_ms, rounds)
    if #AT.clicks == 0 then
        say(AT.TAG .. " `4Kayitli tiklama yok.`` Once `w/ac kaydet`` yazip karelere tikla.")
        return false
    end
    AT.stop()
    AT.recording = false
    AT.next_index = 1
    AT.rounds_left = rounds
    AT.task = scheduler.schedule_periodic(interval_ms, tick)
    say(string.format("%s Basladi: %d tiklama, %d ms arayla%s. Durdurmak icin `w/ac dur``",
        AT.TAG, #AT.clicks, interval_ms, rounds and (", " .. rounds .. " tur") or ""))
    return true
end

local function on_server_bound(ctx)
    if not AT.recording then return end
    local click = AT.parse_tile_click(ctx:get_data())
    if not click then return end
    if #AT.clicks >= AT.MAX_RECORDED then
        say(string.format("%s En fazla %d tiklama kaydedilebilir.", AT.TAG, AT.MAX_RECORDED))
        AT.recording = false
        return
    end
    AT.clicks[#AT.clicks + 1] = click
    say(string.format("%s %d. kaydedildi: %s", AT.TAG, #AT.clicks, AT.describe(click)))
end

local function cmd_ac(ctx)
    local sub = (ctx.args[1] or ""):lower()

    if sub == "kaydet" or sub == "record" then
        AT.stop()
        AT.recording = true
        say(AT.TAG .. " Kayit acik. Istedigin karelere vur/koy, bitince `w/ac bitti`` yaz.")
    elseif sub == "bitti" or sub == "done" then
        AT.recording = false
        say(string.format("%s Kayit bitti: %d tiklama. Baslatmak icin `w/ac basla [ms]``", AT.TAG, #AT.clicks))
    elseif sub == "basla" or sub == "start" then
        local interval = math.tointeger(tonumber(ctx.args[2] or "")) or AT.DEFAULT_INTERVAL_MS
        if interval < AT.MIN_INTERVAL_MS then interval = AT.MIN_INTERVAL_MS end
        local rounds = math.tointeger(tonumber(ctx.args[3] or ""))
        if rounds and rounds < 1 then rounds = nil end
        return AT.start(interval, rounds)
    elseif sub == "dur" or sub == "stop" then
        if AT.task then AT.stop() else say(AT.TAG .. " Zaten calismiyor.") end
    elseif sub == "liste" or sub == "list" then
        if #AT.clicks == 0 then
            say(AT.TAG .. " Kayitli tiklama yok.")
        else
            for i, c in ipairs(AT.clicks) do say(string.format("`w%d.`` %s", i, AT.describe(c))) end
        end
    elseif sub == "temizle" or sub == "clear" then
        AT.stop()
        AT.recording = false
        AT.clicks = {}
        say(AT.TAG .. " Kayitlar silindi.")
    else
        say(AT.TAG .. " `w/ac kaydet``, `w/ac bitti``, `w/ac basla [ms] [tur]``, `w/ac dur``, `w/ac liste``, `w/ac temizle``")
        return false
    end
    return true
end

function AT.install()
    event.on("ServerBoundPacket", on_server_bound)
    -- Recorded packets only make sense in the world/position they were made in.
    event.on("JoinRequest", function()
        AT.stop("dunya degisti")
        AT.recording = false
        AT.clicks = {}
    end)
    event.on("ClientDisconnect", function() AT.stop("baglanti koptu") end)
    event.on("ServerDisconnect", function() AT.stop("baglanti koptu") end)
    command.register("ac", "Record and repeat tile clicks", cmd_ac)
    logger.info("[AutoTile] Ready. Type /ac in game.")
end

if AUTO_TILE_TEST then
    return AT
end

AT.install()
