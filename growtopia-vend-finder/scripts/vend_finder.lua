-- Vend Finder for GTProxy
--
-- Every time you enter a world through the proxy, all vending machines /
-- DigiVends in it are read from the world data and saved to
-- data/vend_finder.tsv on your computer. In game you can then type:
--
--   /vend <item name>    cheapest offers for that item in worlds you visited
--   /find <item name>    same as /vend
--   /vgo <number>        warp to the world of result <number> from the last search
--   /vendworlds          list the scanned worlds
--   /venddel <world>     forget one world
--   /vendhelp            show the commands
--
-- Requires GTProxy with patches/0001-vend-finder-lua-bindings.patch applied
-- (it adds world:get_name(), world:get_vendings() and the `storage` API).

local VF = {}

VF.DB_FILE = "vend_finder.tsv"
VF.MAX_RESULTS = 10
VF.SCAN_DELAY_MS = 300
VF.TAG = "`9[Vend Finder]``"

-- worlds[WORLD_NAME] = { scanned_at = <unix seconds>, vends = { {x, y, item_id, price, name}, ... } }
VF.worlds = {}
VF.last_results = {}

---------------------------------------------------------------------------
-- Pure helpers (no proxy API used here, so they are unit-testable)
---------------------------------------------------------------------------

local function trim(s)
    return (s:gsub("^%s+", ""):gsub("%s+$", ""))
end

-- Tabs / newlines would break the TSV file and backticks are Growtopia color codes.
local function clean_text(s)
    return (tostring(s or ""):gsub("[\t\r\n`]", " "))
end

-- Price in World Locks for a single item. Growtopia stores the vending price as
-- a signed int: > 0 means "price WL per item", < 0 means "-price items per WL".
function VF.price_per_item(price)
    if price > 0 then
        return price
    elseif price < 0 then
        return 1 / (-price)
    end
    return math.huge
end

