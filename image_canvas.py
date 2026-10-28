# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import math
import tkinter as tk
from typing import Callable
from PIL import Image, ImageTk


class ImageCanvas(tk.Canvas):
    def __init__(self, master, *, on_cursor=None, on_left_press=None,
                 on_left_drag=None, on_left_release=None, on_view_changed=None, **kwargs):
        super().__init__(master, highlightthickness=0, background="#303030", **kwargs)
        self.original_image: Image.Image | None = None
        self.tk_image = None
        self.image_item = None
        self.scale = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.min_scale = 0.01
        self.max_scale = 50.0
        self._render_pending = False
        self._pan_last_x = self._pan_last_y = 0
        self.on_cursor = on_cursor
        self.on_left_press = on_left_press
        self.on_left_drag = on_left_drag
        self.on_left_release = on_left_release
        self.on_view_changed = on_view_changed
        self.bind("<Configure>", self._on_configure)
        self.bind("<Motion>", self._on_motion)
        self.bind("<ButtonPress-1>", self._on_left_press)
        self.bind("<B1-Motion>", self._on_left_drag)
        self.bind("<ButtonRelease-1>", self._on_left_release)
        self.bind("<ButtonPress-2>", self._pan_start); self.bind("<B2-Motion>", self._pan_move)
        self.bind("<ButtonPress-3>", self._pan_start); self.bind("<B3-Motion>", self._pan_move)
        self.bind("<MouseWheel>", self._on_mousewheel)
        self.bind("<Button-4>", lambda e: self.zoom_at(e.x, e.y, 1.15))
        self.bind("<Button-5>", lambda e: self.zoom_at(e.x, e.y, 1/1.15))

    def set_image(self, image: Image.Image) -> None:
        self.original_image = image
        self.scale, self.offset_x, self.offset_y = 1.0, 0.0, 0.0
        self.request_render(); self.after_idle(self.fit_to_window)

    def image_to_canvas(self, x, y):
        return self.offset_x + x*self.scale, self.offset_y + y*self.scale

    def canvas_to_image(self, x, y):
        return (x-self.offset_x)/self.scale, (y-self.offset_y)/self.scale

    def inside_image(self, x, y):
        if self.original_image is None: return False
        w, h = self.original_image.size
        return 0 <= x < w and 0 <= y < h

    def fit_to_window(self):
        if self.original_image is None: return
        cw, ch = max(1, self.winfo_width()), max(1, self.winfo_height())
        iw, ih = self.original_image.size
        self.scale = max(self.min_scale, min(self.max_scale, min(cw/iw, ch/ih)))
        self.offset_x = (cw-iw*self.scale)/2
        self.offset_y = (ch-ih*self.scale)/2
        self.request_render(); self._notify_view_changed()

    def zoom_at(self, cx, cy, factor):
        if self.original_image is None: return
        ix, iy = self.canvas_to_image(cx, cy)
        ns = max(self.min_scale, min(self.max_scale, self.scale*factor))
        if math.isclose(ns, self.scale, abs_tol=1e-15): return
        self.scale = ns
        self.offset_x = cx - ix*self.scale
        self.offset_y = cy - iy*self.scale
        self.request_render(); self._notify_view_changed()

    def request_render(self):
        if self._render_pending: return
        self._render_pending = True
        self.after_idle(self._render)

    def _render(self):
        self._render_pending = False
        if self.original_image is None: return
        cw, ch = max(1, self.winfo_width()), max(1, self.winfo_height())
        iw, ih = self.original_image.size
        x0 = max(0, int(math.floor(-self.offset_x/self.scale)))
        y0 = max(0, int(math.floor(-self.offset_y/self.scale)))
        x1 = min(iw, int(math.ceil((cw-self.offset_x)/self.scale)))
        y1 = min(ih, int(math.ceil((ch-self.offset_y)/self.scale)))
        if x1 <= x0 or y1 <= y0:
            if self.image_item is not None: self.itemconfigure(self.image_item, state="hidden")
            return
        crop = self.original_image.crop((x0, y0, x1, y1))
        dw = max(1, int(round((x1-x0)*self.scale)))
        dh = max(1, int(round((y1-y0)*self.scale)))
        if (dw, dh) != crop.size:
            filt = Image.Resampling.LANCZOS if self.scale < 1 else Image.Resampling.BILINEAR
            crop = crop.resize((dw, dh), filt)
        self.tk_image = ImageTk.PhotoImage(crop)
        cx, cy = self.offset_x + x0*self.scale, self.offset_y + y0*self.scale
        if self.image_item is None:
            self.image_item = self.create_image(cx, cy, anchor="nw", image=self.tk_image, tags=("base_image",))
        else:
            self.coords(self.image_item, cx, cy)
            self.itemconfigure(self.image_item, image=self.tk_image, state="normal")
        self.tag_lower("base_image")

    def _on_configure(self, _e): self.request_render(); self._notify_view_changed()
    def _on_motion(self, e):
        if not self.on_cursor: return
        x, y = self.canvas_to_image(e.x, e.y)
        self.on_cursor(x, y) if self.inside_image(x, y) else self.on_cursor(None, None)
    def _on_left_press(self, e):
        if not self.on_left_press: return
        x, y = self.canvas_to_image(e.x, e.y)
        if self.inside_image(x, y): self.on_left_press(x, y)
    def _bounded(self, x, y):
        w, h = self.original_image.size
        return min(max(x, 0), w-1), min(max(y, 0), h-1)
    def _on_left_drag(self, e):
        if self.on_left_drag and self.original_image:
            self.on_left_drag(*self._bounded(*self.canvas_to_image(e.x, e.y)))
    def _on_left_release(self, e):
        if self.on_left_release and self.original_image:
            self.on_left_release(*self._bounded(*self.canvas_to_image(e.x, e.y)))
    def _pan_start(self, e): self._pan_last_x, self._pan_last_y = e.x, e.y
    def _pan_move(self, e):
        self.offset_x += e.x-self._pan_last_x; self.offset_y += e.y-self._pan_last_y
        self._pan_last_x, self._pan_last_y = e.x, e.y
        self.request_render(); self._notify_view_changed()
    def _on_mousewheel(self, e):
        if e.delta: self.zoom_at(e.x, e.y, 1.15 if e.delta > 0 else 1/1.15)
    def _notify_view_changed(self):
        if self.on_view_changed: self.on_view_changed()
