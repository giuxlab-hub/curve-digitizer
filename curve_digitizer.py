# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import csv
import json
import math
import os
import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
from PIL import Image, UnidentifiedImageError

from digitizer_model import AxisConfig, CalibrationError, CORNER_ORDER, DigitizedPoint, Project, Series
from image_canvas import ImageCanvas

APP_NAME = "Curve Digitizer"
SERIES_COLORS = ("#d62728", "#1f77b4", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf", "#e377c2", "#8c564b", "#bcbd22")
CORNER_LABELS = {"bottom_left": "BL", "bottom_right": "BR", "top_left": "TL", "top_right": "TR"}


def fmt(v, digits=10):
    if v is None: return "—"
    return f"{v:.{digits}g}" if math.isfinite(v) else str(v)


def csv_header(name, unit):
    name = re.sub(r"\s+", "_", name.strip())
    unit = re.sub(r"\s+", "_", unit.strip())
    return f"{name}_{unit}" if unit else name


class SeriesDialog(tk.Toplevel):
    def __init__(self, master, series=None):
        super().__init__(master)
        self.title("Edit series" if series else "New series")
        self.transient(master); self.grab_set(); self.resizable(False, False)
        self.result = None
        self.vars = [
            tk.StringVar(value=series.name if series else ""),
            tk.StringVar(value=series.parameter_name if series else "Parameter"),
            tk.StringVar(value=series.parameter_value if series else ""),
            tk.StringVar(value=series.parameter_unit if series else ""),
        ]
        labels = ("Series name", "Parameter name", "Parameter value", "Parameter unit")
        f = ttk.Frame(self, padding=10); f.pack(fill="both", expand=True)
        for r, (label, var) in enumerate(zip(labels, self.vars)):
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", padx=(0,8), pady=3)
            ttk.Entry(f, textvariable=var, width=30).grid(row=r, column=1, sticky="ew", pady=3)
        b = ttk.Frame(f); b.grid(row=4, column=0, columnspan=2, sticky="e", pady=(8,0))
        ttk.Button(b, text="Cancel", command=self.destroy).pack(side="right", padx=(5,0))
        ttk.Button(b, text="OK", command=self.accept).pack(side="right")
        self.bind("<Return>", lambda e: self.accept()); self.bind("<Escape>", lambda e: self.destroy())

    def accept(self):
        name, pname, pvalue, punit = [v.get().strip() for v in self.vars]
        if not name or not pname:
            messagebox.showerror(APP_NAME, "Series name and parameter name are required.", parent=self); return
        self.result = dict(name=name, parameter_name=pname, parameter_value=pvalue, parameter_unit=punit)
        self.destroy()


class ExportDialog(tk.Toplevel):
    def __init__(self, master, project, active):
        super().__init__(master)
        self.title("CSV export"); self.transient(master); self.grab_set(); self.resizable(False, False)
        self.result = None
        vals = [project.x_axis.name, project.x_axis.unit, project.y_axis.name, project.y_axis.unit,
                active.parameter_name if active else "Parameter", active.parameter_unit if active else ""]
        self.vars = [tk.StringVar(value=x) for x in vals]
        labels = ("X name", "X unit", "Y name", "Y unit", "Series parameter name", "Series parameter unit")
        f = ttk.Frame(self, padding=10); f.pack()
        for r, (label, var) in enumerate(zip(labels, self.vars)):
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", padx=(0,8), pady=3)
            ttk.Entry(f, textvariable=var, width=28).grid(row=r, column=1, pady=3)
        ttk.Label(f, text="Units are labels only; no numeric conversion is performed.", wraplength=320).grid(row=6, column=0, columnspan=2, sticky="w", pady=(8,0))
        b = ttk.Frame(f); b.grid(row=7, column=0, columnspan=2, sticky="e", pady=(8,0))
        ttk.Button(b, text="Cancel", command=self.destroy).pack(side="right", padx=(5,0))
        ttk.Button(b, text="Export", command=self.accept).pack(side="right")

    def accept(self):
        xname, xunit, yname, yunit, pname, punit = [v.get().strip() for v in self.vars]
        if not xname or not yname or not pname:
            messagebox.showerror(APP_NAME, "X, Y and parameter names are required.", parent=self); return
        self.result = dict(x_name=xname, x_unit=xunit, y_name=yname, y_unit=yunit, parameter_name=pname, parameter_unit=punit)
        self.destroy()


class App:
    def __init__(self, root):
        self.root = root
        root.title(APP_NAME); root.geometry("1250x800"); root.minsize(900,600)
        self.project = Project(); self.project_path = None
        self.image = None; self.gray_image = None
        self.active_series_id = None; self.selected_point_id = None
        self.pending_corner = None; self.mode = tk.StringVar(value="add")
        self.dirty = False; self.undo_stack = []; self.redo_stack = []
        self.dragging = False; self.drag_snapshot = None
        self.build_menu(); self.build_ui(); self.bind_keys(); self.sync_controls(); self.update_title()
        root.protocol("WM_DELETE_WINDOW", self.close)

    def build_menu(self):
        m = tk.Menu(self.root)
        fm = tk.Menu(m, tearoff=False)
        for label, accel, cmd in [
            ("Open image...","Ctrl+O",self.open_image), ("Open project...","Ctrl+Shift+O",self.open_project),
            ("Save project","Ctrl+S",self.save_project), ("Save project as...","Ctrl+Shift+S",self.save_project_as),
            ("Export CSV...","Ctrl+E",self.export_csv)]:
            fm.add_command(label=label, accelerator=accel, command=cmd)
        fm.add_separator(); fm.add_command(label="Exit", command=self.close); m.add_cascade(label="File", menu=fm)
        em = tk.Menu(m, tearoff=False); em.add_command(label="Undo", accelerator="Ctrl+Z", command=self.undo); em.add_command(label="Redo", accelerator="Ctrl+Y", command=self.redo)
        em.add_separator(); em.add_command(label="Delete selected point", accelerator="Delete", command=self.delete_selected_point); m.add_cascade(label="Edit", menu=em)
        vm = tk.Menu(m, tearoff=False); vm.add_command(label="Fit image to window", accelerator="F", command=lambda:self.canvas.fit_to_window()); m.add_cascade(label="View", menu=vm)
        self.root.config(menu=m)

    def build_ui(self):
        outer = ttk.Frame(self.root); outer.pack(fill="both", expand=True)
        paned = ttk.Panedwindow(outer, orient="horizontal"); paned.pack(fill="both", expand=True)
        cf, sf = ttk.Frame(paned), ttk.Frame(paned, width=370); paned.add(cf, weight=4); paned.add(sf, weight=1)
        self.canvas = ImageCanvas(cf, on_cursor=self.on_cursor, on_left_press=self.canvas_press, on_left_drag=self.canvas_drag, on_left_release=self.canvas_release, on_view_changed=self.redraw)
        self.canvas.pack(fill="both", expand=True)
        nb = ttk.Notebook(sf); nb.pack(fill="both", expand=True, padx=5, pady=5)
        self.cal_tab, self.ser_tab, self.proj_tab = ttk.Frame(nb,padding=8), ttk.Frame(nb,padding=8), ttk.Frame(nb,padding=8)
        nb.add(self.cal_tab,text="Calibration"); nb.add(self.ser_tab,text="Series"); nb.add(self.proj_tab,text="Project")
        self.build_cal_tab(); self.build_series_tab(); self.build_project_tab()
        self.status = tk.StringVar(value="No image loaded."); ttk.Label(outer,textvariable=self.status,relief="sunken",anchor="w").pack(fill="x",side="bottom")

    def build_cal_tab(self):
        self.x_name,self.x_unit,self.x_min,self.x_max,self.x_scale = [tk.StringVar() for _ in range(5)]
        self.y_name,self.y_unit,self.y_min,self.y_max,self.y_scale = [tk.StringVar() for _ in range(5)]
        a = ttk.LabelFrame(self.cal_tab,text="Axes",padding=6); a.pack(fill="x")
        ttk.Label(a,text="").grid(row=0,column=0); ttk.Label(a,text="X").grid(row=0,column=1); ttk.Label(a,text="Y").grid(row=0,column=2)
        for r,(label,xv,yv) in enumerate((("Name",self.x_name,self.y_name),("Unit",self.x_unit,self.y_unit),("Min",self.x_min,self.y_min),("Max",self.x_max,self.y_max)),start=1):
            ttk.Label(a,text=label).grid(row=r,column=0,sticky="w"); ttk.Entry(a,textvariable=xv,width=11).grid(row=r,column=1,padx=2,pady=2); ttk.Entry(a,textvariable=yv,width=11).grid(row=r,column=2,padx=2,pady=2)
        ttk.Label(a,text="Scale").grid(row=5,column=0,sticky="w")
        ttk.Combobox(a,textvariable=self.x_scale,values=("linear","log"),state="readonly",width=9).grid(row=5,column=1)
        ttk.Combobox(a,textvariable=self.y_scale,values=("linear","log"),state="readonly",width=9).grid(row=5,column=2)
        ttk.Button(a,text="Apply axis settings",command=lambda:self.commit_axes(True)).grid(row=6,column=0,columnspan=3,sticky="ew",pady=(5,0))
        c = ttk.LabelFrame(self.cal_tab,text="Four-point calibration",padding=6); c.pack(fill="x",pady=(8,0))
        ttk.Label(c,text="Choose a corner, then click the corresponding graph corner.",wraplength=320).pack(fill="x",pady=(0,5))
        for corner,label in (("bottom_left","1. Capture bottom-left"),("bottom_right","2. Capture bottom-right"),("top_left","3. Capture top-left"),("top_right","4. Capture top-right")):
            ttk.Button(c,text=label,command=lambda q=corner:self.start_corner(q)).pack(fill="x",pady=2)
        ttk.Button(c,text="Clear calibration",command=self.clear_cal).pack(fill="x",pady=(6,2))
        self.cal_status = tk.StringVar(); ttk.Label(c,textvariable=self.cal_status,justify="left",wraplength=320).pack(fill="x",pady=(5,0))
        v = ttk.LabelFrame(self.cal_tab,text="Verify calibration",padding=6); v.pack(fill="x",pady=(8,0))
        self.exp_x,self.exp_y = tk.StringVar(),tk.StringVar(); self.verify_result = tk.StringVar(value="No verification point.")
        ttk.Button(v,text="Verify calibration: click point",command=self.start_verify).grid(row=0,column=0,columnspan=2,sticky="ew",pady=(0,5))
        ttk.Label(v,text="Expected X").grid(row=1,column=0,sticky="w"); ttk.Entry(v,textvariable=self.exp_x,width=14).grid(row=1,column=1)
        ttk.Label(v,text="Expected Y").grid(row=2,column=0,sticky="w"); ttk.Entry(v,textvariable=self.exp_y,width=14).grid(row=2,column=1)
        ttk.Label(v,textvariable=self.verify_result,justify="left",wraplength=320).grid(row=3,column=0,columnspan=2,sticky="w",pady=(5,0))

    def build_series_tab(self):
        self.tree = ttk.Treeview(self.ser_tab,columns=("parameter","value","unit","visible","points"),show="tree headings",height=10)
        for col,text,w in (("#0","Series",110),("parameter","Parameter",65),("value","Value",55),("unit","Unit",45),("visible","Vis",35),("points","Pts",35)):
            self.tree.heading(col,text=text); self.tree.column(col,width=w)
        self.tree.pack(fill="both",expand=True); self.tree.bind("<<TreeviewSelect>>",self.series_selected)
        b = ttk.Frame(self.ser_tab); b.pack(fill="x",pady=(5,0))
        for text,cmd in (("New",self.new_series),("Edit",self.edit_series),("Delete",self.delete_series),("Show / Hide",self.toggle_visible)):
            ttk.Button(b,text=text,command=cmd).pack(side="left",padx=2)
        m = ttk.LabelFrame(self.ser_tab,text="Point mode",padding=6); m.pack(fill="x",pady=(8,0))
        ttk.Radiobutton(m,text="Add points",variable=self.mode,value="add",command=self.mode_changed).pack(anchor="w")
        ttk.Radiobutton(m,text="Edit / move points",variable=self.mode,value="edit",command=self.mode_changed).pack(anchor="w")
        self.show_numbers,self.snap_enabled,self.snap_radius = tk.BooleanVar(),tk.BooleanVar(),tk.IntVar(value=3)
        ttk.Checkbutton(m,text="Show progressive point numbers",variable=self.show_numbers,command=self.display_changed).pack(anchor="w",pady=(5,0))
        s = ttk.LabelFrame(self.ser_tab,text="Optional local snap",padding=6); s.pack(fill="x",pady=(8,0))
        ttk.Checkbutton(s,text="Snap to darkest local pixel",variable=self.snap_enabled,command=self.snap_changed).grid(row=0,column=0,columnspan=2,sticky="w")
        ttk.Label(s,text="Radius [image pixels]").grid(row=1,column=0,sticky="w",pady=(5,0)); sp=ttk.Spinbox(s,from_=0,to=25,width=6,textvariable=self.snap_radius,command=self.snap_changed); sp.grid(row=1,column=1,sticky="w"); sp.bind("<FocusOut>",lambda e:self.snap_changed())
        ttk.Label(s,text="Caution: black graph grids can attract the snap.",wraplength=320).grid(row=2,column=0,columnspan=2,sticky="w",pady=(5,0))
        self.selected_label = tk.StringVar(value="No point selected."); ttk.Label(self.ser_tab,textvariable=self.selected_label,wraplength=320).pack(fill="x",pady=(8,0))

    def build_project_tab(self):
        ttk.Label(self.proj_tab,text="Project notes").pack(anchor="w")
        self.notes = tk.Text(self.proj_tab,wrap="word",height=20); self.notes.pack(fill="both",expand=True,pady=(4,0))
        ttk.Label(self.proj_tab,text="The source image is referenced by path and is never overwritten or modified.",wraplength=320).pack(fill="x",pady=(8,0))

    def bind_keys(self):
        for seq,cmd in (("<Control-o>",self.open_image),("<Control-Shift-o>",self.open_project),("<Control-s>",self.save_project),("<Control-Shift-s>",self.save_project_as),("<Control-e>",self.export_csv),("<Control-z>",self.undo),("<Control-y>",self.redo),("<Delete>",self.delete_selected_point)):
            self.root.bind(seq,lambda e,c=cmd:c())
        self.root.bind("<KeyPress-f>",lambda e:self.canvas.fit_to_window() if not isinstance(e.widget,(tk.Entry,tk.Text,ttk.Entry,ttk.Combobox,ttk.Spinbox)) else None)

    def load_image_file(self,path):
        try:
            with Image.open(path) as src: return src.copy()
        except UnidentifiedImageError as exc: raise ValueError("Unsupported or invalid image.") from exc

    def set_image(self,image):
        self.image=image; self.gray_image=image.convert("L"); self.canvas.set_image(image)

    def open_image(self):
        if not self.maybe_save(): return False
        path=filedialog.askopenfilename(title="Open graph image",filetypes=(("Supported images","*.png *.jpg *.jpeg *.tif *.tiff"),("All files","*")))
        if not path:return False
        try:image=self.load_image_file(path)
        except Exception as exc: messagebox.showerror(APP_NAME,f"Unable to open image:\n{exc}"); return False
        self.project=Project(image_path=os.path.abspath(path),image_width=image.width,image_height=image.height); self.project_path=None
        self.active_series_id=self.selected_point_id=None; self.undo_stack.clear(); self.redo_stack.clear(); self.set_image(image); self.sync_controls(); self.refresh_tree(); self.dirty=False; self.update_title(); return True

    def open_project(self):
        if not self.maybe_save(): return False
        path=filedialog.askopenfilename(title="Open project",filetypes=(("JSON project","*.json"),("All files","*")))
        if not path:return False
        try:
            with open(path,"r",encoding="utf-8") as f:data=json.load(f)
            if data.get("format")!="giux-curve-digitizer-project": raise ValueError("Not a Curve Digitizer project.")
            p=Project.from_dict(data); info=data.get("image",{}); candidates=[]
            if info.get("relative_path"): candidates.append(os.path.abspath(os.path.join(os.path.dirname(path),info["relative_path"])))
            if info.get("path"): candidates.append(info["path"])
            image_path=next((x for x in candidates if os.path.isfile(x)),None)
            if image_path is None:
                image_path=filedialog.askopenfilename(title="Locate project source image",filetypes=(("Supported images","*.png *.jpg *.jpeg *.tif *.tiff"),("All files","*")))
                if not image_path:return False
            image=self.load_image_file(image_path)
        except Exception as exc: messagebox.showerror(APP_NAME,f"Unable to open project:\n{exc}"); return False
        p.image_path=os.path.abspath(image_path); self.project=p; self.project_path=os.path.abspath(path); self.set_image(image)
        self.active_series_id=p.series[0].id if p.series else None; self.selected_point_id=None; self.undo_stack.clear(); self.redo_stack.clear(); p.recalculate_all_points(); self.sync_controls(); self.refresh_tree(); self.dirty=False; self.update_title(); return True

    def save_project(self):
        return self.save_project_as() if not self.project_path else self.save_to(self.project_path)
    def save_project_as(self):
        path=filedialog.asksaveasfilename(title="Save project",defaultextension=".json",filetypes=(("JSON project","*.json"),("All files","*")))
        return False if not path else self.save_to(path)
    def save_to(self,path):
        if self.image is None: messagebox.showerror(APP_NAME,"No image loaded."); return False
        if not self.commit_axes(False): return False
        self.project.notes=self.notes.get("1.0","end-1c"); self.project.show_point_numbers=bool(self.show_numbers.get()); self.project.snap_enabled=bool(self.snap_enabled.get()); self.project.snap_radius=max(0,int(self.snap_radius.get())); self.project.recalculate_all_points()
        d=self.project.to_dict(); img=os.path.abspath(self.project.image_path); d["image"]["path"]=img
        try:d["image"]["relative_path"]=os.path.relpath(img,os.path.dirname(os.path.abspath(path)))
        except ValueError:d["image"]["relative_path"]=None
        try:
            with open(path,"w",encoding="utf-8",newline="\n") as f: json.dump(d,f,indent=2,ensure_ascii=False,allow_nan=False); f.write("\n")
        except Exception as exc: messagebox.showerror(APP_NAME,f"Unable to save project:\n{exc}"); return False
        self.project_path=os.path.abspath(path); self.dirty=False; self.update_title(); return True

    def sync_controls(self):
        for var,val in ((self.x_name,self.project.x_axis.name),(self.x_unit,self.project.x_axis.unit),(self.x_min,fmt(self.project.x_axis.minimum)),(self.x_max,fmt(self.project.x_axis.maximum)),(self.x_scale,self.project.x_axis.scale),(self.y_name,self.project.y_axis.name),(self.y_unit,self.project.y_axis.unit),(self.y_min,fmt(self.project.y_axis.minimum)),(self.y_max,fmt(self.project.y_axis.maximum)),(self.y_scale,self.project.y_axis.scale)):
            var.set(val)
        self.show_numbers.set(self.project.show_point_numbers); self.snap_enabled.set(self.project.snap_enabled); self.snap_radius.set(self.project.snap_radius)
        self.notes.delete("1.0","end"); self.notes.insert("1.0",self.project.notes); self.update_cal_status()

    def commit_axes(self,push):
        try:
            x=AxisConfig(self.x_name.get().strip() or "X",self.x_unit.get().strip(),float(self.x_min.get()),float(self.x_max.get()),self.x_scale.get()); y=AxisConfig(self.y_name.get().strip() or "Y",self.y_unit.get().strip(),float(self.y_min.get()),float(self.y_max.get()),self.y_scale.get()); x.validate(); y.validate()
        except Exception as exc: messagebox.showerror(APP_NAME,f"Invalid axis configuration:\n{exc}"); return False
        changed=x.to_dict()!=self.project.x_axis.to_dict() or y.to_dict()!=self.project.y_axis.to_dict()
        if changed and push:self.push_undo()
        self.project.x_axis,self.project.y_axis=x,y; self.project.recalculate_all_points(); self.update_cal_status(); self.redraw();
        if changed:self.mark_dirty()
        return True

    def start_corner(self,corner):
        if not self.image: messagebox.showerror(APP_NAME,"Open an image first."); return
        self.pending_corner=corner; self.mode.set("calibrate"); self.status.set(f"Calibration mode: click {corner.replace('_','-')}")
    def clear_cal(self):
        if not self.project.calibration.pixels:return
        self.push_undo(); self.project.calibration.clear(); self.project.recalculate_all_points(); self.pending_corner=None; self.mode.set("add"); self.mark_dirty(); self.update_cal_status(); self.redraw()
    def update_cal_status(self):
        lines=[]
        for c in CORNER_ORDER:
            p=self.project.calibration.pixels.get(c); lines.append(f"{CORNER_LABELS[c]}: not set" if p is None else f"{CORNER_LABELS[c]}: {p[0]:.2f}, {p[1]:.2f} px")
        if self.project.calibration.is_complete():
            try:
                _,cond=self.project.calibration.matrix(); lines += ["",f"Corner RMS residual: {self.project.calibration.reprojection_rms():.3e}",f"Matrix condition: {cond:.3e}"]
            except CalibrationError as exc: lines += ["",f"Calibration error: {exc}"]
        self.cal_status.set("\n".join(lines))
    def start_verify(self):
        if not self.project.calibration_ready(): messagebox.showerror(APP_NAME,"Complete calibration first."); return
        self.mode.set("verify"); self.pending_corner=None; self.status.set("Verify calibration: click a known grid point.")

    def refresh_tree(self):
        for i in self.tree.get_children(): self.tree.delete(i)
        for s in self.project.series:self.tree.insert("","end",iid=s.id,text=s.name,values=(s.parameter_name,s.parameter_value,s.parameter_unit,"yes" if s.visible else "no",len(s.points)))
        if self.active_series_id and self.project.find_series(self.active_series_id): self.tree.selection_set(self.active_series_id)
    def active_series(self): return self.project.find_series(self.active_series_id)
    def series_selected(self,_e=None):
        sel=self.tree.selection();
        if sel:self.active_series_id=sel[0]; self.selected_point_id=None; self.update_selected(); self.redraw()
    def new_series(self):
        d=SeriesDialog(self.root); self.root.wait_window(d)
        if not d.result:return
        self.push_undo(); s=Series(**d.result,color=SERIES_COLORS[len(self.project.series)%len(SERIES_COLORS)]); self.project.series.append(s); self.active_series_id=s.id; self.mark_dirty(); self.refresh_tree(); self.redraw()
    def edit_series(self):
        s=self.active_series();
        if not s:return
        d=SeriesDialog(self.root,s); self.root.wait_window(d)
        if not d.result:return
        self.push_undo(); s.name=d.result["name"]; s.parameter_name=d.result["parameter_name"]; s.parameter_value=d.result["parameter_value"]; s.parameter_unit=d.result["parameter_unit"]; self.mark_dirty(); self.refresh_tree(); self.redraw()
    def delete_series(self):
        s=self.active_series();
        if not s or not messagebox.askyesno(APP_NAME,f"Delete series '{s.name}' and its {len(s.points)} points?"):return
        self.push_undo(); self.project.series=[x for x in self.project.series if x.id!=s.id]; self.active_series_id=self.project.series[0].id if self.project.series else None; self.selected_point_id=None; self.mark_dirty(); self.refresh_tree(); self.update_selected(); self.redraw()
    def toggle_visible(self):
        s=self.active_series();
        if not s:return
        self.push_undo(); s.visible=not s.visible; self.mark_dirty(); self.refresh_tree(); self.redraw()

    def canvas_press(self,x,y):
        mode=self.mode.get()
        if mode=="calibrate":
            if self.pending_corner:self.push_undo(); self.project.calibration.set_corner(self.pending_corner,x,y); self.project.recalculate_all_points(); self.pending_corner=None; self.mode.set("add"); self.mark_dirty(); self.update_cal_status(); self.redraw()
        elif mode=="verify": self.verify(x,y)
        elif mode=="add": self.add_point(x,y)
        elif mode=="edit": self.begin_drag(x,y)
    def canvas_drag(self,x,y):
        if not self.dragging:return
        p=self.selected_point();
        if not p:return
        sx,sy=self.snap(x,y); p.manual_pixel_x,p.manual_pixel_y=x,y; p.pixel_x,p.pixel_y=sx,sy; self.project.update_point_calibration(p); self.update_selected(); self.redraw()
    def canvas_release(self,_x,_y):
        if self.dragging and self.drag_snapshot is not None:
            self.undo_stack.append(self.drag_snapshot); self.redo_stack.clear(); self.drag_snapshot=None; self.dragging=False; self.mark_dirty(); self.refresh_tree()
    def verify(self,x,y):
        try:cx,cy=self.project.pixel_to_calibrated(x,y)
        except CalibrationError as exc: messagebox.showerror(APP_NAME,str(exc)); return
        lines=[f"Pixel: {x:.3f}, {y:.3f}",f"Calculated X: {fmt(cx)} {self.project.x_axis.unit}",f"Calculated Y: {fmt(cy)} {self.project.y_axis.unit}"]
        for label,text,val,unit in (("ΔX",self.exp_x.get().strip(),cx,self.project.x_axis.unit),("ΔY",self.exp_y.get().strip(),cy,self.project.y_axis.unit)):
            if text:
                try:lines.append(f"{label}: {fmt(val-float(text))} {unit}")
                except ValueError:lines.append(f"{label}: invalid expected value")
        self.verify_result.set("\n".join(lines))
    def add_point(self,x,y):
        s=self.active_series();
        if not s: messagebox.showinfo(APP_NAME,"Create or select an active series first."); return
        self.push_undo(); sx,sy=self.snap(x,y); p=DigitizedPoint(manual_pixel_x=x,manual_pixel_y=y,pixel_x=sx,pixel_y=sy); self.project.update_point_calibration(p); s.points.append(p); self.selected_point_id=p.id; self.mark_dirty(); self.refresh_tree(); self.update_selected(); self.redraw()
    def begin_drag(self,x,y):
        s=self.active_series();
        if not s:return
        cx,cy=self.canvas.image_to_canvas(x,y); best=None; bd=None
        for p in s.points:
            px,py=self.canvas.image_to_canvas(p.pixel_x,p.pixel_y); d=math.hypot(px-cx,py-cy)
            if d<=10 and (bd is None or d<bd):best,bd=p,d
        self.selected_point_id=best.id if best else None; self.dragging=bool(best); self.drag_snapshot=self.project.to_dict() if best else None; self.update_selected(); self.redraw()
    def selected_point(self):
        s=self.active_series(); return next((p for p in s.points if p.id==self.selected_point_id),None) if s else None
    def delete_selected_point(self):
        s=self.active_series(); p=self.selected_point();
        if not s or not p:return
        self.push_undo(); s.points=[x for x in s.points if x.id!=p.id]; self.selected_point_id=None; self.mark_dirty(); self.refresh_tree(); self.update_selected(); self.redraw()

    def snap(self,x,y):
        if not self.snap_enabled.get() or self.gray_image is None:return x,y
        r=max(0,int(self.snap_radius.get()));
        if r==0:return x,y
        w,h=self.gray_image.size; cx,cy=int(round(x)),int(round(y)); x0,y0=max(0,cx-r),max(0,cy-r); x1,y1=min(w,cx+r+1),min(h,cy+r+1)
        patch=np.asarray(self.gray_image.crop((x0,y0,x1,y1)),dtype=np.uint8); candidates=np.argwhere(patch==patch.min()); best=None; bd=None
        for ly,lx in candidates:
            px,py=x0+int(lx),y0+int(ly); d=(px-x)**2+(py-y)**2
            if bd is None or d<bd:best,bd=(float(px),float(py)),d
        return best or (x,y)

    def redraw(self):
        if not hasattr(self,"canvas"):return
        self.canvas.delete("overlay")
        if not self.image:return
        for c,p in self.project.calibration.pixels.items():
            x,y=self.canvas.image_to_canvas(*p); r=6; self.canvas.create_rectangle(x-r,y-r,x+r,y+r,outline="cyan",width=2,tags=("overlay",)); self.canvas.create_text(x+9,y-9,text=CORNER_LABELS[c],fill="cyan",anchor="sw",tags=("overlay",))
        for s in self.project.series:
            if not s.visible:continue
            for i,p in enumerate(s.points,1):
                x,y=self.canvas.image_to_canvas(p.pixel_x,p.pixel_y); sel=s.id==self.active_series_id and p.id==self.selected_point_id; r=6 if sel else 4; w=3 if sel else 2
                self.canvas.create_oval(x-r,y-r,x+r,y+r,outline=s.color,width=w,tags=("overlay",))
                if self.show_numbers.get(): self.canvas.create_text(x+r+3,y-r-2,text=str(i),fill=s.color,anchor="sw",tags=("overlay",))
    def on_cursor(self,x,y):
        if x is None:self.status.set(f"Mode: {self.mode.get()}"); return
        t=f"Pixel X,Y: {x:.3f}, {y:.3f}"
        if self.project.calibration_ready():
            try:cx,cy=self.project.pixel_to_calibrated(x,y); t+=f"    |    {self.project.x_axis.name}: {fmt(cx)} {self.project.x_axis.unit}    |    {self.project.y_axis.name}: {fmt(cy)} {self.project.y_axis.unit}"
            except CalibrationError:pass
        self.status.set(t+f"    |    Mode: {self.mode.get()}")
    def update_selected(self):
        p=self.selected_point()
        if not p:self.selected_label.set("No point selected."); return
        lines=[f"Manual click: {p.manual_pixel_x:.3f}, {p.manual_pixel_y:.3f} px",f"Stored pixel: {p.pixel_x:.3f}, {p.pixel_y:.3f} px"]
        if p.calibrated_x is not None:lines += [f"X = {fmt(p.calibrated_x)} {self.project.x_axis.unit}",f"Y = {fmt(p.calibrated_y)} {self.project.y_axis.unit}"]
        self.selected_label.set("\n".join(lines))
    def mode_changed(self): self.pending_corner=None; self.selected_point_id=None; self.dragging=False; self.drag_snapshot=None; self.update_selected(); self.redraw()
    def display_changed(self):
        self.push_undo(); self.project.show_point_numbers=bool(self.show_numbers.get()); self.mark_dirty(); self.redraw()
    def snap_changed(self):
        try:r=max(0,int(self.snap_radius.get()))
        except Exception:r=3; self.snap_radius.set(3)
        self.push_undo(); self.project.snap_enabled=bool(self.snap_enabled.get()); self.project.snap_radius=r; self.mark_dirty()

    def push_undo(self): self.undo_stack.append(self.project.to_dict()); self.undo_stack=self.undo_stack[-100:]; self.redo_stack.clear()
    def restore(self,d):
        active=self.active_series_id; self.project=Project.from_dict(d); self.active_series_id=active if self.project.find_series(active) else (self.project.series[0].id if self.project.series else None); self.selected_point_id=None; self.sync_controls(); self.refresh_tree(); self.redraw(); self.mark_dirty()
    def undo(self):
        if not self.undo_stack:return
        cur=self.project.to_dict(); d=self.undo_stack.pop(); self.redo_stack.append(cur); self.restore(d)
    def redo(self):
        if not self.redo_stack:return
        cur=self.project.to_dict(); d=self.redo_stack.pop(); self.undo_stack.append(cur); self.restore(d)

    def export_csv(self):
        if not self.project.calibration_ready(): messagebox.showerror(APP_NAME,"A valid calibration is required before export."); return False
        if not self.project.series: messagebox.showerror(APP_NAME,"There are no series to export."); return False
        self.project.recalculate_all_points(); d=ExportDialog(self.root,self.project,self.active_series()); self.root.wait_window(d)
        if not d.result:return False
        path=filedialog.asksaveasfilename(title="Export CSV",defaultextension=".csv",filetypes=(("CSV","*.csv"),("All files","*")))
        if not path:return False
        r=d.result; headers=(csv_header(r["x_name"],r["x_unit"]),csv_header(r["parameter_name"],r["parameter_unit"]),csv_header(r["y_name"],r["y_unit"]))
        try:
            with open(path,"w",encoding="utf-8",newline="") as f:
                w=csv.writer(f); w.writerow(headers)
                for s in self.project.series:
                    for p in s.points:
                        if p.calibrated_x is not None and p.calibrated_y is not None:w.writerow((fmt(p.calibrated_x,12),s.parameter_value,fmt(p.calibrated_y,12)))
        except Exception as exc: messagebox.showerror(APP_NAME,f"Unable to export CSV:\n{exc}"); return False
        return True

    def mark_dirty(self): self.dirty=True; self.update_title()
    def update_title(self):
        name=os.path.basename(self.project_path or self.project.image_path or "Untitled"); self.root.title(f"{APP_NAME} — {name}{' *' if self.dirty else ''}")
    def maybe_save(self):
        if not self.dirty:return True
        a=messagebox.askyesnocancel(APP_NAME,"Save changes to the current project?")
        if a is None:return False
        return self.save_project() if a else True
    def close(self):
        if self.maybe_save():self.root.destroy()


def main():
    root=tk.Tk(); App(root); root.mainloop()

if __name__ == "__main__": main()
