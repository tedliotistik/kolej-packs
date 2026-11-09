"""Vend Finder overlay: a small always-on-top search window for Growtopia prices.

It never touches the game (no proxy, no memory reading, no input injection):
it only shows a window when you press the hotkey (F8 by default) and reads /
writes a local data file.

Run:  python vend_overlay.py            (or the built VendOverlay.exe)
"""
from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import vend_core as core

APP_TITLE = "Vend Finder"
DEFAULT_CONFIG = {
    "hotkey": "F8",
    "data_file": "data/vend_finder.tsv",
    "opacity": 0.95,
    "always_on_top": True,
    "start_hidden": False,
}


def base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def load_config() -> dict:
    path = os.path.join(base_dir(), "config.json")
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(path, encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    except FileNotFoundError:
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(cfg, fh, indent=2)
        except OSError:
            pass
    except (OSError, ValueError) as exc:
        print(f"config.json okunamadi, varsayilanlar kullaniliyor: {exc}")
    data_file = cfg["data_file"]
    if not os.path.isabs(data_file):
        cfg["data_file"] = os.path.join(base_dir(), data_file)
    return cfg


# ---------------------------------------------------------------------------
# Global hotkey (Windows only, via RegisterHotKey - no keyboard hooks)
# ---------------------------------------------------------------------------

MODIFIERS = {"ALT": 0x1, "CTRL": 0x2, "CONTROL": 0x2, "SHIFT": 0x4, "WIN": 0x8}
NAMED_KEYS = {
    **{f"F{i}": 0x6F + i for i in range(1, 25)},
    "INSERT": 0x2D, "HOME": 0x24, "END": 0x23, "PAGEUP": 0x21, "PAGEDOWN": 0x22,
    "PAUSE": 0x13, "SCROLLLOCK": 0x91, "SPACE": 0x20, "TAB": 0x09,
    "NUMPAD0": 0x60, "NUMPAD1": 0x61, "NUMPAD2": 0x62, "NUMPAD3": 0x63, "NUMPAD4": 0x64,
    "NUMPAD5": 0x65, "NUMPAD6": 0x66, "NUMPAD7": 0x67, "NUMPAD8": 0x68, "NUMPAD9": 0x69,
}


def parse_hotkey(text: str) -> tuple[int, int]:
    """'CTRL+SHIFT+V' -> (modifiers, virtual key code)."""
    mods, vk = 0, None
    for part in [p.strip().upper() for p in text.split("+") if p.strip()]:
        if part in MODIFIERS:
            mods |= MODIFIERS[part]
        elif part in NAMED_KEYS:
            vk = NAMED_KEYS[part]
        elif len(part) == 1 and part.isalnum():
            vk = ord(part)
        else:
            raise ValueError(f"Bilinmeyen tus: {part}")
    if vk is None:
        raise ValueError("Kisayolda bir tus olmali (or. F8 veya CTRL+SHIFT+V)")
    return mods, vk


class HotkeyListener(threading.Thread):
    WM_HOTKEY = 0x0312
    WM_QUIT = 0x0012
    MOD_NOREPEAT = 0x4000

    def __init__(self, hotkey: str, events: "queue.Queue[str]"):
        super().__init__(daemon=True)
        self.hotkey = hotkey
        self.events = events
        self.thread_id = None
        self.error = None
        self.ready = threading.Event()

    def run(self):
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self.thread_id = kernel32.GetCurrentThreadId()
        try:
            mods, vk = parse_hotkey(self.hotkey)
        except ValueError as exc:
            self.error = str(exc)
            self.ready.set()
            return
        if not user32.RegisterHotKey(None, 1, mods | self.MOD_NOREPEAT, vk):
            self.error = f"{self.hotkey} kisayolu baska bir program tarafindan kullaniliyor."
            self.ready.set()
            return
        self.ready.set()
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == self.WM_HOTKEY:
                    self.events.put("toggle")
        finally:
            user32.UnregisterHotKey(None, 1)

    def stop(self):
        if self.thread_id:
            import ctypes
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, self.WM_QUIT, 0, 0)


# ---------------------------------------------------------------------------
# Add / edit dialog
# ---------------------------------------------------------------------------