-- 1 Diamond Lock = 100 WL, 1 Blue Gem Lock = 100 DL.
function VF.format_locks(wl)
    local parts = {}
    local bgl = wl // 10000
    local dl = (wl % 10000) // 100
    local rest = wl % 100
    if bgl > 0 then parts[#parts + 1] = bgl .. " BGL" end
    if dl > 0 then parts[#parts + 1] = dl .. " DL" end
    if rest > 0 or #parts == 0 then parts[#parts + 1] = rest .. " WL" end
    return table.concat(parts, " ")
end

function VF.format_price(price)
    if price < 0 then
        return string.format("`2%d/WL``", -price)
    end
    return string.format("`2%s``", VF.format_locks(price))
end

function VF.format_age(seconds)
    seconds = math.max(0, seconds)
    if seconds < 60 then
        return "az once"
    elseif seconds < 3600 then
        return string.format("%d dk once", seconds // 60)
    elseif seconds < 86400 then
        return string.format("%d sa once", seconds // 3600)
    end
    return string.format("%d gun once", seconds // 86400)
end

function VF.serialize(worlds)
    local names = {}
    for name in pairs(worlds) do names[#names + 1] = name end
    table.sort(names)

    local lines = { "# world\tscanned_at\tx\ty\titem_id\tprice\titem_name" }
    for _, name in ipairs(names) do
        local w = worlds[name]
        for _, v in ipairs(w.vends) do
            lines[#lines + 1] = table.concat({
                name, tostring(w.scanned_at), tostring(v.x), tostring(v.y),
                tostring(v.item_id), tostring(v.price), clean_text(v.name),
            }, "\t")
        end
    end
    return table.concat(lines, "\n") .. "\n"
end

function VF.deserialize(text)
    local worlds = {}
    for line in (text or ""):gmatch("[^\r\n]+") do
        if line:sub(1, 1) ~= "#" then
            local f = {}
            for field in (line .. "\t"):gmatch("([^\t]*)\t") do f[#f + 1] = field end
            local world_name = f[1]
            local scanned_at, x, y, item_id, price =
                tonumber(f[2]), tonumber(f[3]), tonumber(f[4]), tonumber(f[5]), tonumber(f[6])
            if world_name and world_name ~= "" and scanned_at and x and y and item_id and price then
                local w = worlds[world_name]
                if not w then
                    w = { scanned_at = scanned_at, vends = {} }
                    worlds[world_name] = w
                end
                w.vends[#w.vends + 1] = {
                    x = math.tointeger(x) or x, y = math.tointeger(y) or y,
                    item_id = math.tointeger(item_id) or item_id,
                    price = math.tointeger(price) or price,
                    name = f[7] or "",
                }
            end
        end
    end
    return worlds
end

-- Returns matching offers sorted by cheapest price per item, then most recent.
-- An exact (case-insensitive) item name match wins over partial matches.
function VF.search(worlds, query)
    query = trim(query):lower()
    if query == "" then return {} end

    local exact, partial = {}, {}
    for world_name, w in pairs(worlds) do
        for _, v in ipairs(w.vends) do
            local name = (v.name or ""):lower()
            local offer = {
                world = world_name, scanned_at = w.scanned_at,
                x = v.x, y = v.y, item_id = v.item_id, price = v.price, name = v.name,
            }
            if name == query then
                exact[#exact + 1] = offer
            elseif name:find(query, 1, true) then
                partial[#partial + 1] = offer
            end
        end
    end

    local results = #exact > 0 and exact or partial
    table.sort(results, function(a, b)
        local pa, pb = VF.price_per_item(a.price), VF.price_per_item(b.price)
        if pa ~= pb then return pa < pb end
        if a.scanned_at ~= b.scanned_at then return a.scanned_at > b.scanned_at end
        if a.world ~= b.world then return a.world < b.world end
        if a.y ~= b.y then return a.y < b.y end
        return a.x < b.x
    end)
    return results
end

-- Turns the raw world:get_vendings() output into stored vend entries.
-- Empty machines (no item) and machines without a price are skipped.
function VF.build_vends(raw_vendings, item_name_of)
    local vends = {}
    for _, v in ipairs(raw_vendings or {}) do
        if v.item_id and v.item_id ~= 0 and v.price and v.price ~= 0 then
            vends[#vends + 1] = {
                x = v.x, y = v.y, item_id = v.item_id, price = v.price,
                name = clean_text(item_name_of(v.item_id)),
            }
        end
    end
    return vends
end

function VF.format_result_line(index, offer, now)
    return string.format(
        "`w%d.`` %s `o%s`` - `w%s`` (%d, %d) - %s",
        index, VF.format_price(offer.price), clean_text(offer.name), offer.world,
        offer.x, offer.y, VF.format_age(now - offer.scanned_at)
    )
end

---------------------------------------------------------------------------
-- Proxy integration
---------------------------------------------------------------------------

local function now()
    return storage.now()
end

local function item_name_of(item_id)
    local item = item_database:get_item(item_id)
    if item and item.item_name and item.item_name ~= "" then
        return item.item_name
    end
    return "Item #" .. tostring(item_id)
end

local function say(msg)
    local log = LogPacket.new()
    log.msg = msg
    send.to_client(log)
end

function VF.load()
    local text = storage.read(VF.DB_FILE)
    VF.worlds = VF.deserialize(text)
    local world_count, vend_count = 0, 0
    for _, w in pairs(VF.worlds) do
        world_count = world_count + 1
        vend_count = vend_count + #w.vends
    end
    logger.info(string.format("[VendFinder] Loaded %d vends from %d worlds (%s)",
        vend_count, world_count, storage.path()))
end

function VF.save()
    if not storage.write(VF.DB_FILE, VF.serialize(VF.worlds)) then
        logger.error("[VendFinder] Could not save " .. VF.DB_FILE)
    end
end

function VF.scan_current_world()
    local world_name = world:get_name()
    if not world_name or world_name == "" or world_name == "EXIT" then
        return
    end

    local vends = VF.build_vends(world:get_vendings(), item_name_of)
    local had_before = VF.worlds[world_name] ~= nil

    if #vends == 0 then
        -- No (priced) vends any more: forget the world so stale prices disappear.
        if had_before then
            VF.worlds[world_name] = nil
            VF.save()
        end
        return
    end

    VF.worlds[world_name] = { scanned_at = now(), vends = vends }
    VF.save()
    say(string.format("%s `w%s``: `2%d`` vend kaydedildi.", VF.TAG, world_name, #vends))
end

local scan_task = nil
local function on_map_data()
    -- Let the proxy's own world handler finish parsing the map first.
    if scan_task and scheduler.is_pending(scan_task) then
        scheduler.cancel(scan_task)
    end
    scan_task = scheduler.schedule(VF.SCAN_DELAY_MS, function()
        local ok, err = pcall(VF.scan_current_world)
        if not ok then
            logger.error("[VendFinder] Scan failed: " .. tostring(err))
        end
    end)
end

local function cmd_vend(ctx)
    local query = table.concat(ctx.args, " ")
    if trim(query) == "" then
        say(VF.TAG .. " Kullanim: `w/vend <esya adi>`` (ornek: /vend magplant)")
        return false
    end

    local results = VF.search(VF.worlds, query)
    VF.last_results = results
    if #results == 0 then
        say(string.format("%s `4'%s'`` icin kayitli vend yok. Once satan dunyalara gir.",
            VF.TAG, clean_text(query)))
        return true
    end

    local t = now()
    say(string.format("%s `w%s`` icin `2%d`` ilan (en ucuz once):",
        VF.TAG, clean_text(query), #results))
    for i = 1, math.min(#results, VF.MAX_RESULTS) do
        say(VF.format_result_line(i, results[i], t))
    end
    if #results > VF.MAX_RESULTS then
        say(string.format("`o... ve %d ilan daha.``", #results - VF.MAX_RESULTS))
    end
    say("`oDunyaya gitmek icin: /vgo <numara>``")
    return true
end

local function cmd_vgo(ctx)
    local n = tonumber(ctx.args[1] or "")
    local offer = n and VF.last_results[math.tointeger(n) or -1]
    if not offer then
        say(VF.TAG .. " Kullanim: `w/vgo <numara>`` (once /vend ile ara)")
        return false
    end
    -- get_prefix() may return extra leading bytes in some GTProxy builds; the
    -- prefix itself is always the last character.
    local prefix = (command.get_prefix() or "/"):sub(-1)
    return command.execute(prefix .. "warp " .. offer.world)
end

local function cmd_worlds(ctx)
    local list = {}
    for name, w in pairs(VF.worlds) do list[#list + 1] = { name = name, w = w } end
    table.sort(list, function(a, b) return a.w.scanned_at > b.w.scanned_at end)

    if #list == 0 then
        say(VF.TAG .. " Henuz taranmis dunya yok.")
        return true
    end

    local t = now()
    say(string.format("%s `2%d`` taranmis dunya:", VF.TAG, #list))
    for i = 1, math.min(#list, 20) do
        local e = list[i]
        say(string.format("`w%s`` - %d vend - %s", e.name, #e.w.vends, VF.format_age(t - e.w.scanned_at)))
    end
    if #list > 20 then
        say(string.format("`o... ve %d dunya daha.``", #list - 20))
    end
    return true
end

local function cmd_del(ctx)
    local name = (ctx.args[1] or ""):upper()
    if name == "" then
        say(VF.TAG .. " Kullanim: `w/venddel <dunya>``")
        return false
    end
    if not VF.worlds[name] then
        say(string.format("%s `4%s`` kayitli degil.", VF.TAG, name))
        return true
    end
    VF.worlds[name] = nil
    VF.save()
    say(string.format("%s `w%s`` silindi.", VF.TAG, name))
    return true
end

local function cmd_help(ctx)
    say(VF.TAG .. " Komutlar:")
    say("`w/vend <esya>`` veya `w/find <esya>`` - girdigin dunyalardaki en ucuz vendler")
    say("`w/vgo <numara>`` - son aramadaki ilanin dunyasina git")
    say("`w/vendworlds`` - taranmis dunyalar, `w/venddel <dunya>`` - dunyayi sil")
    return true
end

function VF.install()
    if type(world.get_vendings) ~= "function" or type(storage) ~= "table" then
        logger.error("[VendFinder] This GTProxy build is missing the vend finder patch "
            .. "(patches/0001-vend-finder-lua-bindings.patch). Script disabled.")
        return false
    end

    VF.load()
    event.on("SendMapData", on_map_data)

    command.register("vend", "Find the cheapest vends for an item", cmd_vend)
    command.register("find", "Same as /vend", cmd_vend)
    command.register("vgo", "Warp to a result of the last /vend search", cmd_vgo)
    command.register("vendworlds", "List worlds scanned by Vend Finder", cmd_worlds)
    command.register("venddel", "Remove a world from Vend Finder", cmd_del)
    command.register("vendhelp", "Vend Finder help", cmd_help)

    logger.info("[VendFinder] Ready. Type /vendhelp in game.")
    return true
end

-- When loaded by the test runner, only expose the module.
if VEND_FINDER_TEST then
    return VF
end

VF.install()
