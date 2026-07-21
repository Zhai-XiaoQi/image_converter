from __future__ import annotations

import os
import queue
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import (
    BooleanVar,
    Button,
    Canvas,
    Checkbutton,
    Entry,
    Frame,
    IntVar,
    Label,
    LabelFrame,
    PanedWindow,
    Radiobutton,
    Scale,
    Scrollbar,
    StringVar,
    Toplevel,
    Tk,
    filedialog,
    messagebox,
)
from tkinter import font as tkfont
from tkinter import ttk

from PIL import Image, ImageDraw, ImageGrab, ImageTk


SUPPORTED_INPUTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
SKIP_DIR_NAMES = {"渐进式JPG", "AI_language_check_contact_sheets", "AI_language_text_check_sheets", "AI_language_category_sheets"}


@dataclass
class ConvertJob:
    source: Path
    target: Path
    selected: bool = True
    tree_id: str = ""
    status: str = "pending"
    message: str = ""


class ImageConverterApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("图片格式转换工具")
        self.default_window_size = (1500, 960)
        self.root.minsize(1180, 760)

        self.input_paths: list[Path] = []
        self.jobs: list[ConvertJob] = []
        self.tree_nodes: dict[str, dict[str, object]] = {}
        self.card_frames: dict[int, Frame] = {}
        self.card_vars: dict[int, BooleanVar] = {}
        self.thumb_cache: dict[tuple[str, int, tuple[int, int]], ImageTk.PhotoImage] = {}
        self.tree_icons: dict[tuple[str, str], ImageTk.PhotoImage] = {}
        self.hover_tree_item: str | None = None
        self.layout_after_id: str | None = None
        self.scan_after_id: str | None = None
        self.preview_after_id: str | None = None
        self.worker: threading.Thread | None = None
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()

        self.mode = StringVar(value="folder")
        self.output_format = StringVar(value="jpg")
        self.quality = IntVar(value=92)
        self.progressive_jpg = BooleanVar(value=False)
        self.preserve_structure = BooleanVar(value=True)
        self.overwrite = BooleanVar(value=False)
        self.delete_originals = BooleanVar(value=False)
        self.alpha_bg = StringVar(value="#ffffff")
        self.search_text = StringVar(value="")
        self.filter_jpg = BooleanVar(value=True)
        self.filter_png = BooleanVar(value=True)
        self.filter_webp = BooleanVar(value=True)
        self.filter_other = BooleanVar(value=True)
        self.single_output_format = StringVar(value="jpg")
        self.single_quality = IntVar(value=92)
        self.single_progressive_jpg = BooleanVar(value=False)
        self.single_alpha_bg = StringVar(value="#ffffff")
        self.single_last_result: Path | None = None
        self.input_text = StringVar(value="")
        self.output_text = StringVar(value="")
        self.status_text = StringVar(value="请选择图片或文件夹。")
        self.status_number_font = ("Microsoft YaHei UI", 9, "bold")

        self._build_ui()
        self._build_tree_icons()
        self._center_root()
        self.root.after(120, self._drain_events)

    def _center_root(self) -> None:
        width, height = self.default_window_size
        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _build_ui(self) -> None:
        style = ttk.Style(self.root)
        module_font = ("Microsoft YaHei UI", 11, "bold")
        style.configure("File.Treeview", font=("Microsoft YaHei UI", 12), rowheight=34)
        style.configure("File.Treeview.Heading", font=module_font)
        style.configure("TNotebook.Tab", font=("Microsoft YaHei UI", 12, "bold"), padding=(18, 8))
        style.map("File.Treeview", background=[("selected", "#dcecff")])

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True)
        main = Frame(self.notebook, padx=12, pady=12)
        self.notebook.add(main, text="批量转换")

        settings_area = Frame(main)
        settings_area.pack(fill="x")
        left_settings = Frame(settings_area)
        left_settings.pack(side="left", fill="both", expand=True, padx=(0, 8))

        top = LabelFrame(left_settings, text="输入", font=module_font)
        top.pack(fill="x")
        mode_row = Frame(top)
        mode_row.pack(fill="x", padx=10, pady=(6, 2))
        Button(mode_row, text="选择文件夹", command=self.choose_folder_input, width=14).pack(side="left")
        Button(mode_row, text="选择文件", command=self.choose_files_input, width=14).pack(side="left", padx=(8, 0))
        Button(mode_row, text="扫描预览", command=self.scan_jobs, width=12).pack(side="left", padx=(8, 0))
        input_row = Frame(top)
        input_row.pack(fill="x", padx=10, pady=(2, 6))
        Entry(input_row, textvariable=self.input_text).pack(side="left", fill="x", expand=True)

        out = LabelFrame(left_settings, text="输出", font=module_font)
        out.pack(fill="x", pady=(6, 0))
        out_row = Frame(out)
        out_row.pack(fill="x", padx=10, pady=6)
        Entry(out_row, textvariable=self.output_text).pack(side="left", fill="x", expand=True)
        Button(out_row, text="选择输出目录", command=self.choose_output, width=14).pack(side="left", padx=(8, 0))
        Button(out_row, text="打开输出目录", command=self.open_output_dir, width=14).pack(side="left", padx=(8, 0))

        opts = LabelFrame(settings_area, text="转换设置", font=module_font)
        opts.pack(side="right", fill="both", padx=(8, 0))
        row1 = Frame(opts)
        row1.pack(fill="x", padx=10, pady=(6, 4))
        Label(row1, text="输出格式").pack(side="left")
        for label, value in [("JPG", "jpg"), ("PNG", "png"), ("WEBP", "webp")]:
            Radiobutton(row1, text=label, variable=self.output_format, value=value, command=self._on_output_format_change).pack(side="left", padx=(10, 0))
        Label(row1, text="质量").pack(side="left", padx=(24, 4))
        ttk.Spinbox(row1, from_=1, to=100, textvariable=self.quality, width=6).pack(side="left")
        self.progressive_check = Checkbutton(row1, text="仅 JPG 渐进式", variable=self.progressive_jpg)
        self.progressive_check.pack(side="left", padx=(18, 0))
        Checkbutton(row1, text="保留目录结构", variable=self.preserve_structure, command=self.scan_jobs).pack(side="left", padx=(18, 0))
        row2 = Frame(opts)
        row2.pack(fill="x", padx=10, pady=(4, 6))
        self.alpha_label = Label(row2, text="转 JPG 时背景色")
        self.alpha_label.pack(side="left")
        self.alpha_entry = Entry(row2, textvariable=self.alpha_bg, width=10)
        self.alpha_entry.pack(side="left", padx=(6, 0))
        Checkbutton(row2, text="覆盖已存在文件", variable=self.overwrite, fg="#9a6400").pack(side="left", padx=(20, 0))
        Checkbutton(row2, text="成功后删除原图", variable=self.delete_originals, fg="#b42318", font=("Microsoft YaHei UI", 9, "bold")).pack(side="left", padx=(20, 0))

        preview = LabelFrame(main, text="预览", font=module_font)
        preview.pack(fill="both", expand=True, pady=(8, 0))
        filter_row = Frame(preview)
        filter_row.pack(fill="x", padx=10, pady=(8, 0))
        Label(filter_row, text="格式").pack(side="left")
        for text, var in [("JPG", self.filter_jpg), ("PNG", self.filter_png), ("WEBP", self.filter_webp), ("其他", self.filter_other)]:
            Checkbutton(filter_row, text=text, variable=var, command=self.scan_jobs).pack(side="left", padx=(8, 0))
        Label(filter_row, text="搜索").pack(side="left", padx=(24, 4))
        search_entry = Entry(filter_row, textvariable=self.search_text, width=34)
        search_entry.pack(side="left")
        Button(filter_row, text="清空", command=self._clear_search, width=8).pack(side="left", padx=(8, 0))
        search_entry.bind("<KeyRelease>", lambda _e: self._schedule_scan())
        panes = PanedWindow(preview, orient="horizontal", sashwidth=6)
        panes.pack(fill="both", expand=True, padx=10, pady=8)

        tree_outer = Frame(panes)
        tree_toolbar = Frame(tree_outer)
        tree_toolbar.pack(fill="x", pady=(0, 6))
        Button(tree_toolbar, text="全选", command=lambda: self.set_all_selected(True), width=8).pack(side="left")
        Button(tree_toolbar, text="全不选", command=lambda: self.set_all_selected(False), width=8).pack(side="left", padx=(8, 0))
        self.tree = ttk.Treeview(tree_outer, show="tree", style="File.Treeview")
        self.tree.column("#0", width=390, stretch=True)
        tree_scroll = Scrollbar(tree_outer, command=self.tree.yview)
        self.tree.config(yscrollcommand=tree_scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Motion>", self._on_tree_motion)
        self.tree.bind("<Leave>", self._on_tree_leave)
        self.tree.tag_configure("hover", background="#eef6ff")
        panes.add(tree_outer, minsize=380)

        grid_outer = Frame(panes)
        self.grid_canvas = Canvas(grid_outer, highlightthickness=0)
        self.grid_inner = Frame(self.grid_canvas)
        grid_scroll = Scrollbar(grid_outer, command=self.grid_canvas.yview)
        self.grid_canvas.config(yscrollcommand=grid_scroll.set)
        self.grid_window = self.grid_canvas.create_window((0, 0), window=self.grid_inner, anchor="nw")
        self.grid_canvas.pack(side="left", fill="both", expand=True)
        grid_scroll.pack(side="right", fill="y")
        self.grid_inner.bind("<Configure>", self._on_grid_configure)
        self.grid_canvas.bind("<Configure>", self._on_canvas_configure)
        self.grid_canvas.bind("<MouseWheel>", self._on_grid_mousewheel)
        self.grid_inner.bind("<MouseWheel>", self._on_grid_mousewheel)
        panes.add(grid_outer, minsize=600)

        bottom = Frame(main)
        bottom.pack(fill="x", pady=(10, 0))
        self.progress = ttk.Progressbar(bottom, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True)
        Button(
            bottom,
            text="开始转换",
            command=self.start_convert,
            width=18,
            bg="#0b5cad",
            fg="white",
            activebackground="#084a8d",
            activeforeground="white",
            font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(side="left", padx=(10, 0), ipady=2)
        self.status_frame = Frame(main)
        self.status_frame.pack(fill="x", pady=(8, 0))
        self._set_status_message("请选择图片或文件夹。")
        for drop_widget in (preview, self.tree, self.grid_canvas):
            self._enable_batch_drop(drop_widget)
        self._build_single_editor_tab(module_font)
        self._on_output_format_change()
        self._bind_shortcuts()

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Return>", self._shortcut_enter)
        self.root.bind("<Escape>", self._shortcut_escape)
        self.root.bind("<Control-s>", self._shortcut_save_single)
        self.root.bind("<Control-S>", self._shortcut_save_single)
        self.root.bind("<Control-v>", self._shortcut_paste_single)
        self.root.bind("<Control-V>", self._shortcut_paste_single)
        self.root.bind("<Key-r>", self._shortcut_reset_single)
        self.root.bind("<Key-R>", self._shortcut_reset_single)

    def _shortcut_enter(self, _event) -> str | None:
        if self.notebook.index("current") == 0:
            self.start_convert()
            return "break"
        return None

    def _shortcut_escape(self, _event) -> str:
        return "break"

    def _set_status_message(self, message: str) -> None:
        self.status_text.set(message)
        if not hasattr(self, "status_frame"):
            return
        for child in self.status_frame.winfo_children():
            child.destroy()
        Label(self.status_frame, text=message, anchor="w").pack(side="left")

    def _set_status_parts(self, parts: list[tuple[str, bool]]) -> None:
        self.status_text.set("".join(text for text, _highlight in parts))
        if not hasattr(self, "status_frame"):
            return
        for child in self.status_frame.winfo_children():
            child.destroy()
        for text, highlight in parts:
            options = {"text": text, "anchor": "w"}
            if highlight:
                options.update({"fg": "#0b5cad", "font": self.status_number_font})
            Label(self.status_frame, **options).pack(side="left")

    def _shortcut_save_single(self, _event) -> str | None:
        if self.notebook.index("current") == 1 and self.single_editor:
            self.single_editor._save_copy_auto()
            return "break"
        return None

    def _shortcut_paste_single(self, _event) -> str | None:
        if self.notebook.index("current") == 1:
            self.load_single_from_clipboard()
            return "break"
        return None

    def _shortcut_reset_single(self, _event) -> str | None:
        if self.notebook.index("current") == 1 and self.single_editor:
            self.single_editor._reset_defaults()
            return "break"
        return None

    def choose_input(self) -> None:
        if self.mode.get() == "files":
            self.choose_files_input()
        else:
            self.choose_folder_input()

    def choose_folder_input(self) -> None:
        folder = filedialog.askdirectory(title="选择要转换的文件夹")
        if folder:
            self.mode.set("folder")
            self.input_paths = [Path(folder)]
            self.input_text.set(folder)
            if not self.output_text.get():
                self.output_text.set(str(Path(folder).with_name(f"{Path(folder).name}_converted_images")))
            self.scan_jobs()

    def choose_files_input(self) -> None:
        files = filedialog.askopenfilenames(
            title="选择图片",
            filetypes=[("Image files", "*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff"), ("All files", "*.*")],
        )
        if files:
            self.mode.set("files")
            self.input_paths = [Path(p) for p in files]
            self.input_text.set(f"已选择 {len(files)} 个文件")
            if not self.output_text.get():
                self.output_text.set(str(self.input_paths[0].parent / "converted_images"))
            self.scan_jobs()

    def _on_output_format_change(self) -> None:
        is_jpg = self.output_format.get() == "jpg"
        if not is_jpg:
            self.progressive_jpg.set(False)
        state = "normal" if is_jpg else "disabled"
        for widget in (self.progressive_check, self.alpha_label, self.alpha_entry):
            widget.config(state=state)
        self.scan_jobs()

    def choose_output(self) -> None:
        folder = filedialog.askdirectory(title="选择输出文件夹")
        if folder:
            self.output_text.set(folder)
            self.scan_jobs()

    def _clear_search(self) -> None:
        self.search_text.set("")
        self.scan_jobs()

    def _schedule_scan(self) -> None:
        if self.scan_after_id:
            self.root.after_cancel(self.scan_after_id)
        self.scan_after_id = self.root.after(220, self.scan_jobs)

    def open_output_dir(self) -> None:
        out = Path(self.output_text.get().strip())
        if not out:
            messagebox.showwarning("没有输出目录", "请先选择输出目录。")
            return
        out.mkdir(parents=True, exist_ok=True)
        os.startfile(out)  # type: ignore[attr-defined]

    def scan_jobs(self) -> None:
        self.jobs.clear()
        self._clear_preview()
        if not self.input_paths:
            self._set_status_message("请选择输入。")
            return
        out_root = Path(self.output_text.get().strip()) if self.output_text.get().strip() else None
        if not out_root:
            self._set_status_message("请选择输出目录。")
            return
        base_root = self._base_root()
        output_ext = "." + self.output_format.get()
        for src in self._collect_sources(out_root):
            if not self._matches_filters(src):
                continue
            if self.preserve_structure.get() and base_root and src.is_relative_to(base_root):
                target = out_root / src.relative_to(base_root).with_suffix(output_ext)
            else:
                target = out_root / src.with_suffix(output_ext).name
            self.jobs.append(ConvertJob(src, target))
        self._populate_tree()
        self._populate_grid()
        self._update_selected_status()
        self.progress.config(value=0, maximum=max(1, len(self.jobs)))

    def _matches_filters(self, src: Path) -> bool:
        ext = src.suffix.lower()
        ext_ok = (
            (ext in {".jpg", ".jpeg"} and self.filter_jpg.get())
            or (ext == ".png" and self.filter_png.get())
            or (ext == ".webp" and self.filter_webp.get())
            or (ext not in {".jpg", ".jpeg", ".png", ".webp"} and self.filter_other.get())
        )
        if not ext_ok:
            return False
        query = self.search_text.get().strip().lower()
        if not query:
            return True
        rel = str(self._display_source_rel(src)).lower()
        return query in rel or query in src.name.lower()

    def _collect_sources(self, out_root: Path) -> list[Path]:
        sources: list[Path] = []
        out_resolved = out_root.resolve()
        for path in self.input_paths:
            if path.is_dir():
                for item in path.rglob("*"):
                    if item.is_dir():
                        continue
                    if any(part in SKIP_DIR_NAMES for part in item.parts):
                        continue
                    try:
                        if item.resolve().is_relative_to(out_resolved):
                            continue
                    except OSError:
                        pass
                    if self._is_supported_input(item):
                        sources.append(item)
            elif self._is_supported_input(path):
                sources.append(path)
        return sorted(set(sources), key=lambda p: str(p).lower())

    def _base_root(self) -> Path | None:
        folders = [p for p in self.input_paths if p.is_dir()]
        if len(folders) == 1:
            return folders[0]
        if self.input_paths:
            return self.input_paths[0].parent
        return None

    def _display_base_root(self) -> Path | None:
        folders = [p for p in self.input_paths if p.is_dir()]
        if len(folders) == 1:
            return folders[0].parent
        if self.input_paths:
            return self.input_paths[0].parent
        return None

    @staticmethod
    def _is_supported_input(path: Path) -> bool:
        return path.is_file() and path.suffix.lower() in SUPPORTED_INPUTS

    def _clear_preview(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._clear_grid()
        self.tree_nodes.clear()

    def _build_tree_icons(self) -> None:
        colors = {
            "checked": ("#1976d2", "#ffffff"),
            "unchecked": ("#ffffff", "#555555"),
            "partial": ("#1976d2", "#ffffff"),
        }
        for kind in ("folder", "file"):
            for state, (fill, mark_color) in colors.items():
                img = Image.new("RGBA", (44, 26), (0, 0, 0, 0))
                draw = ImageDraw.Draw(img)
                draw.rounded_rectangle((1, 4, 20, 23), radius=2, fill=fill, outline="#555555", width=1)
                if state == "checked":
                    draw.line((5, 14, 9, 18, 17, 8), fill=mark_color, width=3)
                elif state == "partial":
                    draw.rectangle((6, 13, 16, 16), fill=mark_color)
                if kind == "folder":
                    draw.rectangle((25, 9, 42, 22), fill="#f2c14e", outline="#9b771f")
                    draw.rectangle((23, 7, 34, 13), fill="#f2c14e", outline="#9b771f")
                else:
                    draw.rectangle((25, 4, 42, 23), fill="#f7fbff", outline="#5c85b1")
                    draw.rectangle((28, 16, 33, 20), fill="#71a85f")
                    draw.polygon([(34, 20), (39, 12), (42, 20)], fill="#5d8ec1")
                self.tree_icons[(kind, state)] = ImageTk.PhotoImage(img)

    def _display_source_rel(self, source: Path) -> Path:
        base_root = self._display_base_root()
        if base_root and source.is_relative_to(base_root):
            return source.relative_to(base_root)
        return Path(source.name)

    def _populate_tree(self) -> None:
        node_map: dict[Path, str] = {}
        for idx, job in enumerate(self.jobs):
            rel = self._display_source_rel(job.source)
            parent_id = ""
            cumulative = Path()
            for part in rel.parts[:-1]:
                cumulative = cumulative / part
                if cumulative not in node_map:
                    node_id = self.tree.insert(parent_id, "end", text=part, image=self.tree_icons[("folder", "checked")], open=True)
                    node_map[cumulative] = node_id
                    self.tree_nodes[node_id] = {"kind": "folder", "name": part}
                parent_id = node_map[cumulative]
            job.tree_id = self.tree.insert(parent_id, "end", text=rel.name, image=self.tree_icons[("file", "checked")])
            self.tree_nodes[job.tree_id] = {"kind": "file", "job_index": idx, "name": rel.name}
        self._refresh_folder_states()

    def _populate_grid(self) -> None:
        self._clear_grid()
        for idx, job in enumerate(self.jobs):
            if job.selected:
                self._create_card(idx, job)
        self.root.update_idletasks()
        self._layout_cards(reset_scroll=True)

    def _clear_grid(self) -> None:
        for child in self.grid_inner.winfo_children():
            child.destroy()
        self.card_frames.clear()
        self.card_vars.clear()
        self.grid_canvas.yview_moveto(0)
        self.grid_canvas.xview_moveto(0)
        self.grid_canvas.configure(scrollregion=(0, 0, 0, 0))

    def _create_card(self, idx: int, job: ConvertJob) -> None:
        var = BooleanVar(value=job.selected)
        self.card_vars[idx] = var
        card = Frame(self.grid_inner, bd=1, relief="solid", padx=8, pady=8, bg="#f5f5f5")
        self.card_frames[idx] = card
        top = Frame(card, bg="#f5f5f5")
        top.pack(fill="x")
        Checkbutton(top, variable=var, command=lambda i=idx: self._set_job_selected(i, self.card_vars[i].get()), bg="#f5f5f5", activebackground="#eaf3ff").pack(side="left")
        Button(top, text="编辑", command=lambda i=idx: self.load_single_image(self.jobs[i].source), width=6).pack(side="right")
        thumb = self._get_thumbnail(job.source, (176, 126))
        image_label = Label(card, image=thumb, width=184, height=132, bg="#f7f7f4")
        image_label.image = thumb  # type: ignore[attr-defined]
        image_label.pack(fill="x", pady=(4, 0))
        rel = self._display_source_rel(job.source)
        name_label = Label(card, text=rel.name, width=25, anchor="center", bg="#f5f5f5")
        name_label.pack(pady=(4, 0))
        parent = str(rel.parent) if str(rel.parent) != "." else "(根目录)"
        parent_label = Label(card, text=parent, width=25, anchor="center", fg="#666", bg="#f5f5f5")
        parent_label.pack()
        card.bind("<Button-1>", lambda _e, i=idx: self._schedule_card_preview(i))
        self._bind_card_hover(card)
        for clickable in (image_label, name_label, parent_label):
            clickable.bind("<Button-1>", lambda _e, i=idx: self._schedule_card_preview(i))
        image_label.bind("<Double-Button-1>", lambda _e, i=idx: self._open_card_editor(i))
        for widget in [card, top, image_label, *card.winfo_children()]:
            widget.bind("<MouseWheel>", self._on_grid_mousewheel, add="+")

    def _bind_card_hover(self, card: Frame) -> None:
        def apply_bg(widget, color: str) -> None:
            try:
                if not isinstance(widget, Button):
                    widget.configure(bg=color)
            except Exception:
                pass
            for child in widget.winfo_children():
                apply_bg(child, color)

        def pointer_inside() -> bool:
            x = card.winfo_pointerx()
            y = card.winfo_pointery()
            left = card.winfo_rootx()
            top = card.winfo_rooty()
            return left <= x <= left + card.winfo_width() and top <= y <= top + card.winfo_height()

        def enter(_event=None) -> None:
            card.configure(bg="#eaf3ff")
            apply_bg(card, "#eaf3ff")

        def leave(_event=None) -> None:
            def reset_if_outside() -> None:
                if pointer_inside():
                    return
                card.configure(bg="#f5f5f5")
                apply_bg(card, "#f5f5f5")

            card.after(60, reset_if_outside)

        for widget in [card, *card.winfo_children()]:
            widget.bind("<Enter>", enter, add="+")
            widget.bind("<Leave>", leave, add="+")

    def _schedule_card_preview(self, job_index: int) -> str:
        self._select_job_in_tree(job_index)
        if self.preview_after_id:
            self.root.after_cancel(self.preview_after_id)
        self.preview_after_id = self.root.after(180, lambda i=job_index: self.open_large_preview(i))
        return "break"

    def _open_card_editor(self, job_index: int) -> str:
        if self.preview_after_id:
            self.root.after_cancel(self.preview_after_id)
            self.preview_after_id = None
        if 0 <= job_index < len(self.jobs):
            self.load_single_image(self.jobs[job_index].source)
        return "break"

    def _get_thumbnail(self, path: Path, size: tuple[int, int]) -> ImageTk.PhotoImage:
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            mtime = 0
        key = (str(path), mtime, size)
        cached = self.thumb_cache.get(key)
        if cached:
            return cached
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail(size, Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", size, (247, 247, 244))
            canvas.paste(im, ((size[0] - im.width) // 2, (size[1] - im.height) // 2))
        photo = ImageTk.PhotoImage(canvas)
        self.thumb_cache[key] = photo
        if len(self.thumb_cache) > 800:
            for old_key in list(self.thumb_cache.keys())[:200]:
                self.thumb_cache.pop(old_key, None)
        return photo

    def _schedule_layout(self) -> None:
        if self.layout_after_id:
            self.root.after_cancel(self.layout_after_id)
        self.layout_after_id = self.root.after(80, self._layout_cards)

    def _layout_cards(self, reset_scroll: bool = False) -> None:
        self.layout_after_id = None
        width = max(360, self.grid_canvas.winfo_width(), self.grid_canvas.winfo_reqwidth())
        card_width = 320
        columns = max(1, width // card_width)
        actual_width = max(280, width // columns)
        for column in range(max(columns, 12)):
            self.grid_inner.grid_columnconfigure(column, weight=1 if column < columns else 0, minsize=actual_width if column < columns else 0)
        for visible_idx, card in enumerate(self.card_frames.values()):
            card.grid_forget()
            card.grid(row=visible_idx // columns, column=visible_idx % columns, padx=0, pady=0, sticky="nsew")
        self.grid_inner.update_idletasks()
        self.grid_canvas.configure(scrollregion=self.grid_canvas.bbox("all"))
        if reset_scroll:
            self.grid_canvas.yview_moveto(0)

    @staticmethod
    def _folder_text(name: str, state: str) -> str:
        return name

    @staticmethod
    def _file_text(name: str, selected: bool) -> str:
        return name

    @staticmethod
    def _node_clean_name(text: str) -> str:
        return text

    def _on_tree_click(self, event) -> str | None:
        item = self.tree.identify_row(event.y)
        if not item:
            return None
        node = self.tree_nodes.get(item)
        if not node:
            return None
        if node["kind"] == "file":
            idx = int(node["job_index"])
            self._set_job_selected(idx, not self.jobs[idx].selected)
        else:
            self._set_folder_selected(item, not self._folder_all_selected(item))
        return "break"

    def _on_tree_select(self, _event) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        node = self.tree_nodes.get(selected[0])
        if node and node["kind"] == "file":
            card = self.card_frames.get(int(node["job_index"]))
            if card:
                self.grid_canvas.yview_moveto(max(0, card.winfo_y() / max(1, self.grid_inner.winfo_height())))

    def _on_tree_motion(self, event) -> None:
        item = self.tree.identify_row(event.y)
        if item == self.hover_tree_item:
            return
        if self.hover_tree_item and self.tree.exists(self.hover_tree_item):
            tags = tuple(tag for tag in self.tree.item(self.hover_tree_item, "tags") if tag != "hover")
            self.tree.item(self.hover_tree_item, tags=tags)
        self.hover_tree_item = item or None
        if item:
            tags = tuple(set(self.tree.item(item, "tags")) | {"hover"})
            self.tree.item(item, tags=tags)

    def _on_tree_leave(self, _event) -> None:
        if self.hover_tree_item and self.tree.exists(self.hover_tree_item):
            tags = tuple(tag for tag in self.tree.item(self.hover_tree_item, "tags") if tag != "hover")
            self.tree.item(self.hover_tree_item, tags=tags)
        self.hover_tree_item = None

    def _select_job_in_tree(self, idx: int) -> None:
        tree_id = self.jobs[idx].tree_id
        if tree_id:
            self.tree.selection_set(tree_id)
            self.tree.see(tree_id)

    def _set_job_selected(self, idx: int, selected: bool, refresh: bool = True) -> None:
        job = self.jobs[idx]
        job.selected = selected
        if idx in self.card_vars:
            self.card_vars[idx].set(selected)
        if job.tree_id:
            self.tree.item(job.tree_id, image=self.tree_icons[("file", "checked" if selected else "unchecked")])
        if refresh:
            self._refresh_all_selection_views()

    def _set_folder_selected(self, item: str, selected: bool, refresh: bool = True) -> None:
        for child in self.tree.get_children(item):
            node = self.tree_nodes.get(child)
            if not node:
                continue
            if node["kind"] == "file":
                self._set_job_selected(int(node["job_index"]), selected, refresh=False)
            else:
                self._set_folder_selected(child, selected, refresh=False)
        if refresh:
            self._refresh_all_selection_views()

    def set_all_selected(self, selected: bool) -> None:
        for idx in range(len(self.jobs)):
            self._set_job_selected(idx, selected, refresh=False)
        self._refresh_all_selection_views()

    def _refresh_all_selection_views(self) -> None:
        self._refresh_folder_states()
        self._populate_grid()
        self._update_selected_status()

    def _refresh_folder_states(self) -> None:
        def walk(item: str) -> str:
            node = self.tree_nodes.get(item)
            if node and node["kind"] == "file":
                return "checked" if self.jobs[int(node["job_index"])].selected else "unchecked"
            child_states = [walk(child) for child in self.tree.get_children(item)]
            if child_states and all(s == "checked" for s in child_states):
                state = "checked"
            elif any(s != "unchecked" for s in child_states):
                state = "partial"
            else:
                state = "unchecked"
            self.tree.item(item, image=self.tree_icons[("folder", state)])
            return state
        for root_item in self.tree.get_children(""):
            walk(root_item)

    def _folder_all_selected(self, item: str) -> bool:
        states: list[bool] = []
        for child in self.tree.get_children(item):
            node = self.tree_nodes.get(child)
            if node and node["kind"] == "file":
                states.append(self.jobs[int(node["job_index"])].selected)
            else:
                states.append(self._folder_all_selected(child))
        return bool(states) and all(states)

    def _update_selected_status(self) -> None:
        selected = sum(1 for job in self.jobs if job.selected)
        self._set_status_parts([
            ("已扫描 ", False),
            (str(len(self.jobs)), True),
            (" 张图片，已选择 ", False),
            (str(selected), True),
            (" 张。", False),
        ])

    def _on_grid_configure(self, _event) -> None:
        self.grid_canvas.configure(scrollregion=self.grid_canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        self.grid_canvas.itemconfigure(self.grid_window, width=event.width)
        self._schedule_layout()

    def _on_grid_mousewheel(self, event) -> str:
        step = -1 if event.delta > 0 else 1
        self.grid_canvas.yview_scroll(step * 3, "units")
        return "break"

    def start_convert(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("正在转换", "转换任务正在运行。")
            return
        selected_jobs = [job for job in self.jobs if job.selected]
        if not selected_jobs:
            messagebox.showwarning("没有选中图片", "请至少勾选一张图片。")
            return
        if self.delete_originals.get():
            ok = messagebox.askyesno("确认删除原图", "转换成功后会删除原图。请确认你已经备份或确实不再需要原图。")
            if not ok:
                return
        self.progress.config(value=0, maximum=len(selected_jobs))
        self._set_status_message("开始转换...")
        self.worker = threading.Thread(target=self._convert_worker, args=(selected_jobs,), daemon=True)
        self.worker.start()

    def _convert_worker(self, selected_jobs: list[ConvertJob]) -> None:
        ok = failed = skipped = 0
        unselected = len(self.jobs) - len(selected_jobs)
        failures: list[str] = []
        report = [
            f"Image conversion report: {datetime.now():%Y-%m-%d %H:%M:%S}",
            f"Output format: {self.output_format.get()}",
            f"Total: {len(self.jobs)}",
            f"Selected: {len(selected_jobs)}",
            f"Unselected: {unselected}",
            "",
        ]
        for index, job in enumerate(selected_jobs, start=1):
            try:
                if job.target.exists() and not self.overwrite.get():
                    skipped += 1
                    report.append(f"[SKIP] {job.source} -> {job.target} (target exists)")
                else:
                    self._convert_one(job.source, job.target)
                    if self.delete_originals.get() and job.source.resolve() != job.target.resolve():
                        job.source.unlink()
                    ok += 1
                    report.append(f"[OK] {job.source} -> {job.target}")
            except Exception as exc:  # noqa: BLE001
                failed += 1
                message = f"{job.source} -> {job.target} ({exc})"
                failures.append(message)
                report.append(f"[FAIL] {message}")
            self.events.put(("progress", (index, len(selected_jobs), ok, failed, skipped)))
        report_path = Path(self.output_text.get().strip()) / "conversion_report.txt"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("\n".join(report), encoding="utf-8")
        self.events.put(("done", (ok, failed, skipped, unselected, report_path, failures)))

    def _convert_one(self, source: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        out_format = self.output_format.get()
        bg = self._parse_color(self.alpha_bg.get())
        with Image.open(source) as im:
            if out_format == "jpg":
                im = self._flatten_alpha(im, bg)
            elif out_format == "webp":
                im = im.convert("RGBA") if im.mode in {"RGBA", "LA", "P"} else im.convert("RGB")
            elif out_format == "png":
                im = im.convert("RGBA") if im.mode in {"RGBA", "LA", "P"} else im.convert("RGB")
            if out_format == "jpg":
                im.save(target, format="JPEG", quality=int(self.quality.get()), optimize=True, progressive=bool(self.progressive_jpg.get()))
            elif out_format == "webp":
                im.save(target, format="WEBP", quality=int(self.quality.get()), method=6)
            elif out_format == "png":
                im.save(target, format="PNG", optimize=True)
            else:
                raise ValueError(f"Unsupported output format: {out_format}")

    @staticmethod
    def _flatten_alpha(im: Image.Image, bg: tuple[int, int, int]) -> Image.Image:
        if im.mode in {"RGBA", "LA"} or (im.mode == "P" and "transparency" in im.info):
            rgba = im.convert("RGBA")
            canvas = Image.new("RGBA", rgba.size, bg + (255,))
            canvas.alpha_composite(rgba)
            return canvas.convert("RGB")
        return im.convert("RGB")

    @staticmethod
    def _parse_color(value: str) -> tuple[int, int, int]:
        value = value.strip()
        if re.match(r"^#[0-9a-fA-F]{6}$", value):
            return tuple(int(value[i : i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]
        if value.lower() in {"white", "ffffff"}:
            return (255, 255, 255)
        if value.lower() in {"black", "000000"}:
            return (0, 0, 0)
        raise ValueError("背景填充色请使用 #ffffff 这种格式")

    def open_editor(self, job_index: int) -> None:
        if 0 <= job_index < len(self.jobs):
            ImageEditorWindow(self, self.jobs[job_index].source)

    def open_large_preview(self, job_index: int) -> None:
        if not (0 <= job_index < len(self.jobs)):
            return
        source = self.jobs[job_index].source
        try:
            with Image.open(source) as im:
                im = im.convert("RGB")
                im.thumbnail((1100, 760), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(im)
        except Exception as exc:
            messagebox.showerror("无法预览", f"图片读取失败：\n{source}\n\n{exc}")
            return
        win = Toplevel(self.root)
        win.title(f"大图预览 - {source.name}")
        width, height = 1160, 840
        win.update_idletasks()
        screen_w = win.winfo_screenwidth()
        screen_h = win.winfo_screenheight()
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)
        win.geometry(f"{width}x{height}+{x}+{y}")
        Label(win, image=photo, bg="#222").pack(fill="both", expand=True, padx=12, pady=12)
        Label(win, text=str(source), anchor="w").pack(fill="x", padx=12, pady=(0, 12))
        win.image_ref = photo  # type: ignore[attr-defined]

    def _build_single_editor_tab(self, module_font) -> None:
        page = Frame(self.notebook, padx=12, pady=12)
        self.notebook.add(page, text="单图处理")
        top_area = Frame(page)
        top_area.pack(fill="x")
        top = LabelFrame(top_area, text="单图输入", font=module_font)
        top.pack(side="left", fill="both", expand=True, padx=(0, 8))
        row = Frame(top)
        row.pack(fill="x", padx=10, pady=6)
        self.single_image_text = StringVar(value="未选择图片")
        Button(row, text="选择图片", command=self.choose_single_image, width=12).pack(side="left")
        Button(row, text="粘贴路径/图片", command=self.load_single_from_clipboard, width=14).pack(side="left", padx=(8, 0))
        Label(row, textvariable=self.single_image_text, anchor="w").pack(side="left", fill="x", expand=True, padx=(10, 0))

        single_opts = LabelFrame(top_area, text="单图转换", font=module_font)
        single_opts.pack(side="right", fill="both", padx=(8, 0))
        opt_row = Frame(single_opts)
        opt_row.pack(fill="x", padx=10, pady=(6, 3))
        Label(opt_row, text="格式").pack(side="left")
        for label, value in [("JPG", "jpg"), ("PNG", "png"), ("WEBP", "webp")]:
            Radiobutton(opt_row, text=label, variable=self.single_output_format, value=value, command=self._on_single_output_format_change).pack(side="left", padx=(8, 0))
        Label(opt_row, text="质量").pack(side="left", padx=(18, 4))
        ttk.Spinbox(opt_row, from_=1, to=100, textvariable=self.single_quality, width=5).pack(side="left")
        self.single_progressive_check = Checkbutton(opt_row, text="仅 JPG 渐进式", variable=self.single_progressive_jpg)
        self.single_progressive_check.pack(side="left", padx=(12, 0))
        opt_row2 = Frame(single_opts)
        opt_row2.pack(fill="x", padx=10, pady=(3, 6))
        self.single_alpha_label = Label(opt_row2, text="转 JPG 时背景色")
        self.single_alpha_label.pack(side="left")
        self.single_alpha_entry = Entry(opt_row2, textvariable=self.single_alpha_bg, width=10)
        self.single_alpha_entry.pack(side="left", padx=(6, 12))

        self.single_editor_host = Frame(page)
        self.single_editor_host.pack(fill="both", expand=True, pady=(10, 0))
        self.single_editor = None
        self._show_empty_single_canvas()
        self._enable_file_drop(self.single_editor_host, self.load_single_image)
        self._on_single_output_format_change()

    def _show_empty_single_canvas(self) -> None:
        for child in self.single_editor_host.winfo_children():
            child.destroy()
        empty = Canvas(self.single_editor_host, bg="#222", highlightthickness=0)
        empty.pack(fill="both", expand=True)
        empty.create_text(760, 360, text="选择图片、粘贴路径，或将图片文件拖到这里", fill="#bbbbbb", font=("Microsoft YaHei UI", 16))
        self._enable_file_drop(empty, self.load_single_image)

    def choose_single_image(self) -> None:
        file_path = filedialog.askopenfilename(
            title="选择单张图片",
            filetypes=[("Image files", "*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff"), ("All files", "*.*")],
        )
        if file_path:
            self.load_single_image(Path(file_path))

    def load_single_from_clipboard(self) -> None:
        try:
            image = ImageGrab.grabclipboard()
        except Exception:
            image = None
        if isinstance(image, Image.Image):
            clip_dir = Path(os.environ.get("TEMP", "."))
            path = clip_dir / f"image_converter_clipboard_{datetime.now():%Y%m%d_%H%M%S}.png"
            image.save(path, format="PNG")
            self.load_single_image(path)
            return
        try:
            value = self.root.clipboard_get().strip().strip('"')
        except Exception:
            messagebox.showwarning("没有可读取内容", "剪贴板里没有图片，也没有可读取的图片路径。")
            return
        path = Path(value)
        if path.is_file() and self._is_supported_input(path):
            self.load_single_image(path)
        else:
            messagebox.showwarning("路径不可用", "剪贴板内容不是可支持的图片文件路径。")

    def _on_single_output_format_change(self) -> None:
        is_jpg = self.single_output_format.get() == "jpg"
        if not is_jpg:
            self.single_progressive_jpg.set(False)
        state = "normal" if is_jpg else "disabled"
        for widget in (self.single_progressive_check, self.single_alpha_label, self.single_alpha_entry):
            widget.config(state=state)

    def _enable_file_drop(self, widget, callback) -> None:
        try:
            self.root.tk.call("package", "require", "tkdnd")
            self.root.tk.call("tkdnd::drop_target", "register", widget._w, "DND_Files")
            command = widget.register(lambda data: callback(Path(str(data).strip("{}").strip())))
            self.root.tk.call("bind", widget._w, "<<Drop:DND_Files>>", f"{command} %D")
        except Exception:
            widget.bind("<Control-v>", lambda _e: self.load_single_from_clipboard(), add="+")

    def _enable_batch_drop(self, widget) -> None:
        try:
            self.root.tk.call("package", "require", "tkdnd")
            self.root.tk.call("tkdnd::drop_target", "register", widget._w, "DND_Files")
            command = widget.register(lambda data: self.load_batch_drop_path(Path(str(data).strip("{}").strip())))
            self.root.tk.call("bind", widget._w, "<<Drop:DND_Files>>", f"{command} %D")
        except Exception:
            return

    def load_batch_drop_path(self, path: Path) -> None:
        if path.is_dir():
            self.mode.set("folder")
            self.input_paths = [path]
            self.input_text.set(str(path))
            if not self.output_text.get():
                self.output_text.set(str(path.with_name(f"{path.name}_converted_images")))
            self.scan_jobs()
        elif path.is_file() and self._is_supported_input(path):
            self.mode.set("files")
            self.input_paths = [path]
            self.input_text.set(str(path))
            if not self.output_text.get():
                self.output_text.set(str(path.parent / "converted_images"))
            self.scan_jobs()

    def load_single_image(self, path: Path) -> None:
        for child in self.single_editor_host.winfo_children():
            child.destroy()
        self.single_image_text.set(str(path))
        self.single_last_result = None
        self.single_editor = EmbeddedImageEditor(self, self.single_editor_host, path)
        self.notebook.select(1)

    def save_single_converted(self) -> None:
        if not self.single_editor:
            messagebox.showwarning("未选择图片", "请先选择一张图片。")
            return
        path = self.single_editor.save_converted_copy(
            self.single_output_format.get(),
            int(self.single_quality.get()),
            bool(self.single_progressive_jpg.get()),
            self._parse_color(self.single_alpha_bg.get()),
        )
        self.single_last_result = path
        messagebox.showinfo("已保存", f"转换副本已保存：\n{path}")

    def open_single_result_dir(self) -> None:
        target: Path | None = self.single_last_result
        if target is None and self.single_editor:
            target = self.single_editor.source
        if target is None:
            messagebox.showwarning("没有结果", "请先选择图片或保存转换副本。")
            return
        folder = target.parent if target.is_file() else target
        os.startfile(folder)  # type: ignore[attr-defined]

    def refresh_after_edit(self) -> None:
        self.thumb_cache.clear()
        self.scan_jobs()

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "progress":
                    index, total, ok, failed, skipped = payload  # type: ignore[misc]
                    self.progress.config(value=index)
                    self._set_status_parts([
                        ("处理中 ", False), (f"{index}/{total}", True),
                        ("，成功 ", False), (str(ok), True),
                        ("，失败 ", False), (str(failed), True),
                        ("，跳过 ", False), (str(skipped), True),
                    ])
                elif kind == "done":
                    ok, failed, skipped, unselected, report_path, failures = payload  # type: ignore[misc]
                    self._set_status_parts([
                        ("完成：成功 ", False), (str(ok), True),
                        ("，失败 ", False), (str(failed), True),
                        ("，跳过 ", False), (str(skipped), True),
                        ("，未选 ", False), (str(unselected), True),
                        (f"。报告：{report_path}", False),
                    ])
                    summary = f"成功 {ok}\n失败 {failed}\n跳过 {skipped}\n未选 {unselected}\n\n报告：{report_path}"
                    if failures:
                        shown = "\n".join(str(item) for item in failures[:8])
                        more = "" if len(failures) <= 8 else f"\n... 还有 {len(failures) - 8} 条，详见报告。"
                        messagebox.showwarning("转换完成：存在失败项", f"{summary}\n\n失败列表：\n{shown}{more}")
                    else:
                        messagebox.showinfo("转换完成", summary)
        except queue.Empty:
            pass
        self.root.after(120, self._drain_events)


class ImageEditorWindow:
    HANDLE = 10
    SNAP = 12

    def __init__(self, app: ImageConverterApp, source: Path) -> None:
        self.app = app
        self.source = source
        self.original = Image.open(source).convert("RGBA")
        self.win = Toplevel(app.root)
        self.win.title(f"编辑图片 - {source.name}")
        self.win.geometry("1000x740")
        self._center_window(1000, 740)

        self.width_var = IntVar(value=self.original.width)
        self.height_var = IntVar(value=self.original.height)
        self.crop_size_text = StringVar(value=f"当前裁剪：{self.original.width} x {self.original.height}")
        self.keep_ratio = BooleanVar(value=True)
        self.preview_ref: ImageTk.PhotoImage | None = None
        self.preview_size = (1, 1)
        self.canvas_size = (1, 1)
        self.scale = 1.0
        self.rotation = 0
        self.image_offset = [0, 0]
        self.output_box = [0, 0, self.original.width, self.original.height]
        self.drag_mode: str | None = None
        self.drag_start: tuple[int, int] | None = None
        self.start_box: list[int] | None = None
        self.start_offset: list[int] | None = None
        self.resize_after_id: str | None = None
        self.undo_stack: list[dict[str, object]] = []
        self.redo_stack: list[dict[str, object]] = []
        self.last_saved_path: Path | None = None
        self.align_icons: dict[str, ImageTk.PhotoImage] = {}

        self._build_ui()
        self.win.after(80, self._reset_view)

    def _center_window(self, width: int, height: int) -> None:
        self.win.update_idletasks()
        screen_w = self.win.winfo_screenwidth()
        screen_h = self.win.winfo_screenheight()
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)
        self.win.geometry(f"{width}x{height}+{x}+{y}")

    def _build_ui(self) -> None:
        top = Frame(self.win, padx=10, pady=8)
        top.pack(fill="x")
        Label(top, text=f"原始尺寸：{self.original.width} x {self.original.height}").pack(side="left")
        Label(top, textvariable=self.crop_size_text, fg="#0b5cad", font=("Microsoft YaHei UI", 9, "bold")).pack(side="left", padx=(18, 0))
        Label(top, text="宽").pack(side="left", padx=(20, 4))
        width_entry = Entry(top, textvariable=self.width_var, width=8)
        width_entry.pack(side="left")
        Label(top, text="高").pack(side="left", padx=(10, 4))
        height_entry = Entry(top, textvariable=self.height_var, width=8)
        height_entry.pack(side="left")
        Checkbutton(top, text="等比例", variable=self.keep_ratio).pack(side="left", padx=(12, 0))
        self._toolbar_separator(top)
        Button(top, text="重置", command=self._reset_defaults).pack(side="left", padx=(8, 0))
        Button(top, text="↶", command=self.undo, width=3).pack(side="left", padx=(4, 0))
        Button(top, text="↷", command=self.redo, width=3).pack(side="left", padx=(4, 0))
        Button(top, text="⟳90", command=self._rotate_90, width=5).pack(side="left", padx=(4, 0))
        self._toolbar_separator(top)
        self._build_align_icons()
        for where in ["left", "hcenter", "right", "top", "vcenter", "bottom"]:
            Button(top, image=self.align_icons[where], command=lambda w=where: self._align_image(w), width=28, height=24).pack(side="left", padx=(4, 0))
        self._toolbar_separator(top)
        for label, ratio in [("1:1", 1 / 1), ("16:9", 16 / 9), ("9:16", 9 / 16), ("4:3", 4 / 3), ("3:4", 3 / 4), ("3:2", 3 / 2)]:
            Button(top, text=label, command=lambda r=ratio: self._apply_ratio_preset(r), width=5).pack(side="left", padx=(4, 0))
        width_entry.bind("<FocusOut>", lambda _e: self._sync_box_from_size("w"))
        height_entry.bind("<FocusOut>", lambda _e: self._sync_box_from_size("h"))

        self.canvas = Canvas(self.win, bg="#222", cursor="fleur")
        self.canvas.pack(fill="both", expand=True, padx=10, pady=8)
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<MouseWheel>", self._on_editor_mousewheel)

        bottom = Frame(self.win, padx=10, pady=8)
        bottom.pack(fill="x")
        Label(bottom, text="拖四边/四角调输出尺寸；框内拖图片调位置；滚轮缩放；靠近画布边缘自动吸附。").pack(side="left")
        Button(bottom, text="打开结果", command=self._open_result_dir).pack(side="right")
        Button(
            bottom,
            text="覆盖原图",
            command=self._overwrite_original,
            fg="#b42318",
            activeforeground="#b42318",
            width=10,
        ).pack(side="right", padx=(8, 0))
        Button(
            bottom,
            text="保存副本",
            command=self._save_copy_auto,
            width=12,
            bg="#0b5cad",
            fg="white",
            activebackground="#084a8d",
            activeforeground="white",
            font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(side="right", padx=(8, 0), ipady=1)

    def _toolbar_separator(self, parent: Frame) -> None:
        Frame(parent, width=1, height=24, bg="#c8c8c8").pack(side="left", padx=(12, 8))

    def _build_align_icons(self) -> None:
        if self.align_icons:
            return
        for kind in ["left", "hcenter", "right", "top", "vcenter", "bottom"]:
            img = Image.new("RGBA", (22, 18), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            line = "#5d636b"
            block = "#5d636b"
            if kind == "left":
                draw.line((4, 3, 4, 15), fill=line, width=2)
                draw.rectangle((8, 4, 18, 8), fill=block)
                draw.rectangle((8, 11, 15, 15), fill=block)
            elif kind == "hcenter":
                draw.line((11, 2, 11, 16), fill=line, width=2)
                draw.rectangle((5, 4, 17, 8), fill=block)
                draw.rectangle((7, 11, 15, 15), fill=block)
            elif kind == "right":
                draw.line((18, 3, 18, 15), fill=line, width=2)
                draw.rectangle((4, 4, 14, 8), fill=block)
                draw.rectangle((7, 11, 14, 15), fill=block)
            elif kind == "top":
                draw.line((4, 4, 18, 4), fill=line, width=2)
                draw.rectangle((6, 8, 10, 15), fill=block)
                draw.rectangle((13, 8, 17, 12), fill=block)
            elif kind == "vcenter":
                draw.line((3, 9, 19, 9), fill=line, width=2)
                draw.rectangle((6, 3, 10, 15), fill=block)
                draw.rectangle((13, 5, 17, 13), fill=block)
            elif kind == "bottom":
                draw.line((4, 15, 18, 15), fill=line, width=2)
                draw.rectangle((6, 4, 10, 11), fill=block)
                draw.rectangle((13, 8, 17, 11), fill=block)
            self.align_icons[kind] = ImageTk.PhotoImage(img)

    def _reset_view(self) -> None:
        self.win.update_idletasks()
        cw, ch = max(400, self.canvas.winfo_width()), max(320, self.canvas.winfo_height())
        self.canvas_size = (cw, ch)
        self.scale = min((cw - 80) / self.original.width, (ch - 80) / self.original.height, 1.0)
        pw, ph = int(self.original.width * self.scale), int(self.original.height * self.scale)
        self.preview_size = (pw, ph)
        self.image_offset = [(cw - pw) // 2, (ch - ph) // 2]
        box_w = min(pw, int(self.width_var.get() * self.scale))
        box_h = min(ph, int(self.height_var.get() * self.scale))
        self.output_box = [(cw - box_w) // 2, (ch - box_h) // 2, (cw + box_w) // 2, (ch + box_h) // 2]
        self._draw_static_image()
        self._draw_overlay()

    def _state(self) -> dict[str, object]:
        return {
            "original": self.original.copy(),
            "scale": self.scale,
            "rotation": self.rotation,
            "image_offset": list(self.image_offset),
            "output_box": list(self.output_box),
            "width": int(self.width_var.get()),
            "height": int(self.height_var.get()),
        }

    def _restore_state(self, state: dict[str, object]) -> None:
        self.original = state["original"].copy()  # type: ignore[assignment,union-attr]
        self.scale = float(state["scale"])
        self.rotation = int(state["rotation"])
        self.image_offset = list(state["image_offset"])  # type: ignore[arg-type]
        self.output_box = list(state["output_box"])  # type: ignore[arg-type]
        self.width_var.set(int(state["width"]))
        self.height_var.set(int(state["height"]))
        self.preview_size = (max(1, int(self.original.width * self.scale)), max(1, int(self.original.height * self.scale)))
        self._draw_static_image()
        self._draw_overlay()

    def _push_history(self) -> None:
        self.undo_stack.append(self._state())
        if len(self.undo_stack) > 80:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def undo(self) -> None:
        if not self.undo_stack:
            return
        self.redo_stack.append(self._state())
        self._restore_state(self.undo_stack.pop())

    def redo(self) -> None:
        if not self.redo_stack:
            return
        self.undo_stack.append(self._state())
        self._restore_state(self.redo_stack.pop())

    def _reset_defaults(self) -> None:
        self._push_history()
        self.rotation = 0
        self.original = Image.open(self.source).convert("RGBA")
        self.width_var.set(self.original.width)
        self.height_var.set(self.original.height)
        self._reset_view()

    def _draw_static_image(self) -> None:
        shown = self.original.convert("RGB").resize(self.preview_size, Image.Resampling.LANCZOS)
        self.preview_ref = ImageTk.PhotoImage(shown)
        self.canvas.delete("image")
        self.canvas.create_image(self.image_offset[0], self.image_offset[1], image=self.preview_ref, anchor="nw", tags="image")

    def _draw_overlay(self) -> None:
        self.canvas.delete("overlay")
        x1, y1, x2, y2 = self.output_box
        cw, ch = self.canvas_size
        mask_options = {"fill": "#000000", "stipple": "gray50", "outline": "", "tags": "overlay"}
        mask_areas = [(0, 0, cw, y1), (0, y2, cw, ch), (0, y1, x1, y2), (x2, y1, cw, y2)]
        for area in mask_areas:
            self.canvas.create_rectangle(*area, **mask_options)
            self.canvas.create_rectangle(*area, **mask_options)
        self.canvas.create_rectangle(x1, y1, x2, y2, outline="#00d084", width=2, tags="overlay")
        for hx, hy in self._handles():
            self.canvas.create_rectangle(hx - self.HANDLE // 2, hy - self.HANDLE // 2, hx + self.HANDLE // 2, hy + self.HANDLE // 2, fill="#00d084", outline="#00d084", tags="overlay")
        self._update_crop_size_label()

    def _update_crop_size_label(self) -> None:
        try:
            width = max(1, int(self.width_var.get()))
            height = max(1, int(self.height_var.get()))
        except Exception:
            width, height = self.original.width, self.original.height
        self.crop_size_text.set(f"当前裁剪：{width} x {height}")

    def _handles(self) -> list[tuple[int, int]]:
        x1, y1, x2, y2 = self.output_box
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        return [(x1, y1), (cx, y1), (x2, y1), (x2, cy), (x2, y2), (cx, y2), (x1, y2), (x1, cy)]

    def _on_canvas_resize(self, _event) -> None:
        if self.resize_after_id:
            self.win.after_cancel(self.resize_after_id)
        self.resize_after_id = self.win.after(120, self._reset_view)

    def _hit_test(self, x: int, y: int) -> str:
        names = ["nw", "n", "ne", "e", "se", "s", "sw", "w"]
        for name, (hx, hy) in zip(names, self._handles()):
            if abs(x - hx) <= self.HANDLE and abs(y - hy) <= self.HANDLE:
                return name
        x1, y1, x2, y2 = self.output_box
        near_left = abs(x - x1) <= self.HANDLE and y1 <= y <= y2
        near_right = abs(x - x2) <= self.HANDLE and y1 <= y <= y2
        near_top = abs(y - y1) <= self.HANDLE and x1 <= x <= x2
        near_bottom = abs(y - y2) <= self.HANDLE and x1 <= x <= x2
        if near_left and near_top:
            return "nw"
        if near_right and near_top:
            return "ne"
        if near_right and near_bottom:
            return "se"
        if near_left and near_bottom:
            return "sw"
        if near_left:
            return "w"
        if near_right:
            return "e"
        if near_top:
            return "n"
        if near_bottom:
            return "s"
        ix, iy = self.image_offset
        pw, ph = self.preview_size
        if ix <= x <= ix + pw and iy <= y <= iy + ph:
            return "move_image"
        return "none"

    def _on_motion(self, event) -> None:
        mode = self._hit_test(event.x, event.y)
        cursors = {"nw": "sizing", "n": "sb_v_double_arrow", "ne": "sizing", "e": "sb_h_double_arrow", "se": "sizing", "s": "sb_v_double_arrow", "sw": "sizing", "w": "sb_h_double_arrow", "move_image": "fleur"}
        self.canvas.config(cursor=cursors.get(mode, "arrow"))

    def _on_press(self, event) -> None:
        self.drag_mode = self._hit_test(event.x, event.y)
        self.drag_start = (event.x, event.y)
        self.start_box = list(self.output_box)
        self.start_offset = list(self.image_offset)
        if self.drag_mode != "none":
            self._push_history()

    def _on_drag(self, event) -> None:
        if not self.drag_mode or not self.drag_start or self.start_box is None or self.start_offset is None:
            return
        dx, dy = event.x - self.drag_start[0], event.y - self.drag_start[1]
        if self.drag_mode == "move_image":
            self.image_offset = [self.start_offset[0] + dx, self.start_offset[1] + dy]
            self._snap_image()
            self.canvas.coords("image", self.image_offset[0], self.image_offset[1])
        elif self.drag_mode != "none":
            x1, y1, x2, y2 = self.start_box
            if "w" in self.drag_mode:
                x1 += dx
            if "e" in self.drag_mode:
                x2 += dx
            if "n" in self.drag_mode:
                y1 += dy
            if "s" in self.drag_mode:
                y2 += dy
            if x2 - x1 >= 12 and y2 - y1 >= 12:
                self.output_box = [x1, y1, x2, y2]
                self._clamp_box()
                self._snap_box()
                self._sync_size_from_box()
                self._draw_overlay()

    def _on_release(self, _event) -> None:
        self.drag_mode = None
        self.drag_start = None
        self.start_box = None
        self.start_offset = None

    def _clamp_box(self) -> None:
        x1, y1, x2, y2 = self.output_box
        cw, ch = self.canvas_size
        w, h = x2 - x1, y2 - y1
        x1 = max(0, min(cw - w, x1))
        y1 = max(0, min(ch - h, y1))
        self.output_box = [x1, y1, x1 + w, y1 + h]

    def _snap_box(self) -> None:
        x1, y1, x2, y2 = self.output_box
        cw, ch = self.canvas_size
        ix, iy = self.image_offset
        pw, ph = self.preview_size
        snap_edges_x = [0, cw, ix, ix + pw]
        snap_edges_y = [0, ch, iy, iy + ph]
        for edge in snap_edges_x:
            if abs(x1 - edge) <= self.SNAP:
                x1 = edge
            if abs(x2 - edge) <= self.SNAP:
                x2 = edge
        for edge in snap_edges_y:
            if abs(y1 - edge) <= self.SNAP:
                y1 = edge
            if abs(y2 - edge) <= self.SNAP:
                y2 = edge
        self.output_box = [x1, y1, x2, y2]

    def _snap_image(self) -> None:
        ix, iy = self.image_offset
        pw, ph = self.preview_size
        cw, ch = self.canvas_size
        x1, y1, x2, y2 = self.output_box
        left_targets = [0, x1, x2]
        right_targets = [cw, x1, x2]
        top_targets = [0, y1, y2]
        bottom_targets = [ch, y1, y2]
        for target in left_targets:
            if abs(ix - target) <= self.SNAP:
                ix = target
                break
        for target in right_targets:
            if abs((ix + pw) - target) <= self.SNAP:
                ix = target - pw
                break
        for target in top_targets:
            if abs(iy - target) <= self.SNAP:
                iy = target
                break
        for target in bottom_targets:
            if abs((iy + ph) - target) <= self.SNAP:
                iy = target - ph
                break
        self.image_offset = [ix, iy]

    def _align_image(self, where: str) -> None:
        self._push_history()
        x1, y1, x2, y2 = self.output_box
        pw, ph = self.preview_size
        if where == "left":
            self.image_offset[0] = x1
        elif where == "hcenter":
            self.image_offset[0] = x1 + ((x2 - x1) - pw) // 2
        elif where == "right":
            self.image_offset[0] = x2 - pw
        elif where == "top":
            self.image_offset[1] = y1
        elif where == "vcenter":
            self.image_offset[1] = y1 + ((y2 - y1) - ph) // 2
        elif where == "bottom":
            self.image_offset[1] = y2 - ph
        elif where == "center":
            self.image_offset = [x1 + ((x2 - x1) - pw) // 2, y1 + ((y2 - y1) - ph) // 2]
        self.canvas.coords("image", self.image_offset[0], self.image_offset[1])

    def _apply_ratio_preset(self, ratio: float) -> None:
        self._push_history()
        if self.preview_size[0] <= 20 or self.preview_size[1] <= 20:
            self._reset_view()
        ix, iy = self.image_offset
        pw, ph = self.preview_size
        available_w = max(20, pw)
        available_h = max(20, ph)
        if available_w / available_h > ratio:
            box_h = available_h
            box_w = int(box_h * ratio)
        else:
            box_w = available_w
            box_h = int(box_w / ratio)
        cx = ix + pw // 2
        cy = iy + ph // 2
        self.output_box = [cx - box_w // 2, cy - box_h // 2, cx + box_w // 2, cy + box_h // 2]
        self._clamp_box()
        self._snap_box()
        self._sync_size_from_box()
        self._draw_overlay()

    def _on_editor_mousewheel(self, event) -> str:
        factor = 1.08 if event.delta > 0 else 0.92
        cx, cy = event.x, event.y
        old_scale = self.scale
        new_scale = max(0.05, min(6.0, self.scale * factor))
        if abs(new_scale - old_scale) < 0.001:
            return "break"
        self._push_history()
        ix, iy = self.image_offset
        rx = (cx - ix) / max(1, self.preview_size[0])
        ry = (cy - iy) / max(1, self.preview_size[1])
        self.scale = new_scale
        self.preview_size = (max(1, int(self.original.width * self.scale)), max(1, int(self.original.height * self.scale)))
        self.image_offset = [int(cx - rx * self.preview_size[0]), int(cy - ry * self.preview_size[1])]
        self._draw_static_image()
        self._draw_overlay()
        return "break"

    def _rotate_90(self) -> None:
        self._push_history()
        self.rotation = (self.rotation + 90) % 360
        self.original = self.original.rotate(-90, expand=True)
        self.width_var.set(self.original.width)
        self.height_var.set(self.original.height)
        self._reset_view()

    def _sync_size_from_box(self) -> None:
        x1, y1, x2, y2 = self.output_box
        self.width_var.set(max(1, int((x2 - x1) / self.scale)))
        self.height_var.set(max(1, int((y2 - y1) / self.scale)))
        self._update_crop_size_label()

    def _sync_box_from_size(self, changed: str) -> None:
        self._push_history()
        w, h = max(1, int(self.width_var.get())), max(1, int(self.height_var.get()))
        if self.keep_ratio.get():
            ratio = self.original.width / self.original.height
            if changed == "w":
                h = max(1, int(w / ratio))
                self.height_var.set(h)
            else:
                w = max(1, int(h * ratio))
                self.width_var.set(w)
        cx = (self.output_box[0] + self.output_box[2]) // 2
        cy = (self.output_box[1] + self.output_box[3]) // 2
        bw, bh = int(w * self.scale), int(h * self.scale)
        self.output_box = [cx - bw // 2, cy - bh // 2, cx + bw // 2, cy + bh // 2]
        self._clamp_box()
        self._draw_overlay()
        self._update_crop_size_label()

    def _edited_image(self) -> Image.Image:
        x1, y1, x2, y2 = self.output_box
        ix, iy = self.image_offset
        sx1 = max(0, int((x1 - ix) / self.scale))
        sy1 = max(0, int((y1 - iy) / self.scale))
        sx2 = min(self.original.width, int((x2 - ix) / self.scale))
        sy2 = min(self.original.height, int((y2 - iy) / self.scale))
        if sx2 <= sx1 or sy2 <= sy1:
            raise ValueError("输出框没有覆盖到图片内容")
        im = self.original.crop((sx1, sy1, sx2, sy2))
        w, h = max(1, int(self.width_var.get())), max(1, int(self.height_var.get()))
        if self.keep_ratio.get():
            ratio = im.width / im.height
            if w / h > ratio:
                w = int(h * ratio)
            else:
                h = int(w / ratio)
        if im.size != (w, h):
            im = im.resize((w, h), Image.Resampling.LANCZOS)
        return im

    def _next_copy_path(self) -> Path:
        base = self.source.with_name(f"{self.source.stem}_edited{self.source.suffix}")
        if not base.exists():
            return base
        for i in range(2, 1000):
            candidate = self.source.with_name(f"{self.source.stem}_edited_{i}{self.source.suffix}")
            if not candidate.exists():
                return candidate
        raise ValueError("无法生成副本文件名")

    def _next_copy_path_with_suffix(self, suffix: str) -> Path:
        suffix = suffix if suffix.startswith(".") else f".{suffix}"
        base = self.source.with_name(f"{self.source.stem}_edited{suffix}")
        if not base.exists():
            return base
        for i in range(2, 1000):
            candidate = self.source.with_name(f"{self.source.stem}_edited_{i}{suffix}")
            if not candidate.exists():
                return candidate
        raise ValueError("无法生成副本文件名")

    def _save_copy_auto(self) -> None:
        self._save_image(self._next_copy_path(), close=True)

    def _overwrite_original(self) -> None:
        if messagebox.askyesno("确认覆盖", f"确定覆盖原图吗？\n{self.source}"):
            self._save_image(self.source, close=True)

    def _open_result_dir(self) -> None:
        target = self.last_saved_path or self.source
        folder = target.parent if target.is_file() else target
        os.startfile(folder)  # type: ignore[attr-defined]

    def _save_image(self, path: Path, close: bool) -> None:
        im = self._edited_image()
        ext = path.suffix.lower()
        if ext in {".jpg", ".jpeg"}:
            im = ImageConverterApp._flatten_alpha(im, (255, 255, 255))
        path.parent.mkdir(parents=True, exist_ok=True)
        if ext in {".jpg", ".jpeg"}:
            im.save(path, format="JPEG", quality=92, optimize=True, progressive=True)
        elif ext == ".webp":
            im.save(path, format="WEBP", quality=92, method=6)
        else:
            im.save(path)
        self.last_saved_path = path
        self.app.refresh_after_edit()
        if close:
            self.win.destroy()

    def save_converted_copy(self, out_format: str, quality: int, progressive: bool, bg: tuple[int, int, int]) -> Path:
        ext = ".jpg" if out_format == "jpg" else f".{out_format}"
        path = self._next_copy_path_with_suffix(ext)
        im = self._edited_image()
        if out_format == "jpg":
            im = ImageConverterApp._flatten_alpha(im, bg)
        elif out_format == "webp":
            im = im.convert("RGBA") if im.mode in {"RGBA", "LA", "P"} else im.convert("RGB")
        elif out_format == "png":
            im = im.convert("RGBA") if im.mode in {"RGBA", "LA", "P"} else im.convert("RGB")
        path.parent.mkdir(parents=True, exist_ok=True)
        if out_format == "jpg":
            im.save(path, format="JPEG", quality=quality, optimize=True, progressive=progressive)
        elif out_format == "webp":
            im.save(path, format="WEBP", quality=quality, method=6)
        elif out_format == "png":
            im.save(path, format="PNG", optimize=True)
        else:
            raise ValueError(f"Unsupported output format: {out_format}")
        self.last_saved_path = path
        self.app.refresh_after_edit()
        return path


class EmbeddedImageEditor(ImageEditorWindow):
    def __init__(self, app: ImageConverterApp, parent: Frame, source: Path) -> None:
        self.app = app
        self.source = source
        self.original = Image.open(source).convert("RGBA")
        self.win = Frame(parent)
        self.win.pack(fill="both", expand=True)

        self.width_var = IntVar(value=self.original.width)
        self.height_var = IntVar(value=self.original.height)
        self.crop_size_text = StringVar(value=f"当前裁剪：{self.original.width} x {self.original.height}")
        self.keep_ratio = BooleanVar(value=True)
        self.preview_ref: ImageTk.PhotoImage | None = None
        self.preview_size = (1, 1)
        self.canvas_size = (1, 1)
        self.scale = 1.0
        self.rotation = 0
        self.image_offset = [0, 0]
        self.output_box = [0, 0, self.original.width, self.original.height]
        self.drag_mode: str | None = None
        self.drag_start: tuple[int, int] | None = None
        self.start_box: list[int] | None = None
        self.start_offset: list[int] | None = None
        self.resize_after_id: str | None = None
        self.undo_stack: list[dict[str, object]] = []
        self.redo_stack: list[dict[str, object]] = []
        self.last_saved_path: Path | None = None
        self.align_icons: dict[str, ImageTk.PhotoImage] = {}

        self._build_ui()
        self.win.after(80, self._reset_view)

    def _center_window(self, width: int, height: int) -> None:
        return

    def _save_copy_auto(self) -> None:
        path = self.save_converted_copy(
            self.app.single_output_format.get(),
            int(self.app.single_quality.get()),
            bool(self.app.single_progressive_jpg.get()),
            self.app._parse_color(self.app.single_alpha_bg.get()),
        )
        self.app.single_last_result = path
        messagebox.showinfo("已保存", f"副本已保存到原图旁边：\n{path}")

    def _overwrite_original(self) -> None:
        if messagebox.askyesno("确认覆盖", f"确定要覆盖原图吗？\n{self.source}"):
            self._save_image(self.source, close=False)
            messagebox.showinfo("已覆盖", "原图已更新。")


def main() -> None:
    root = Tk()
    ImageConverterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