class OfferDialog(tk.Toplevel):
    def __init__(self, app: "OverlayApp", offer: core.Offer | None = None):
        super().__init__(app.root)
        self.app = app
        self.original = offer
        self.title("Ilani duzenle" if offer else "Ilan ekle")
        self.transient(app.root)
        self.resizable(False, False)
        self.attributes("-topmost", True)

        frm = ttk.Frame(self, padding=12)
        frm.grid(sticky="nsew")

        self.item = tk.StringVar(value=offer.item_name if offer else app.search_var.get().strip())
        self.world = tk.StringVar(value=offer.world if offer else "")
        self.amount = tk.StringVar()
        self.unit = tk.StringVar(value="WL / adet")
        self.x = tk.StringVar(value=str(offer.x) if offer and (offer.x or offer.y) else "")
        self.y = tk.StringVar(value=str(offer.y) if offer and (offer.x or offer.y) else "")
        if offer:
            if offer.price < 0:
                self.amount.set(str(-offer.price))
                self.unit.set("adet / WL")
            else:
                self.amount.set(str(offer.price))

        rows = [
            ("Esya adi", ttk.Combobox(frm, textvariable=self.item, values=app.store.item_names(), width=30)),
            ("Dunya", ttk.Entry(frm, textvariable=self.world, width=32)),
        ]
        for r, (label, widget) in enumerate(rows):
            ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", pady=3)
            widget.grid(row=r, column=1, columnspan=3, sticky="ew", pady=3)

        ttk.Label(frm, text="Fiyat").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Entry(frm, textvariable=self.amount, width=10).grid(row=2, column=1, sticky="w", pady=3)
        ttk.Combobox(frm, textvariable=self.unit, values=list(core.UNITS), state="readonly",
                     width=12).grid(row=2, column=2, columnspan=2, sticky="w", pady=3)

        ttk.Label(frm, text="Konum (istege bagli)").grid(row=3, column=0, sticky="w", pady=3)
        ttk.Entry(frm, textvariable=self.x, width=6).grid(row=3, column=1, sticky="w")
        ttk.Entry(frm, textvariable=self.y, width=6).grid(row=3, column=2, sticky="w")

        btns = ttk.Frame(frm)
        btns.grid(row=4, column=0, columnspan=4, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Iptal", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="Kaydet", command=self.on_save).pack(side="right")

        self.bind("<Return>", lambda e: self.on_save())
        self.bind("<Escape>", lambda e: self.destroy())
        rows[0][1].focus_set()
        self.grab_set()

    def on_save(self):
        try:
            item = core.clean_text(self.item.get())
            world = core.normalize_world(self.world.get())
            if not item or not world:
                raise ValueError("Esya adi ve dunya bos olamaz.")
            amount = float(self.amount.get().replace(",", "."))
            price = core.make_price(amount, self.unit.get())
            x = int(self.x.get()) if self.x.get().strip() else 0
            y = int(self.y.get()) if self.y.get().strip() else 0
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, str(exc), parent=self)
            return

        offer = core.Offer(world, item, price, int(time.time()), x, y,
                           self.original.item_id if self.original else 0)
        if self.original and self.original.key != offer.key:
            self.app.store.remove([self.original])
        self.app.store.upsert(offer)
        self.destroy()
        self.app.refresh()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class OverlayApp:
    COLUMNS = (("price", "Fiyat", 150), ("item", "Esya", 170), ("world", "Dunya", 120),
               ("pos", "Konum", 70), ("updated", "Guncellenme", 220))

    def __init__(self, root: tk.Tk, config: dict):
        self.root = root
        self.config = config
        self.store = core.VendStore(config["data_file"])
        self.events: "queue.Queue[str]" = queue.Queue()
        self.rows: dict[str, core.Offer] = {}
        self.hotkey = None

        root.title(APP_TITLE)
        root.geometry("780x460")
        root.minsize(560, 300)
        root.attributes("-topmost", bool(config.get("always_on_top", True)))
        try:
            root.attributes("-alpha", float(config.get("opacity", 0.95)))
        except (tk.TclError, ValueError):
            pass
        root.protocol("WM_DELETE_WINDOW", self.on_close_button)

        self._build()
        self._start_hotkey()
        self.refresh()
        root.after(150, self._poll)
        if config.get("start_hidden") and self.hotkey_ok():
            self.hide()
        else:
            self.show()

    # -- layout -------------------------------------------------------------
    def _build(self):
        style = ttk.Style(self.root)
        style.configure("Search.TEntry", padding=6)
        style.configure("Treeview", rowheight=24)

        outer = ttk.Frame(self.root, padding=8)
        outer.pack(fill="both", expand=True)

        top = ttk.Frame(outer)
        top.pack(fill="x")
        self.search_var = tk.StringVar()
        self.search = ttk.Entry(top, textvariable=self.search_var, style="Search.TEntry",
                                font=("Segoe UI", 13))
        self.search.pack(side="left", fill="x", expand=True)
        ttk.Button(top, text="+ Ekle", command=self.add_offer).pack(side="left", padx=(6, 0))
        self.search_var.trace_add("write", lambda *a: self.refresh())

        flt = ttk.Frame(outer)
        flt.pack(fill="x", pady=(6, 6))
        self.sort_var = tk.StringVar(value=core.SORTS[0])
        self.age_var = tk.StringVar(value=next(iter(core.AGE_FILTERS)))
        self.world_var = tk.StringVar()
        self.max_var = tk.StringVar()

        ttk.Label(flt, text="Siralama").pack(side="left")
        ttk.Combobox(flt, textvariable=self.sort_var, values=core.SORTS, state="readonly",
                     width=16).pack(side="left", padx=(4, 10))
        ttk.Label(flt, text="Guncellenme").pack(side="left")
        ttk.Combobox(flt, textvariable=self.age_var, values=list(core.AGE_FILTERS),
                     state="readonly", width=12).pack(side="left", padx=(4, 10))
        ttk.Label(flt, text="Dunya").pack(side="left")
        ttk.Entry(flt, textvariable=self.world_var, width=12).pack(side="left", padx=(4, 10))
        ttk.Label(flt, text="Max WL/adet").pack(side="left")
        ttk.Entry(flt, textvariable=self.max_var, width=7).pack(side="left", padx=(4, 0))
        for var in (self.sort_var, self.age_var, self.world_var, self.max_var):
            var.trace_add("write", lambda *a: self.refresh())

        table = ttk.Frame(outer)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=[c[0] for c in self.COLUMNS], show="headings",
                                 selectmode="extended")
        for key, label, width in self.COLUMNS:
            self.tree.heading(key, text=label, command=lambda k=key: self.sort_by_column(k))
            self.tree.column(key, width=width, anchor="w")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.tag_configure("old", foreground="#888888")

        self.status = tk.StringVar()
        ttk.Label(outer, textvariable=self.status, foreground="#666666").pack(fill="x", pady=(6, 0))

        self.menu = tk.Menu(self.root, tearoff=False)
        self.menu.add_command(label="Dunya adini kopyala", command=self.copy_world)
        self.menu.add_command(label="Duzenle", command=self.edit_selected)
        self.menu.add_command(label="Fiyat hala ayni (tarihi yenile)", command=self.touch_selected)
        self.menu.add_separator()
        self.menu.add_command(label="Sil", command=self.delete_selected)
        self.menu.add_command(label="Bu dunyanin tum ilanlarini sil", command=self.delete_world)

        self.tree.bind("<Double-1>", lambda e: self.copy_world())
        self.tree.bind("<Button-3>", self._open_menu)
        self.tree.bind("<Delete>", lambda e: self.delete_selected())
        self.root.bind("<Escape>", lambda e: self.hide())
        self.root.bind("<Control-n>", lambda e: self.add_offer())
        self.search.bind("<Down>", lambda e: self._focus_table())
        self.search.bind("<Return>", lambda e: self._focus_table())

    def _start_hotkey(self):
        if sys.platform != "win32":
            return
        self.hotkey = HotkeyListener(self.config.get("hotkey", "F8"), self.events)
        self.hotkey.start()
        self.hotkey.ready.wait(2)
        if self.hotkey.error:
            messagebox.showwarning(APP_TITLE, self.hotkey.error + "\nconfig.json'dan baska bir tus secin.")

    # -- behaviour ----------------------------------------------------------
    def _poll(self):
        try:
            while True:
                if self.events.get_nowait() == "toggle":
                    self.toggle()
        except queue.Empty:
            pass
        self._poll_count = getattr(self, "_poll_count", 0) + 1
        if self._poll_count % 13 == 0 and self.store.reload_if_changed():  # ~every 2 s
            self.refresh()
        self.root.after(150, self._poll)

    def is_visible(self) -> bool:
        return self.root.state() != "withdrawn"

    def toggle(self):
        if self.is_visible() and self.root.focus_displayof() is not None:
            self.hide()
        else:
            self.show()

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", bool(self.config.get("always_on_top", True)))
        self.root.focus_force()
        self.search.focus_set()
        self.search.select_range(0, "end")
        self.store.reload_if_changed()
        self.refresh()

    def hide(self):
        if self.hotkey_ok():
            self.root.withdraw()
        else:
            self.root.iconify()

    def hotkey_ok(self) -> bool:
        return bool(self.hotkey and not self.hotkey.error)

    def on_close_button(self):
        # With a working hotkey the X button only hides the window (reopen with
        # the hotkey, quit with Ctrl+Q). Without one, X really quits.
        if self.hotkey_ok():
            self.hide()
        else:
            self.close()

    def _focus_table(self):
        children = self.tree.get_children()
        if children:
            self.tree.focus_set()
            self.tree.selection_set(children[0])
            self.tree.focus(children[0])

    def _open_menu(self, event):
        row = self.tree.identify_row(event.y)
        if row and row not in self.tree.selection():
            self.tree.selection_set(row)
        if self.tree.selection():
            self.menu.tk_popup(event.x_root, event.y_root)

    def selected(self) -> list[core.Offer]:
        return [self.rows[i] for i in self.tree.selection() if i in self.rows]

    def sort_by_column(self, key):
        if key == "price":
            self.sort_var.set(core.SORTS[1] if self.sort_var.get() == core.SORTS[0] else core.SORTS[0])
        elif key == "updated":
            self.sort_var.set(core.SORTS[3] if self.sort_var.get() == core.SORTS[2] else core.SORTS[2])

    def refresh(self):
        max_wl = None
        try:
            if self.max_var.get().strip():
                max_wl = float(self.max_var.get().replace(",", "."))
        except ValueError:
            max_wl = None

        now = int(time.time())
        results = core.search(
            self.store.offers, self.search_var.get(), self.sort_var.get(),
            core.AGE_FILTERS.get(self.age_var.get()), self.world_var.get(), max_wl=max_wl, now=now,
        )

        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        for i, o in enumerate(results):
            iid = str(i)
            self.rows[iid] = o
            pos = f"{o.x}, {o.y}" if (o.x or o.y) else "-"
            updated = f"{core.format_date(o.updated_at)} ({core.format_age(now - o.updated_at)})"
            tags = ("old",) if now - o.updated_at > 7 * 86400 else ()
            self.tree.insert("", "end", iid=iid, tags=tags,
                             values=(core.format_price(o.price), o.item_name, o.world, pos, updated))

        keys = (f"{self.config.get('hotkey', 'F8')}: ac/kapat, Esc: gizle, Ctrl+Q: cikis"
                if self.hotkey_ok() else "Esc: kucult")
        self.status.set(f"{len(results)} ilan  |  toplam {len(self.store.offers)} kayit  |  "
                        f"{keys}  |  cift tik: dunya adini kopyala, sag tik: duzenle/sil")

    # -- actions ------------------------------------------------------------
    def add_offer(self):
        OfferDialog(self)

    def edit_selected(self):
        sel = self.selected()
        if sel:
            OfferDialog(self, sel[0])

    def copy_world(self):
        sel = self.selected()
        if sel:
            self.root.clipboard_clear()
            self.root.clipboard_append(sel[0].world)
            self.status.set(f"'{sel[0].world}' kopyalandi.")

    def touch_selected(self):
        sel = self.selected()
        if sel:
            self.store.touch(sel)
            self.refresh()

    def delete_selected(self):
        sel = self.selected()
        if sel and messagebox.askyesno(APP_TITLE, f"{len(sel)} ilan silinsin mi?", parent=self.root):
            self.store.remove(sel)
            self.refresh()

    def delete_world(self):
        sel = self.selected()
        if sel and messagebox.askyesno(APP_TITLE, f"{sel[0].world} dunyasinin tum ilanlari silinsin mi?",
                                       parent=self.root):
            self.store.remove_world(sel[0].world)
            self.refresh()

    def close(self):
        if self.hotkey:
            self.hotkey.stop()
        self.root.destroy()


def main():
    config = load_config()
    root = tk.Tk()
    app = OverlayApp(root, config)
    # Ctrl+Q quits; the X button only hides the window while the hotkey works.
    root.bind("<Control-q>", lambda e: app.close())
    root.mainloop()


if __name__ == "__main__":
    main()
