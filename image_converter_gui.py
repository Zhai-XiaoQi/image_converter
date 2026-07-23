from __future__ import annotations

import os
import queue
import re
import io
import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import (
    BooleanVar,
    Button,
    Canvas,
    Checkbutton,
    DoubleVar,
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
    simpledialog,
)
from tkinter import font as tkfont
from tkinter import ttk

from PIL import Image, ImageDraw, ImageFont, ImageGrab, ImageOps, ImageTk

try:
    import pillow_heif  # type: ignore[import-not-found]

    pillow_heif.register_heif_opener()
    HEIC_ENABLED = True
except Exception:
    HEIC_ENABLED = False


SUPPORTED_INPUTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif"}
SKIP_DIR_NAMES = {"渐进式JPG", "AI_language_check_contact_sheets", "AI_language_text_check_sheets", "AI_language_category_sheets"}
PRESETS_FILE = Path(__file__).with_name("image_converter_presets.json")
INVALID_FILENAME_CHARS = r'<>:"/\|?*'
APP_VERSION = "v1.4.6"
DEFAULT_PRESETS = {
    "Amazon主图优化": {
        "output_format": "jpg",
        "quality": 92,
        "progressive_jpg": True,
        "preserve_structure": True,
        "alpha_bg": "#ffffff",
        "compression_mode": "quality",
        "target_size": "",
        "resize_mode": "exact",
        "resize_width": 1600,
        "resize_height": 1600,
        "resize_scale_percent": 100,
        "resize_fit_mode": "pad",
        "rename_template": "{name}",
        "rename_prefix": "",
        "rename_suffix": "",
        "rename_find": "",
        "rename_replace": "",
        "rename_start": 1,
        "watermark_enabled": False,
    },
    "A+桌面图": {
        "output_format": "jpg",
        "quality": 92,
        "progressive_jpg": True,
        "preserve_structure": True,
        "alpha_bg": "#ffffff",
        "compression_mode": "quality",
        "target_size": "",
        "resize_mode": "exact",
        "resize_width": 1464,
        "resize_height": 600,
        "resize_scale_percent": 100,
        "resize_fit_mode": "crop",
        "rename_template": "{name}",
        "rename_prefix": "",
        "rename_suffix": "",
        "rename_find": "",
        "rename_replace": "",
        "rename_start": 1,
        "watermark_enabled": False,
    },
    "移动A+": {
        "output_format": "jpg",
        "quality": 92,
        "progressive_jpg": True,
        "preserve_structure": True,
        "alpha_bg": "#ffffff",
        "compression_mode": "quality",
        "target_size": "",
        "resize_mode": "exact",
        "resize_width": 1500,
        "resize_height": 1125,
        "resize_scale_percent": 100,
        "resize_fit_mode": "crop",
        "rename_template": "{name}",
        "rename_prefix": "",
        "rename_suffix": "",
        "rename_find": "",
        "rename_replace": "",
        "rename_start": 1,
        "watermark_enabled": False,
    },
    "WebP网页图": {
        "output_format": "webp",
        "quality": 85,
        "progressive_jpg": False,
        "preserve_structure": True,
        "alpha_bg": "#ffffff",
        "compression_mode": "quality",
        "target_size": "",
        "resize_mode": "none",
        "resize_width": 0,
        "resize_height": 0,
        "resize_scale_percent": 100,
        "resize_fit_mode": "contain",
        "rename_template": "{name}",
        "rename_prefix": "",
        "rename_suffix": "",
        "rename_find": "",
        "rename_replace": "",
        "rename_start": 1,
        "watermark_enabled": False,
    },
}


@dataclass
class ConvertJob:
    source: Path
    target: Path
    selected: bool = True
    tree_id: str = ""
    status: str = "pending"
    message: str = ""


@dataclass(frozen=True)
class WorkflowModule:
    id: str
    name: str
    enabled: bool
    summary: str
    panel_key: str


@dataclass(frozen=True)
class ProcessingStep:
    id: str
    name: str
    module_id: str


class ImageConverterApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title(f"图片格式转换工具 {APP_VERSION}")
        self.default_window_size = (1900, 1040)
        self.root.minsize(1500, 820)

        self.input_paths: list[Path] = []
        self.jobs: list[ConvertJob] = []
        self.tree_nodes: dict[str, dict[str, object]] = {}
        self.card_frames: dict[int, Frame] = {}
        self.card_vars: dict[int, BooleanVar] = {}
        self.thumb_cache: dict[tuple[str, int, tuple[int, int]], ImageTk.PhotoImage] = {}
        self.tree_icons: dict[tuple[str, str], ImageTk.PhotoImage] = {}
        self.selection_state: dict[str, bool] = {}
        self.hover_tree_item: str | None = None
        self.layout_after_id: str | None = None
        self.scan_after_id: str | None = None
        self.preview_zoom_after_id: str | None = None
        self.single_result_after_id: str | None = None
        self.preview_zoom_updating = False
        self.preview_zoom_generation = 0
        self.preview_after_id: str | None = None
        self.worker: threading.Thread | None = None
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.target_conflict_error = ""
        self.workflow_cards: dict[str, Frame] = {}
        self.parameter_panels: dict[str, Frame] = {}
        self.parameter_panel_bodies: dict[str, Frame] = {}
        self.parameter_panel_pack: dict[str, dict[str, object]] = {}
        self.parameter_panel_children: dict[str, list[tuple[object, dict[str, object]]]] = {}
        self.parameter_panel_expanded: dict[str, bool] = {
            "format": True,
            "size": False,
            "rename": False,
            "watermark": False,
        }
        self.parameter_summary_vars: dict[str, StringVar] = {
            "format": StringVar(value=""),
            "size": StringVar(value=""),
            "rename": StringVar(value=""),
            "watermark": StringVar(value=""),
        }
        self.parameter_toggle_buttons: dict[str, Button] = {}
        self.workflow_ui_after_id: str | None = None
        self.active_workflow_module_id: str | None = None
        self.task_ui_after_id: str | None = None
        self.last_task_ui_update = 0.0
        self.current_processing_steps: list[ProcessingStep] = []
        self.current_processing_index = 0
        self.processing_step_states: dict[str, str] = {}
        self.task_stats = {
            "total_steps": 0,
            "completed_steps": 0,
            "ok": 0,
            "failed": 0,
            "skipped": 0,
            "unselected": 0,
            "current_file": "",
            "current_step": "等待开始转换",
            "started_at": None,
        }

        self.mode = StringVar(value="folder")
        self.format_conversion_enabled = BooleanVar(value=True)
        self.output_format = StringVar(value="jpg")
        self.quality = IntVar(value=92)
        self.progressive_jpg = BooleanVar(value=False)
        self.preserve_structure = BooleanVar(value=True)
        self.overwrite = BooleanVar(value=False)
        self.delete_originals = BooleanVar(value=False)
        self.alpha_bg = StringVar(value="#ffffff")
        self.preset_name = StringVar(value="自定义")
        self.presets: dict[str, dict[str, object]] = {}
        self.compression_mode = StringVar(value="quality")
        self.compression_enabled = BooleanVar(value=True)
        self.target_size = StringVar(value="")
        self.size_compress_enabled = BooleanVar(value=True)
        self.resize_enabled = BooleanVar(value=False)
        self.resize_mode = StringVar(value="none")
        self.resize_width = IntVar(value=0)
        self.resize_height = IntVar(value=0)
        self.resize_scale_percent = IntVar(value=100)
        self.resize_fit_mode = StringVar(value="pad")
        self.rename_template = StringVar(value="{name}")
        self.rename_enabled = BooleanVar(value=False)
        self.rename_prefix = StringVar(value="")
        self.rename_suffix = StringVar(value="")
        self.rename_find = StringVar(value="")
        self.rename_replace = StringVar(value="")
        self.rename_replace_rules: list[tuple[str, str]] = []
        self.rename_rules_summary = StringVar(value="更多替换 0 条")
        self.rename_start = IntVar(value=1)
        self.watermark_enabled = BooleanVar(value=False)
        self.watermark_type = StringVar(value="text")
        self.watermark_text = StringVar(value="")
        self.watermark_logo = StringVar(value="")
        self.watermark_position = StringVar(value="右下")
        self.watermark_opacity = IntVar(value=45)
        self.watermark_margin = IntVar(value=24)
        self.watermark_font_size = IntVar(value=36)
        self.watermark_color = StringVar(value="#ffffff")
        self.watermark_outline = BooleanVar(value=True)
        self.watermark_shadow = BooleanVar(value=True)
        self.watermark_scale_percent = IntVar(value=100)
        self.watermark_angle = IntVar(value=0)
        self.watermark_custom_x = DoubleVar(value=-1.0)
        self.watermark_custom_y = DoubleVar(value=-1.0)
        self.heic_notice = StringVar(value="")
        self.preset_summary = StringVar(value="选择预设后会自动回填格式、尺寸和处理规则。")
        self.workflow_stats_text = StringVar(value="")
        self.task_current_file_text = StringVar(value="当前文件：-")
        self.task_current_step_text = StringVar(value="当前步骤：等待开始转换")
        self.task_progress_text = StringVar(value="总进度：0%")
        self.preview_zoom = IntVar(value=100)
        self.preview_zoom_text = StringVar(value="100%")
        self.search_text = StringVar(value="")
        self.filter_jpg = BooleanVar(value=True)
        self.filter_png = BooleanVar(value=True)
        self.filter_webp = BooleanVar(value=True)
        self.filter_other = BooleanVar(value=True)
        self.single_output_format = StringVar(value="jpg")
        self.single_quality = IntVar(value=92)
        self.single_progressive_jpg = BooleanVar(value=False)
        self.single_alpha_bg = StringVar(value="#ffffff")
        self.single_result_size_text = StringVar(value="结果尺寸：-")
        self.single_result_file_size_text = StringVar(value="结果大小：-")
        self.single_last_result: Path | None = None
        self.input_text = StringVar(value="")
        self.output_text = StringVar(value="")
        self.status_text = StringVar(value="请选择图片或文件夹。")
        self.status_number_font = ("Microsoft YaHei UI", 9, "bold")

        self._load_presets()
        self._build_ui()
        self._build_tree_icons()
        self._center_root()
        self.root.after(120, self._drain_events)

    def _center_root(self) -> None:
        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        width = min(self.default_window_size[0], max(1280, screen_w - 24))
        height = min(self.default_window_size[1], max(820, screen_h - 80))
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _load_presets(self) -> None:
        self.presets = {name: values.copy() for name, values in DEFAULT_PRESETS.items()}
        if not PRESETS_FILE.exists():
            return
        try:
            loaded = json.loads(PRESETS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return
        if isinstance(loaded, dict):
            for name, values in loaded.items():
                if isinstance(name, str) and isinstance(values, dict):
                    self.presets[name] = values

    def _preset_names(self) -> list[str]:
        def display_name(name: str) -> str:
            values = self.presets.get(name, {})
            width = int(values.get("resize_width", 0) or 0)
            height = int(values.get("resize_height", 0) or 0)
            mode = str(values.get("resize_mode", "none"))
            if name == "WebP网页图" or mode == "none":
                return f"{name} - 原尺寸"
            if mode == "scale":
                return f"{name} - {int(values.get('resize_scale_percent', 100) or 100)}%"
            if width and height:
                return f"{name} - {width} x {height}"
            return name

        return ["自定义", *(display_name(name) for name in sorted(self.presets.keys()))]

    def _preset_summary_text(self, name: str) -> str:
        values = self.presets.get(name)
        if not values:
            return "自定义处理方案。"
        mode = str(values.get("resize_mode", "none"))
        if mode == "exact":
            width = int(values.get("resize_width", 0) or 0)
            height = int(values.get("resize_height", 0) or 0)
            fit_map = {"stretch": "拉伸", "pad": "等比留白", "crop": "等比裁剪"}
            fit = fit_map.get(str(values.get("resize_fit_mode", "pad")), str(values.get("resize_fit_mode", "pad")))
            size = f"{width} x {height} / {fit}" if width and height else "指定长宽"
        elif mode == "scale":
            size = f"按比例缩放 {int(values.get('resize_scale_percent', 100) or 100)}%"
        else:
            size = "不改变尺寸"
        out_format = str(values.get("output_format", "jpg")).upper()
        quality = int(values.get("quality", 92) or 92)
        return f"已套用：{name} / {out_format} / {size} / 质量 {quality}%"

    def _preset_key_from_display(self, display_name: str) -> str:
        if display_name in self.presets:
            return display_name
        for name in self.presets:
            if display_name.startswith(f"{name} - "):
                return name
        return display_name

    def _capture_preset(self) -> dict[str, object]:
        return {
            "output_format": self.output_format.get(),
            "quality": self._safe_int_var(self.quality, 92),
            "progressive_jpg": bool(self.progressive_jpg.get()),
            "preserve_structure": bool(self.preserve_structure.get()),
            "alpha_bg": self.alpha_bg.get(),
            "compression_enabled": bool(self.compression_enabled.get()),
            "compression_mode": self.compression_mode.get(),
            "target_size": self.target_size.get(),
            "resize_enabled": bool(self.resize_enabled.get()),
            "resize_mode": self.resize_mode.get(),
            "resize_width": self._safe_int_var(self.resize_width, 0),
            "resize_height": self._safe_int_var(self.resize_height, 0),
            "resize_scale_percent": self._safe_int_var(self.resize_scale_percent, 100),
            "resize_fit_mode": self.resize_fit_mode.get(),
            "rename_enabled": bool(self.rename_enabled.get()),
            "rename_template": self.rename_template.get(),
            "rename_prefix": self.rename_prefix.get(),
            "rename_suffix": self.rename_suffix.get(),
            "rename_find": self.rename_find.get(),
            "rename_replace": self.rename_replace.get(),
            "rename_replace_rules": list(self.rename_replace_rules),
            "rename_start": self._safe_int_var(self.rename_start, 1),
            "watermark_enabled": bool(self.watermark_enabled.get()),
            "watermark_type": self.watermark_type.get(),
            "watermark_text": self.watermark_text.get(),
            "watermark_logo": self.watermark_logo.get(),
            "watermark_position": self.watermark_position.get(),
            "watermark_opacity": self._safe_int_var(self.watermark_opacity, 45),
            "watermark_margin": self._safe_int_var(self.watermark_margin, 24),
            "watermark_font_size": self._safe_int_var(self.watermark_font_size, 36),
            "watermark_color": self.watermark_color.get(),
            "watermark_outline": bool(self.watermark_outline.get()),
            "watermark_shadow": bool(self.watermark_shadow.get()),
            "watermark_scale_percent": self._safe_int_var(self.watermark_scale_percent, 100),
            "watermark_angle": self._safe_int_var(self.watermark_angle, 0),
            "watermark_custom_x": float(self.watermark_custom_x.get()),
            "watermark_custom_y": float(self.watermark_custom_y.get()),
        }

    @staticmethod
    def _safe_int_var(var: IntVar, default: int) -> int:
        try:
            return int(var.get())
        except Exception:
            return default

    def apply_preset(self, name: str) -> None:
        name = self._preset_key_from_display(name)
        values = self.presets.get(name)
        if not values:
            return
        self.preset_name.set(self._preset_display_name(name))
        self.format_conversion_enabled.set(True)
        self.output_format.set(str(values.get("output_format", "jpg")))
        self.quality.set(int(values.get("quality", 92)))
        self.progressive_jpg.set(bool(values.get("progressive_jpg", False)))
        self.preserve_structure.set(bool(values.get("preserve_structure", True)))
        self.alpha_bg.set(str(values.get("alpha_bg", "#ffffff")))
        self.compression_enabled.set(bool(values.get("compression_enabled", True)))
        self.compression_mode.set(str(values.get("compression_mode", "quality")))
        self.target_size.set(str(values.get("target_size", "")))
        self.size_compress_enabled.set(bool(values.get("resize_enabled", str(values.get("resize_mode", "none")) != "none") or values.get("compression_enabled", True)))
        self.resize_enabled.set(bool(values.get("resize_enabled", str(values.get("resize_mode", "none")) != "none")))
        self.resize_mode.set(str(values.get("resize_mode", "none")))
        self.resize_width.set(int(values.get("resize_width", 0)))
        self.resize_height.set(int(values.get("resize_height", 0)))
        self.resize_scale_percent.set(int(values.get("resize_scale_percent", 100)))
        self.resize_fit_mode.set(str(values.get("resize_fit_mode", "pad")))
        self.rename_enabled.set(bool(values.get("rename_enabled", False)))
        self.rename_template.set(str(values.get("rename_template", "{name}")))
        self.rename_prefix.set(str(values.get("rename_prefix", "")))
        self.rename_suffix.set(str(values.get("rename_suffix", "")))
        self.rename_find.set(str(values.get("rename_find", "")))
        self.rename_replace.set(str(values.get("rename_replace", "")))
        raw_rules = values.get("rename_replace_rules", [])
        self.rename_replace_rules = [tuple(rule) for rule in raw_rules if isinstance(rule, (list, tuple)) and len(rule) == 2]  # type: ignore[list-item]
        self.rename_start.set(int(values.get("rename_start", 1)))
        self._update_rename_rules_summary()
        self.watermark_enabled.set(bool(values.get("watermark_enabled", False)))
        self.watermark_type.set(str(values.get("watermark_type", "text")))
        self.watermark_text.set(str(values.get("watermark_text", "")))
        self.watermark_logo.set(str(values.get("watermark_logo", "")))
        self.watermark_position.set(str(values.get("watermark_position", "右下")))
        self.watermark_opacity.set(int(values.get("watermark_opacity", 45)))
        self.watermark_margin.set(int(values.get("watermark_margin", 24)))
        self.watermark_font_size.set(int(values.get("watermark_font_size", 36)))
        self.watermark_color.set(str(values.get("watermark_color", "#ffffff")))
        self.watermark_outline.set(bool(values.get("watermark_outline", True)))
        self.watermark_shadow.set(bool(values.get("watermark_shadow", True)))
        self.watermark_scale_percent.set(int(values.get("watermark_scale_percent", 100)))
        self.watermark_angle.set(int(values.get("watermark_angle", 0)))
        self.watermark_custom_x.set(float(values.get("watermark_custom_x", -1.0)))
        self.watermark_custom_y.set(float(values.get("watermark_custom_y", -1.0)))
        self.preset_summary.set(self._preset_summary_text(name))
        self._update_control_states()
        self.scan_jobs()

    def _preset_display_name(self, name: str) -> str:
        values = self.presets.get(name, {})
        width = int(values.get("resize_width", 0) or 0)
        height = int(values.get("resize_height", 0) or 0)
        mode = str(values.get("resize_mode", "none"))
        if name == "WebP网页图" or mode == "none":
            return f"{name} - 原尺寸"
        if mode == "scale":
            return f"{name} - {int(values.get('resize_scale_percent', 100) or 100)}%"
        if width and height:
            return f"{name} - {width} x {height}"
        return name

    def save_current_preset(self) -> None:
        name = simpledialog.askstring("保存预设", "请输入预设名称：", initialvalue=self.preset_name.get() if self.preset_name.get() != "自定义" else "")
        if not name:
            return
        name = name.strip()
        if not name or name == "自定义":
            messagebox.showwarning("名称无效", "请使用有效的预设名称。")
            return
        self.presets[name] = self._capture_preset()
        PRESETS_FILE.write_text(json.dumps(self.presets, ensure_ascii=False, indent=2), encoding="utf-8")
        self.preset_name.set(self._preset_display_name(name))
        self.preset_combo.config(values=self._preset_names())
        messagebox.showinfo("已保存", f"预设已保存：{name}")

    def _build_ui(self) -> None:
        style = ttk.Style(self.root)
        module_font = ("Microsoft YaHei UI", 12, "bold")
        section_font = ("Microsoft YaHei UI", 10, "bold")
        style.configure("File.Treeview", font=("Microsoft YaHei UI", 12), rowheight=34)
        style.configure("File.Treeview.Heading", font=module_font)
        style.configure("TNotebook.Tab", font=("Microsoft YaHei UI", 12, "bold"), padding=(18, 8))
        style.map("File.Treeview", background=[("selected", "#dcecff")])

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True)
        main = Frame(self.notebook, padx=12, pady=12)
        self.notebook.add(main, text="批量自动化")

        body = Frame(main)
        body.pack(fill="both", expand=True)

        left_col = Frame(body)
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 8))

        settings_shell = LabelFrame(body, text="自动化工作流", font=module_font, width=560)
        settings_shell.pack(side="right", fill="x", anchor="n")
        opts = Frame(settings_shell)
        opts.pack(fill="x", padx=8, pady=8)

        top_area = Frame(left_col)
        top_area.pack(fill="x", pady=(0, 8))

        top = LabelFrame(top_area, text="输入", font=module_font)
        top.pack(side="left", fill="x", expand=True, padx=(0, 8))
        mode_row = Frame(top)
        mode_row.pack(fill="x", padx=10, pady=(5, 1))
        Button(mode_row, text="选择文件夹", command=self.choose_folder_input, width=14).pack(side="left")
        Button(mode_row, text="选择文件", command=self.choose_files_input, width=14).pack(side="left", padx=(8, 0))
        Button(mode_row, text="扫描预览", command=self.scan_jobs, width=12).pack(side="left", padx=(8, 0))
        Label(mode_row, text="支持：JPG / PNG / WEBP / HEIC / HEIF / BMP / TIFF", fg="#0b5cad").pack(side="left", padx=(14, 0))
        self.heic_label = Label(mode_row, textvariable=self.heic_notice, fg="#b42318", anchor="w")
        self.heic_label.pack(side="left", padx=(12, 0))
        input_row = Frame(top)
        input_row.pack(fill="x", padx=10, pady=(1, 5))
        Entry(input_row, textvariable=self.input_text).pack(side="left", fill="x", expand=True)

        out = LabelFrame(top_area, text="输出", font=module_font)
        out.pack(side="left", fill="x", expand=True)
        out_row = Frame(out)
        out_row.pack(fill="x", padx=10, pady=(17, 5))
        Entry(out_row, textvariable=self.output_text).pack(side="left", fill="x", expand=True)
        Button(out_row, text="选择输出目录", command=self.choose_output, width=14).pack(side="left", padx=(8, 0))
        Button(out_row, text="打开输出目录", command=self.open_output_dir, width=14).pack(side="left", padx=(8, 0))

        preview = LabelFrame(left_col, text="预览", font=module_font)
        preview.pack(fill="both", expand=True)
        filter_row = Frame(preview)
        filter_row.pack(fill="x", padx=10, pady=(8, 0))
        Label(filter_row, text="格式").pack(side="left")
        for text, var in [("JPG", self.filter_jpg), ("PNG", self.filter_png), ("WEBP", self.filter_webp), ("其他", self.filter_other)]:
            Checkbutton(filter_row, text=text, variable=var, command=self.scan_jobs).pack(side="left", padx=(8, 0))
        Label(filter_row, text="搜索").pack(side="left", padx=(24, 4))
        search_entry = Entry(filter_row, textvariable=self.search_text, width=34)
        search_entry.pack(side="left")
        Button(filter_row, text="清空", command=self._clear_search, width=8).pack(side="left", padx=(8, 0))
        self.preview_zoom_slider = ttk.Scale(filter_row, from_=60, to=180, orient="horizontal", variable=self.preview_zoom)
        self.preview_zoom_slider.pack(side="right", padx=(8, 0))
        self.preview_zoom_slider.bind("<B1-Motion>", lambda _e: self._on_preview_zoom_slide(str(self.preview_zoom.get())))
        self.preview_zoom_slider.bind("<ButtonRelease-1>", lambda _e: self._on_preview_zoom_slide(str(self.preview_zoom.get())))
        Button(filter_row, text="适应宽度", command=self._fit_preview_width, width=10).pack(side="right", padx=(10, 0))
        Label(filter_row, textvariable=self.preview_zoom_text, fg="#0b5cad", font=("Microsoft YaHei UI", 10, "bold")).pack(side="right")
        Label(filter_row, text="缩放").pack(side="right", padx=(24, 6))
        search_entry.bind("<KeyRelease>", lambda _e: self._schedule_scan())
        panes = PanedWindow(preview, orient="horizontal", sashwidth=6)
        self.preview_panes = panes
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
        panes.add(tree_outer, minsize=390)

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
        panes.add(grid_outer, minsize=760)

        workflow_box = LabelFrame(opts, text="当前处理流程", font=section_font)
        workflow_box.pack(fill="x", pady=(0, 6))
        self.workflow_cards_frame = Frame(workflow_box)
        self.workflow_cards_frame.pack(fill="x", padx=8, pady=(6, 2))
        Label(
            workflow_box,
            textvariable=self.workflow_stats_text,
            anchor="w",
            fg="#0b5cad",
            font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(fill="x", padx=10, pady=(3, 7))

        preset_box = LabelFrame(opts, text="处理预设", font=section_font)
        preset_box.pack(fill="x", pady=(0, 6))
        preset_row = Frame(preset_box)
        preset_row.pack(fill="x", padx=10, pady=7)
        self.preset_combo = ttk.Combobox(preset_row, textvariable=self.preset_name, values=self._preset_names(), width=26, state="readonly")
        self.preset_combo.pack(side="left", fill="x", expand=True)
        self.preset_combo.bind("<<ComboboxSelected>>", lambda _e: self.apply_preset(self.preset_name.get()))
        Button(preset_row, text="保存预设", command=self.save_current_preset, width=10).pack(side="left", padx=(8, 0))
        Label(preset_box, textvariable=self.preset_summary, fg="#0b5cad", anchor="w", wraplength=500).pack(fill="x", padx=10, pady=(0, 7))

        _base_panel, base_box = self._make_collapsible_panel(opts, "格式与输出", self.format_conversion_enabled, self._on_output_format_change, "format")
        self.format_controls: list[object] = []
        base_row1 = Frame(base_box)
        base_row1.pack(fill="x", padx=10, pady=(7, 4))
        Label(base_row1, text="输出格式").pack(side="left")
        for label, value in [("JPG", "jpg"), ("PNG", "png"), ("WEBP", "webp")]:
            rb = Radiobutton(base_row1, text=label, variable=self.output_format, value=value, command=self._on_output_format_change)
            rb.pack(side="left", padx=(10, 0))
            self.format_controls.append(rb)
        self.progressive_check = Checkbutton(base_row1, text="仅 JPG 渐进式", variable=self.progressive_jpg)
        self.progressive_check.pack(side="left", padx=(18, 0))
        base_row2 = Frame(base_box)
        base_row2.pack(fill="x", padx=10, pady=(2, 7))
        self.alpha_label = Label(base_row2, text="转 JPG 时背景色")
        self.alpha_label.pack(side="left")
        self.alpha_entry = Entry(base_row2, textvariable=self.alpha_bg, width=10)
        self.alpha_entry.pack(side="left", padx=(6, 0))
        self.preserve_structure_check = Checkbutton(base_row2, text="保留目录结构", variable=self.preserve_structure, command=self.scan_jobs)
        self.preserve_structure_check.pack(side="left", padx=(18, 0))
        self.format_controls.extend([self.progressive_check, self.alpha_label, self.alpha_entry, self.preserve_structure_check])

        _size_panel, size_compress_box = self._make_collapsible_panel(opts, "尺寸与压缩", self.size_compress_enabled, self._on_size_compress_toggle, "size")
        self.resize_controls: list[object] = []
        self.compression_controls: list[object] = []
        resize_box = Frame(size_compress_box)
        resize_box.pack(fill="x", padx=10, pady=(8, 2))
        resize_row1 = Frame(resize_box)
        resize_row1.pack(fill="x")
        Label(resize_row1, text="尺寸").pack(side="left", padx=(0, 8))
        for label, value in [("不改变尺寸", "none"), ("按比例缩放", "scale"), ("指定长宽", "exact")]:
            rb = Radiobutton(resize_row1, text=label, variable=self.resize_mode, value=value, command=self._on_resize_mode_change)
            rb.pack(side="left", padx=(0, 10))
            self.resize_controls.append(rb)
        self.resize_none_row = Frame(resize_box)
        self.resize_none_row.pack(fill="x", pady=(4, 2))
        self.resize_none_label = Label(self.resize_none_row, text="当前模式不会改变图片尺寸。", fg="#666")
        self.resize_none_label.pack(side="left")
        self.resize_scale_row = Frame(resize_box)
        Label(self.resize_scale_row, text="比例").pack(side="left")
        self.resize_scale_spin = ttk.Spinbox(self.resize_scale_row, from_=1, to=500, textvariable=self.resize_scale_percent, width=7)
        self.resize_scale_spin.pack(side="left", padx=(4, 2))
        Label(self.resize_scale_row, text="%").pack(side="left")
        self.resize_exact_row = Frame(resize_box)
        Label(self.resize_exact_row, text="宽").pack(side="left")
        self.resize_width_spin = ttk.Spinbox(self.resize_exact_row, from_=0, to=20000, textvariable=self.resize_width, width=7)
        self.resize_width_spin.pack(side="left", padx=(4, 2))
        Label(self.resize_exact_row, text="px  高").pack(side="left")
        self.resize_height_spin = ttk.Spinbox(self.resize_exact_row, from_=0, to=20000, textvariable=self.resize_height, width=7)
        self.resize_height_spin.pack(side="left", padx=(4, 2))
        Label(self.resize_exact_row, text="px").pack(side="left")
        resize_fit_row = Frame(resize_box)
        self.resize_fit_row = resize_fit_row
        Label(resize_fit_row, text="适配").pack(side="left")
        self.resize_fit_combo = ttk.Combobox(resize_fit_row, textvariable=self.resize_fit_mode, values=["stretch", "pad", "crop"], width=8, state="readonly")
        self.resize_fit_combo.pack(side="left", padx=(4, 0))
        self.resize_fit_combo.bind("<<ComboboxSelected>>", lambda _e: self.scan_jobs())
        self.resize_fit_hint = Label(resize_fit_row, text="stretch=拉伸 / pad=等比留白 / crop=等比裁剪", fg="#666")
        self.resize_fit_hint.pack(side="left", padx=(8, 0))
        self.resize_controls.extend([
            self.resize_scale_spin, self.resize_width_spin, self.resize_height_spin,
            self.resize_fit_combo, self.resize_none_label, self.resize_fit_hint,
        ])

        compress_row = Frame(size_compress_box)
        compress_row.pack(fill="x", padx=10, pady=(4, 8))
        Label(compress_row, text="压缩").pack(side="left", padx=(0, 8))
        self.compression_quality_radio = Radiobutton(compress_row, text="固定质量", variable=self.compression_mode, value="quality", command=self._update_control_states)
        self.compression_quality_radio.pack(side="left")
        self.quality_spin = ttk.Spinbox(compress_row, from_=1, to=100, textvariable=self.quality, width=6)
        self.quality_spin.pack(side="left", padx=(4, 2))
        Label(compress_row, text="%").pack(side="left")
        self.compression_target_radio = Radiobutton(compress_row, text="目标体积", variable=self.compression_mode, value="target", command=self._update_control_states)
        self.compression_target_radio.pack(side="left", padx=(18, 0))
        self.target_size_entry = Entry(compress_row, textvariable=self.target_size, width=9)
        self.target_size_entry.pack(side="left", padx=(4, 2))
        self.target_size_unit = Label(compress_row, text="KB")
        self.target_size_unit.pack(side="left")
        self.compression_hint = Label(compress_row, text="", fg="#9a6400")
        self.compression_hint.pack(side="left", padx=(10, 0))
        self.compression_controls.extend([
            self.compression_quality_radio, self.quality_spin, self.compression_target_radio,
            self.target_size_entry, self.target_size_unit, self.compression_hint,
        ])

        _rename_panel, rename_box = self._make_collapsible_panel(opts, "批量重命名", self.rename_enabled, lambda: (self._update_control_states(), self.scan_jobs()), "rename")
        self.rename_controls: list[object] = []
        rename_row = Frame(rename_box)
        rename_row.pack(fill="x", padx=8, pady=(5, 2))
        Label(rename_row, text="模板").pack(side="left")
        self.rename_template_entry = Entry(rename_row, textvariable=self.rename_template, width=24)
        self.rename_template_entry.pack(side="left", padx=(4, 8))
        self.rename_hint = Label(rename_row, text="可用：{name} {parent} {index} {index2} {index3} {date}", fg="#666")
        self.rename_hint.pack(side="left")
        rename_affix_row = Frame(rename_box)
        rename_affix_row.pack(fill="x", padx=8, pady=(2, 2))
        Label(rename_affix_row, text="前缀").pack(side="left")
        self.rename_prefix_entry = Entry(rename_affix_row, textvariable=self.rename_prefix, width=12)
        self.rename_prefix_entry.pack(side="left", padx=(4, 12))
        Label(rename_affix_row, text="后缀").pack(side="left")
        self.rename_suffix_entry = Entry(rename_affix_row, textvariable=self.rename_suffix, width=12)
        self.rename_suffix_entry.pack(side="left", padx=(4, 12))
        Label(rename_affix_row, text="起始序号").pack(side="left")
        self.rename_start_spin = ttk.Spinbox(rename_affix_row, from_=0, to=99999, textvariable=self.rename_start, width=7)
        self.rename_start_spin.pack(side="left", padx=(4, 0))
        rename_replace_row = Frame(rename_box)
        rename_replace_row.pack(fill="x", padx=8, pady=(2, 5))
        Label(rename_replace_row, text="替换").pack(side="left")
        self.rename_find_entry = Entry(rename_replace_row, textvariable=self.rename_find, width=18)
        self.rename_find_entry.pack(side="left", padx=(4, 8))
        Label(rename_replace_row, text="为").pack(side="left")
        self.rename_replace_entry = Entry(rename_replace_row, textvariable=self.rename_replace, width=18)
        self.rename_replace_entry.pack(side="left", padx=(4, 8))
        self.rename_rules_button = Button(rename_replace_row, text="更多替换...", command=self.open_rename_rules_editor, width=12)
        self.rename_rules_button.pack(side="left", padx=(4, 8))
        self.rename_rules_label = Label(rename_replace_row, textvariable=self.rename_rules_summary, fg="#0b5cad")
        self.rename_rules_label.pack(side="left")
        self.rename_controls.extend([
            self.rename_template_entry, self.rename_hint, self.rename_prefix_entry, self.rename_suffix_entry,
            self.rename_start_spin, self.rename_find_entry, self.rename_replace_entry,
            self.rename_rules_button, self.rename_rules_label,
        ])

        _watermark_panel, watermark_box = self._make_collapsible_panel(opts, "批量水印", self.watermark_enabled, self._update_control_states, "watermark")
        watermark_row1 = Frame(watermark_box)
        watermark_row1.pack(fill="x", padx=8, pady=(5, 2))
        self.watermark_common_controls: list[object] = []
        self.watermark_text_controls: list[object] = []
        self.watermark_logo_controls: list[object] = []
        self.watermark_preview_button = Button(watermark_row1, text="预览/编辑水印", command=self.open_watermark_editor, width=14)
        self.watermark_preview_button.pack(side="right")
        self.watermark_text_radio = Radiobutton(watermark_row1, text="文字", variable=self.watermark_type, value="text", command=self._update_control_states)
        self.watermark_text_radio.pack(side="left", padx=(10, 0))
        self.watermark_logo_radio = Radiobutton(watermark_row1, text="Logo", variable=self.watermark_type, value="logo", command=self._update_control_states)
        self.watermark_logo_radio.pack(side="left", padx=(8, 0))
        watermark_text_row = Frame(watermark_box)
        watermark_text_row.pack(fill="x", padx=8, pady=(2, 2))
        Label(watermark_text_row, text="文字").pack(side="left")
        self.watermark_text_entry = Entry(watermark_text_row, textvariable=self.watermark_text, width=34)
        self.watermark_text_entry.pack(side="left", fill="x", expand=True, padx=(4, 0))
        watermark_logo_row = Frame(watermark_box)
        watermark_logo_row.pack(fill="x", padx=8, pady=(2, 2))
        Label(watermark_logo_row, text="Logo").pack(side="left")
        self.watermark_logo_button = Button(watermark_row1, text="选择Logo", command=self.choose_watermark_logo, width=10)
        self.watermark_logo_button.pack_forget()
        self.watermark_logo_button = Button(watermark_logo_row, text="选择Logo", command=self.choose_watermark_logo, width=10)
        self.watermark_logo_button.pack(side="left", padx=(4, 0))
        Label(watermark_logo_row, textvariable=self.watermark_logo, fg="#666", anchor="w").pack(side="left", fill="x", expand=True, padx=(8, 0))
        watermark_row2 = Frame(watermark_box)
        watermark_row2.pack(fill="x", padx=8, pady=(2, 2))
        Label(watermark_row2, text="位置").pack(side="left")
        self.watermark_position_combo = ttk.Combobox(
            watermark_row2,
            textvariable=self.watermark_position,
            values=["左上", "上中", "右上", "左中", "居中", "右中", "左下", "下中", "右下"],
            width=6,
            state="readonly",
        )
        self.watermark_position_combo.pack(side="left", padx=(4, 8))
        self.watermark_position_combo.bind("<<ComboboxSelected>>", lambda _e: self._clear_custom_watermark_position())
        Label(watermark_row2, text="透明").pack(side="left")
        self.watermark_opacity_spin = ttk.Spinbox(watermark_row2, from_=1, to=100, textvariable=self.watermark_opacity, width=5)
        self.watermark_opacity_spin.pack(side="left", padx=(4, 2))
        Label(watermark_row2, text="%  边距").pack(side="left")
        self.watermark_margin_spin = ttk.Spinbox(watermark_row2, from_=0, to=999, textvariable=self.watermark_margin, width=5)
        self.watermark_margin_spin.pack(side="left", padx=(4, 2))
        Label(watermark_row2, text="px").pack(side="left")
        Label(watermark_row2, text="  缩放").pack(side="left")
        self.watermark_scale_spin = ttk.Spinbox(watermark_row2, from_=5, to=500, textvariable=self.watermark_scale_percent, width=5)
        self.watermark_scale_spin.pack(side="left", padx=(4, 2))
        Label(watermark_row2, text="%  角度").pack(side="left")
        self.watermark_angle_spin = ttk.Spinbox(watermark_row2, from_=-180, to=180, textvariable=self.watermark_angle, width=5)
        self.watermark_angle_spin.pack(side="left", padx=(4, 2))
        watermark_text_style_row = Frame(watermark_box)
        watermark_text_style_row.pack(fill="x", padx=8, pady=(2, 5))
        Label(watermark_text_style_row, text="字号").pack(side="left")
        self.watermark_font_spin = ttk.Spinbox(watermark_text_style_row, from_=8, to=300, textvariable=self.watermark_font_size, width=5)
        self.watermark_font_spin.pack(side="left", padx=(4, 8))
        Label(watermark_text_style_row, text="颜色").pack(side="left", padx=(0, 2))
        self.watermark_color_entry = Entry(watermark_text_style_row, textvariable=self.watermark_color, width=9)
        self.watermark_color_entry.pack(side="left")
        self.watermark_outline_check = Checkbutton(watermark_text_style_row, text="描边", variable=self.watermark_outline)
        self.watermark_outline_check.pack(side="left", padx=(8, 0))
        self.watermark_shadow_check = Checkbutton(watermark_text_style_row, text="阴影", variable=self.watermark_shadow)
        self.watermark_shadow_check.pack(side="left", padx=(8, 0))
        self.watermark_common_controls.extend([
            self.watermark_text_radio, self.watermark_logo_radio, self.watermark_position_combo,
            self.watermark_opacity_spin, self.watermark_margin_spin, self.watermark_scale_spin, self.watermark_angle_spin,
        ])
        self.watermark_text_controls.extend([
            self.watermark_text_entry, self.watermark_font_spin, self.watermark_color_entry,
            self.watermark_outline_check, self.watermark_shadow_check,
        ])
        self.watermark_logo_controls.append(self.watermark_logo_button)

        danger_box = LabelFrame(opts, text="危险操作", font=section_font)
        danger_box.pack(fill="x", pady=(6, 0))
        danger_row = Frame(danger_box)
        danger_row.pack(fill="x", padx=8, pady=5)
        Checkbutton(danger_row, text="覆盖已存在文件", variable=self.overwrite, fg="#9a6400").pack(side="left")
        Checkbutton(danger_row, text="成功后删除原图", variable=self.delete_originals, fg="#b42318", font=("Microsoft YaHei UI", 9, "bold")).pack(side="left", padx=(20, 0))

        for var in (self.rename_template, self.rename_prefix, self.rename_suffix, self.rename_find, self.rename_replace, self.target_size):
            var.trace_add("write", lambda *_args: self._schedule_scan())
        for var in (self.rename_start, self.resize_width, self.resize_height, self.resize_scale_percent):
            var.trace_add("write", lambda *_args: self._schedule_scan())
        for var in (
            self.progressive_jpg, self.alpha_bg, self.quality, self.compression_mode,
            self.compression_enabled, self.format_conversion_enabled, self.size_compress_enabled,
            self.rename_enabled, self.watermark_enabled, self.watermark_type, self.watermark_position,
            self.watermark_opacity,
        ):
            var.trace_add("write", lambda *_args: self._update_workflow_summary())

        self.status_frame = Frame(main, height=54)
        self.status_frame.pack(fill="x", pady=(6, 0))
        self.status_frame.pack_propagate(False)
        self.status_line_frame = Frame(self.status_frame)
        self.status_line_frame.pack(fill="x")
        self.task_line_frame = Frame(self.status_frame)
        self.task_line_frame.pack(fill="x", pady=(2, 0))
        Label(self.task_line_frame, textvariable=self.task_current_file_text, anchor="w").pack(side="left")
        Label(self.task_line_frame, text="  |  ").pack(side="left")
        Label(self.task_line_frame, textvariable=self.task_current_step_text, anchor="w", fg="#0b5cad", font=self.status_number_font).pack(side="left")
        Label(self.task_line_frame, text="  |  ").pack(side="left")
        Label(self.task_line_frame, textvariable=self.task_progress_text, anchor="w").pack(side="left")
        self._set_status_message("请选择图片或文件夹。")

        bottom = Frame(main, height=44)
        bottom.pack(fill="x", pady=(4, 8))
        bottom.pack_propagate(False)
        self.progress = ttk.Progressbar(bottom, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, pady=(14, 12))
        self.start_button = Button(
            bottom,
            text="开始转换",
            command=self.start_convert,
            width=18,
            bg="#0b5cad",
            fg="white",
            activebackground="#084a8d",
            activeforeground="white",
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        self.start_button.pack(side="left", fill="y", padx=(10, 0), pady=(4, 4))
        for drop_widget in (preview, self.tree, self.grid_canvas):
            self._enable_batch_drop(drop_widget)
        self._build_single_editor_tab(module_font)
        self._on_output_format_change()
        self.root.after(220, self._set_initial_panes)
        self._bind_shortcuts()

    def _make_collapsible_panel(self, parent: Frame, text: str, variable: BooleanVar, command, panel_key: str) -> tuple[Frame, Frame]:
        panel = Frame(parent, bd=1, relief="groove", bg="#f3f4f6")
        panel.pack(fill="x", pady=6)
        header = Frame(panel, bg="#f3f4f6")
        header.pack(fill="x", padx=8, pady=5)
        self.parameter_toggle_buttons[panel_key] = Button(
            header,
            text="▼" if self.parameter_panel_expanded.get(panel_key, False) else "▶",
            width=2,
            command=lambda key=panel_key: self._toggle_parameter_panel(key),
        )
        self.parameter_toggle_buttons[panel_key].pack(side="left")
        Label(header, text=text, font=("Microsoft YaHei UI", 10, "bold"), bg="#f3f4f6").pack(side="left", padx=(4, 0))
        Checkbutton(header, text="启用", variable=variable, command=command, bg="#f3f4f6", activebackground="#f3f4f6").pack(side="left", padx=(8, 0))
        Label(header, textvariable=self.parameter_summary_vars[panel_key], fg="#667085", bg="#f3f4f6", font=("Microsoft YaHei UI", 9), width=28, anchor="w").pack(side="left", padx=(10, 0))
        body = Frame(panel)
        self.parameter_panels[panel_key] = panel
        self.parameter_panel_bodies[panel_key] = body
        if self.parameter_panel_expanded.get(panel_key, False):
            body.pack(fill="x", padx=0, pady=(0, 6))
        return panel, body

    def _toggle_parameter_panel(self, key: str) -> None:
        self._set_parameter_panel_expanded(key, not self.parameter_panel_expanded.get(key, False))

    def _set_parameter_panel_expanded(self, key: str, expanded: bool) -> None:
        self.parameter_panel_expanded[key] = expanded
        button = self.parameter_toggle_buttons.get(key)
        if button:
            button.config(text="▼" if expanded else "▶")
        body = self.parameter_panel_bodies.get(key)
        if not body:
            return
        if expanded:
            if not body.winfo_manager():
                body.pack(fill="x", padx=0, pady=(0, 6))
        else:
            body.pack_forget()
        try:
            self.parameter_panels[key].update_idletasks()
        except Exception:
            pass

    def _expand_parameter_panel(self, key: str) -> None:
        for panel_key in self.parameter_panel_expanded:
            self._set_parameter_panel_expanded(panel_key, panel_key == key)
        panel = self.parameter_panels.get(key)
        if panel:
            panel.focus_set()

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Return>", self._shortcut_enter)
        self.root.bind("<Escape>", self._shortcut_escape)
        self.root.bind("<Control-s>", self._shortcut_save_single)
        self.root.bind("<Control-S>", self._shortcut_save_single)
        self.root.bind("<Control-v>", self._shortcut_paste_single)
        self.root.bind("<Control-V>", self._shortcut_paste_single)
        self.root.bind("<Key-r>", self._shortcut_reset_single)
        self.root.bind("<Key-R>", self._shortcut_reset_single)
        self.root.bind_all("<Button-1>", self._blur_text_input_on_outside_click, add="+")

    def _blur_text_input_on_outside_click(self, event) -> None:
        widget = event.widget
        if self._is_text_input_widget(widget):
            return
        try:
            top = widget.winfo_toplevel()
            top.focus_set()
        except Exception:
            pass

    def _is_text_input_widget(self, widget) -> bool:
        input_classes = {"Entry", "TEntry", "Spinbox", "TSpinbox", "Combobox", "TCombobox", "Listbox"}
        current = widget
        while current is not None:
            try:
                if current.winfo_class() in input_classes:
                    return True
                current = current.master
            except Exception:
                return False
        return False

    def _shortcut_enter(self, _event) -> str | None:
        if self.notebook.index("current") == 0:
            self.start_convert()
            return "break"
        return None

    def _shortcut_escape(self, _event) -> str:
        return "break"

    def _set_status_message(self, message: str) -> None:
        self.status_text.set(message)
        if not hasattr(self, "status_line_frame"):
            return
        for child in self.status_line_frame.winfo_children():
            child.destroy()
        Label(self.status_line_frame, text=message, anchor="w").pack(side="left", fill="y")

    def _set_status_parts(self, parts: list[tuple[str, bool]]) -> None:
        self.status_text.set("".join(text for text, _highlight in parts))
        if not hasattr(self, "status_line_frame"):
            return
        for child in self.status_line_frame.winfo_children():
            child.destroy()
        for text, highlight in parts:
            options = {"text": text, "anchor": "w"}
            if highlight:
                options.update({"fg": "#0b5cad", "font": self.status_number_font})
            Label(self.status_line_frame, **options).pack(side="left", fill="y")

    def _set_task_status(self, current_file: str = "-", current_step: str = "等待开始转换", progress_text: str = "0%") -> None:
        self.task_current_file_text.set(f"当前文件：{current_file or '-'}")
        self.task_current_step_text.set(f"当前步骤：{current_step or '等待开始转换'}")
        self.task_progress_text.set(f"总进度：{progress_text}")

    def _update_start_button_state(self) -> None:
        if not hasattr(self, "start_button"):
            return
        state = "disabled" if self.target_conflict_error else "normal"
        selected = sum(1 for job in self.jobs if job.selected)
        self.start_button.config(state=state, text=f"开始转换（{selected}张）" if selected else "开始转换")

    def _set_initial_panes(self) -> None:
        try:
            preview_total = self.preview_panes.winfo_width()
            if preview_total > 0:
                self.preview_panes.sash_place(0, int(preview_total * 0.32), 0)
        except Exception:
            pass

    def _set_preview_zoom(self, value: int | float) -> None:
        value = max(60, min(180, int(float(value))))
        self.preview_zoom_updating = True
        self.preview_zoom.set(value)
        self.preview_zoom_updating = False
        self.preview_zoom_text.set(f"{value}%")
        self.preview_zoom_after_id = None
        self._populate_grid()

    def _render_preview_zoom_from_slider(self, value: int, generation: int) -> None:
        if generation != self.preview_zoom_generation:
            return
        self.preview_zoom_text.set(f"{value}%")
        self.preview_zoom_after_id = None
        self._populate_grid()

    def _on_preview_zoom_slide(self, value: str) -> None:
        if self.preview_zoom_updating:
            return
        value_int = max(60, min(180, int(float(value))))
        self.preview_zoom_text.set(f"{value_int}%")
        self.preview_zoom_generation += 1
        generation = self.preview_zoom_generation
        if self.preview_zoom_after_id:
            self.root.after_cancel(self.preview_zoom_after_id)
        self.preview_zoom_after_id = self.root.after(160, lambda: self._render_preview_zoom_from_slider(value_int, generation))

    def _fit_preview_width(self) -> None:
        width = max(360, self.grid_canvas.winfo_width())
        target_columns = 2 if width >= 560 else 1
        zoom = int((width / target_columns) / 320 * 100)
        self._set_preview_zoom(zoom)

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
            filetypes=[("Image files", "*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff *.heic *.heif"), ("All files", "*.*")],
        )
        if files:
            self.mode.set("files")
            self.input_paths = [Path(p) for p in files]
            self.input_text.set(f"已选择 {len(files)} 个文件")
            if not self.output_text.get():
                self.output_text.set(str(self.input_paths[0].parent / "converted_images"))
            self.scan_jobs()

    def choose_watermark_logo(self) -> None:
        path = filedialog.askopenfilename(
            title="选择水印 Logo",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff"), ("All files", "*.*")],
        )
        if path:
            self.watermark_logo.set(path)
            self.watermark_custom_x.set(-1.0)
            self.watermark_custom_y.set(-1.0)

    def _clear_custom_watermark_position(self) -> None:
        self.watermark_custom_x.set(-1.0)
        self.watermark_custom_y.set(-1.0)

    def _normalize_rename_rules(self, raw_rules: object) -> list[tuple[str, str]]:
        rules: list[tuple[str, str]] = []
        if isinstance(raw_rules, list):
            for item in raw_rules:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    find, repl = str(item[0]), str(item[1])
                elif isinstance(item, dict):
                    find, repl = str(item.get("find", "")), str(item.get("replace", ""))
                else:
                    continue
                if find:
                    rules.append((find, repl))
        return rules

    def _update_rename_rules_summary(self) -> None:
        self.rename_rules_summary.set(f"更多替换 {len(self.rename_replace_rules)} 条")

    def open_rename_rules_editor(self) -> None:
        win = Toplevel(self.root)
        win.title("批量替换规则")
        win.geometry("620x420")
        win.transient(self.root)
        rules: list[tuple[str, str]] = []
        if self.rename_find.get():
            rules.append((self.rename_find.get(), self.rename_replace.get()))
        rules.extend(self.rename_replace_rules)

        top = Frame(win, padx=10, pady=10)
        top.pack(fill="both", expand=True)
        tree = ttk.Treeview(top, columns=("find", "replace"), show="headings", height=10)
        tree.heading("find", text="查找")
        tree.heading("replace", text="替换为")
        tree.column("find", width=220, stretch=True)
        tree.column("replace", width=220, stretch=True)
        tree.pack(fill="both", expand=True)

        form = Frame(top)
        form.pack(fill="x", pady=(10, 0))
        find_var = StringVar()
        replace_var = StringVar()
        Label(form, text="查找").pack(side="left")
        Entry(form, textvariable=find_var, width=22).pack(side="left", padx=(4, 10))
        Label(form, text="替换为").pack(side="left")
        Entry(form, textvariable=replace_var, width=22).pack(side="left", padx=(4, 10))

        def refresh() -> None:
            tree.delete(*tree.get_children())
            for index, (find, repl) in enumerate(rules):
                tree.insert("", "end", iid=str(index), values=(find, repl))

        def load_selected(_event=None) -> None:
            selected = tree.selection()
            if not selected:
                return
            index = int(selected[0])
            if 0 <= index < len(rules):
                find_var.set(rules[index][0])
                replace_var.set(rules[index][1])

        def add_rule() -> None:
            find = find_var.get()
            if not find:
                messagebox.showwarning("缺少查找内容", "请先输入要查找的文本。", parent=win)
                return
            rules.append((find, replace_var.get()))
            find_var.set("")
            replace_var.set("")
            refresh()

        def update_rule() -> None:
            selected = tree.selection()
            if not selected:
                messagebox.showwarning("未选择规则", "请先选择要修改的规则。", parent=win)
                return
            find = find_var.get()
            if not find:
                messagebox.showwarning("缺少查找内容", "请先输入要查找的文本。", parent=win)
                return
            index = int(selected[0])
            if 0 <= index < len(rules):
                rules[index] = (find, replace_var.get())
                refresh()
                tree.selection_set(str(index))

        def remove_rule() -> None:
            selected = tree.selection()
            if not selected:
                return
            for iid in sorted((int(item) for item in selected), reverse=True):
                if 0 <= iid < len(rules):
                    rules.pop(iid)
            refresh()

        def move_rule(delta: int) -> None:
            selected = tree.selection()
            if not selected:
                return
            index = int(selected[0])
            new_index = index + delta
            if not (0 <= index < len(rules) and 0 <= new_index < len(rules)):
                return
            rules[index], rules[new_index] = rules[new_index], rules[index]
            refresh()
            tree.selection_set(str(new_index))

        def save_rules() -> None:
            if rules:
                self.rename_find.set(rules[0][0])
                self.rename_replace.set(rules[0][1])
                self.rename_replace_rules = list(rules[1:])
            else:
                self.rename_find.set("")
                self.rename_replace.set("")
                self.rename_replace_rules = []
            self._update_rename_rules_summary()
            self.scan_jobs()
            win.destroy()

        Button(form, text="添加", command=add_rule, width=8).pack(side="left")
        Button(form, text="更新", command=update_rule, width=8).pack(side="left", padx=(6, 0))
        actions = Frame(top)
        actions.pack(fill="x", pady=(10, 0))
        Button(actions, text="删除", command=remove_rule, width=8).pack(side="left")
        Button(actions, text="上移", command=lambda: move_rule(-1), width=8).pack(side="left", padx=(8, 0))
        Button(actions, text="下移", command=lambda: move_rule(1), width=8).pack(side="left", padx=(8, 0))
        Button(actions, text="取消", command=win.destroy, width=10).pack(side="right")
        Button(actions, text="保存规则", command=save_rules, width=12, bg="#0b5cad", fg="white").pack(side="right", padx=(0, 8))
        tree.bind("<<TreeviewSelect>>", load_selected)
        refresh()
        win.update_idletasks()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry(f"620x420+{max(0, (sw - 620) // 2)}+{max(0, (sh - 420) // 2)}")

    def _on_output_format_change(self) -> None:
        is_jpg = self.output_format.get() == "jpg"
        if not is_jpg:
            self.progressive_jpg.set(False)
        if self.output_format.get() == "png" and self.compression_mode.get() == "target":
            self.compression_mode.set("quality")
        self._update_control_states()
        self.scan_jobs()

    def _on_resize_mode_change(self) -> None:
        self._update_control_states()
        self.scan_jobs()

    def _on_size_compress_toggle(self) -> None:
        self._update_control_states()
        self.scan_jobs()

    def _update_control_states(self) -> None:
        out_format = self.output_format.get()
        is_jpg = out_format == "jpg"
        format_enabled = self.format_conversion_enabled.get()
        for widget in self.format_controls:
            widget.config(state="normal" if format_enabled else "disabled")
        jpg_state = "normal" if format_enabled and is_jpg else "disabled"
        for widget in (self.progressive_check, self.alpha_label, self.alpha_entry):
            widget.config(state=jpg_state)

        compression_enabled = self.size_compress_enabled.get() and self.compression_enabled.get()
        if out_format == "png" and self.compression_mode.get() == "target":
            self.compression_mode.set("quality")
        target_state = "normal" if compression_enabled and self.compression_mode.get() == "target" and out_format != "png" else "disabled"
        quality_state = "normal" if compression_enabled and self.compression_mode.get() == "quality" else "disabled"
        radio_state = "normal" if compression_enabled else "disabled"
        self.compression_quality_radio.config(state=radio_state)
        self.compression_target_radio.config(state=radio_state)
        self.quality_spin.config(state=quality_state)
        self.target_size_entry.config(state=target_state)
        self.target_size_unit.config(state=target_state)
        self.compression_hint.config(state=radio_state, text="PNG仅做无损 optimize" if compression_enabled and out_format == "png" else "")

        for row in (self.resize_none_row, self.resize_scale_row, self.resize_exact_row, self.resize_fit_row):
            row.pack_forget()
        resize_enabled = self.size_compress_enabled.get() and self.resize_enabled.get()
        self.preset_combo.config(state="readonly")
        resize_radio_state = "normal" if resize_enabled else "disabled"
        for widget in self.resize_controls:
            if isinstance(widget, ttk.Combobox):
                widget.config(state="readonly" if resize_enabled else "disabled")
            else:
                widget.config(state=resize_radio_state)
        resize_mode = self.resize_mode.get()
        if resize_enabled and resize_mode == "scale":
            self.resize_scale_row.pack(fill="x", padx=8, pady=(2, 5))
            self.resize_scale_spin.config(state="normal")
        elif resize_enabled and resize_mode == "exact":
            self.resize_exact_row.pack(fill="x", padx=8, pady=(2, 2))
            self.resize_fit_row.pack(fill="x", padx=8, pady=(0, 5))
            self.resize_width_spin.config(state="normal")
            self.resize_height_spin.config(state="normal")
            self.resize_fit_combo.config(state="readonly")
        else:
            self.resize_none_row.pack(fill="x", padx=8, pady=(2, 5))
            self.resize_scale_spin.config(state="disabled")
            self.resize_width_spin.config(state="disabled")
            self.resize_height_spin.config(state="disabled")
            self.resize_fit_combo.config(state="disabled")

        rename_state = "normal" if self.rename_enabled.get() else "disabled"
        for widget in self.rename_controls:
            widget.config(state=rename_state)

        watermark_enabled = self.watermark_enabled.get()
        common_state = "normal" if watermark_enabled else "disabled"
        common_combo_state = "readonly" if watermark_enabled else "disabled"
        text_state = "normal" if watermark_enabled and self.watermark_type.get() == "text" else "disabled"
        logo_state = "normal" if watermark_enabled and self.watermark_type.get() == "logo" else "disabled"
        for widget in self.watermark_common_controls:
            if isinstance(widget, ttk.Combobox):
                widget.config(state=common_combo_state)
            else:
                widget.config(state=common_state)
        for widget in self.watermark_text_controls:
            widget.config(state=text_state)
        for widget in self.watermark_logo_controls:
            widget.config(state=logo_state)
        if hasattr(self, "watermark_preview_button"):
            self.watermark_preview_button.config(state=common_state)

        if not HEIC_ENABLED:
            self.heic_notice.set("HEIC 需安装 pillow-heif")
        else:
            self.heic_notice.set("")
        self._update_workflow_summary()

    def _update_workflow_summary(self) -> None:
        summaries = {
            "format": self._format_module_summary(),
            "size": self._size_module_summary(),
            "rename": self._rename_module_summary(),
            "watermark": self._watermark_module_summary(),
        }
        for key, summary in summaries.items():
            self.parameter_summary_vars[key].set(summary)
        total = len(self.jobs)
        selected = sum(1 for job in self.jobs if job.selected)
        enabled_modules = len([module for module in self._workflow_modules() if module.enabled])
        self.workflow_stats_text.set(f"已选择 {selected} / {total} 张 · 启用 {enabled_modules} 个处理模块")
        self._schedule_workflow_render()

    def _format_module_summary(self) -> str:
        if not self.format_conversion_enabled.get():
            return "未启用"
        bits = [self.output_format.get().upper()]
        if self.output_format.get() == "jpg" and self.progressive_jpg.get():
            bits.append("渐进式")
        if self.output_format.get() == "jpg":
            bg = self.alpha_bg.get().strip().lower()
            bits.append("白底" if bg in {"#fff", "#ffffff", "white"} else f"背景 {self.alpha_bg.get()}")
        if self.preserve_structure.get():
            bits.append("保留目录")
        return " · ".join(bits)

    def _size_module_summary(self) -> str:
        if not self.size_compress_enabled.get():
            return "未启用"
        size_part = "原尺寸"
        if self.resize_enabled.get():
            if self.resize_mode.get() == "scale":
                size_part = f"{self._safe_int_var(self.resize_scale_percent, 100)}%"
            elif self.resize_mode.get() == "exact":
                fit_map = {"stretch": "拉伸", "pad": "留白", "crop": "裁剪"}
                fit = fit_map.get(self.resize_fit_mode.get(), self.resize_fit_mode.get())
                size_part = f"{self._safe_int_var(self.resize_width, 0)}x{self._safe_int_var(self.resize_height, 0)} · {fit}"
        if self.compression_enabled.get():
            if self.compression_mode.get() == "target":
                compress_part = f"目标 {self.target_size.get() or '-'}KB"
            else:
                compress_part = f"{self.output_format.get().upper()}质量{self._safe_int_var(self.quality, 92)}%"
        else:
            compress_part = "不压缩"
        return f"{size_part} · {compress_part}"

    def _rename_module_summary(self) -> str:
        if not self.rename_enabled.get():
            return "未启用"
        template = self.rename_template.get().strip() or "{name}"
        rules = len(self.rename_replace_rules) + (1 if self.rename_find.get() else 0)
        return f"{template} · 替换 {rules} 条"

    def _watermark_module_summary(self) -> str:
        if not self.watermark_enabled.get():
            return "未启用"
        wm_type = "文字" if self.watermark_type.get() == "text" else "Logo"
        return f"{wm_type} · {self.watermark_position.get()} · {self._safe_int_var(self.watermark_opacity, 45)}%"

    def _workflow_modules(self) -> list[WorkflowModule]:
        return [
            WorkflowModule("format", "格式与输出", self.format_conversion_enabled.get(), self._format_module_summary(), "format"),
            WorkflowModule("size", "尺寸与压缩", self.size_compress_enabled.get(), self._size_module_summary(), "size"),
            WorkflowModule("rename", "批量重命名", self.rename_enabled.get(), self._rename_module_summary(), "rename"),
            WorkflowModule("watermark", "批量水印", self.watermark_enabled.get(), self._watermark_module_summary(), "watermark"),
        ]

    def _schedule_workflow_render(self) -> None:
        if self.workflow_ui_after_id:
            self.root.after_cancel(self.workflow_ui_after_id)
        self.workflow_ui_after_id = self.root.after(80, self._render_workflow_cards)

    def _render_workflow_cards(self) -> None:
        self.workflow_ui_after_id = None
        if not hasattr(self, "workflow_cards_frame"):
            return
        for child in self.workflow_cards_frame.winfo_children():
            child.destroy()
        self.workflow_cards.clear()
        enabled_modules = [module for module in self._workflow_modules() if module.enabled]
        if not enabled_modules:
            Label(self.workflow_cards_frame, text="未启用处理模块，当前仅扫描和预览图片。", fg="#666", anchor="w").pack(fill="x", pady=3)
            return
        for index, module in enumerate(enabled_modules, start=1):
            active = module.id == self.active_workflow_module_id
            node = Frame(self.workflow_cards_frame, bg="#f5f5f5")
            node.pack(fill="x", pady=(0, 4))
            rail = Frame(node, width=28, bg="#f5f5f5")
            rail.pack(side="left", fill="y")
            rail.pack_propagate(False)
            Label(
                rail,
                text=str(index),
                fg="#0b5cad" if active else "#98a2b3",
                bg="#f5f5f5",
                font=("Microsoft YaHei UI", 9, "bold" if active else "normal"),
            ).pack(anchor="n", pady=(5, 0))
            if index < len(enabled_modules):
                Label(rail, text="│", fg="#d0d5dd", bg="#f5f5f5").pack(anchor="n")
            card_bg = "#eaf3ff" if active else "#ffffff"
            card_fg = "#0b5cad" if active else "#344054"
            card = Frame(node, bd=1, relief="solid", bg=card_bg, padx=8, pady=5)
            card.pack(side="left", fill="x", expand=True)
            Button(
                card,
                text=module.name,
                command=lambda key=module.panel_key: self._expand_parameter_panel(key),
                anchor="w",
                relief="flat",
                bg=card_bg,
                fg=card_fg,
                activebackground=card_bg,
                activeforeground=card_fg,
                font=("Microsoft YaHei UI", 9, "bold" if active else "normal"),
            ).pack(fill="x")
            Label(card, text=module.summary, anchor="w", fg="#475467", bg=card_bg, wraplength=500).pack(fill="x", pady=(2, 0))
            self.workflow_cards[module.id] = card

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

    def open_watermark_editor(self) -> None:
        selected_jobs = [job for job in self.jobs if job.selected]
        if not selected_jobs:
            messagebox.showwarning("没有样图", "请先在预览区勾选一张图片。")
            return
        if self.watermark_type.get() == "logo" and not Path(self.watermark_logo.get().strip()).exists():
            messagebox.showwarning("没有 Logo", "请先选择水印 Logo 文件。")
            return
        if self.watermark_type.get() == "logo":
            try:
                with Image.open(Path(self.watermark_logo.get().strip())) as logo:
                    logo.verify()
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("Logo 不可读", f"当前 Logo 文件无法作为水印读取，请换一张图片。\n\n{exc}")
                return
        if self.watermark_type.get() == "text" and not self.watermark_text.get().strip():
            messagebox.showwarning("没有文字", "请先输入文字水印内容。")
            return
        errors: list[str] = []
        for selected in selected_jobs:
            try:
                base = self._prepare_watermark_preview_image(selected.source)
                if errors:
                    self._set_status_message(f"水印预览已跳过 {len(errors)} 张不可读样图，使用 {selected.source.name}。")
                WatermarkEditor(self, base, selected.source)
                return
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{selected.source.name}: {exc}")
        shown = "\n".join(errors[:5])
        more = "" if len(errors) <= 5 else f"\n... 还有 {len(errors) - 5} 张不可读"
        messagebox.showerror("无法预览", f"已勾选图片里没有可用于预览的样图。\n\n{shown}{more}")

    def _prepare_watermark_preview_image(self, source: Path) -> Image.Image:
        if source.suffix.lower() in {".heic", ".heif"} and not HEIC_ENABLED:
            raise ValueError("当前环境未安装 HEIC 支持库，无法预览 HEIC/HEIF 图片")
        bg = self._parse_color(self.alpha_bg.get())
        with Image.open(source) as im:
            im = self._resize_image(im, bg)
            if self._effective_output_format(source) == "jpg":
                im = self._flatten_alpha(im, bg)
            return im.convert("RGBA")

    def scan_jobs(self) -> None:
        for job in self.jobs:
            self.selection_state[self._source_key(job.source)] = job.selected
        self.jobs.clear()
        self._clear_preview()
        if not self.input_paths:
            self.target_conflict_error = ""
            self._update_start_button_state()
            self._set_status_message("请选择输入。")
            return
        out_root = Path(self.output_text.get().strip()) if self.output_text.get().strip() else None
        if not out_root:
            self.target_conflict_error = ""
            self._update_start_button_state()
            self._set_status_message("请选择输出目录。")
            return
        base_root = self._base_root()
        try:
            visible_index = int(self.rename_start.get())
        except Exception:
            visible_index = 1
        for src in self._collect_sources(out_root):
            if not self._matches_filters(src):
                continue
            target = self._build_target_path(src, out_root, base_root, self._output_extension(src), visible_index)
            selected = self.selection_state.get(self._source_key(src), True)
            self.jobs.append(ConvertJob(src, target, selected=selected))
            visible_index += 1
        self._auto_resolve_same_stem_extension_conflicts()
        self.target_conflict_error = self._selected_target_error()
        self._populate_tree()
        self._populate_grid()
        self._update_selected_status()
        self._update_start_button_state()
        self.progress.config(value=0, maximum=max(1, len(self.jobs)))
        self._set_task_status("-", "等待开始转换", "0%")

    @staticmethod
    def _source_key(source: Path) -> str:
        try:
            return str(source.resolve()).lower()
        except OSError:
            return str(source).lower()

    def _build_target_path(self, src: Path, out_root: Path, base_root: Path | None, output_ext: str, index: int) -> Path:
        stem = self._renamed_stem(src, index)
        if self.preserve_structure.get() and base_root and src.is_relative_to(base_root):
            return (out_root / src.relative_to(base_root)).with_name(stem + output_ext)
        return out_root / (stem + output_ext)

    def _effective_output_format(self, source: Path) -> str:
        if self.format_conversion_enabled.get():
            return self.output_format.get()
        suffix = source.suffix.lower()
        if suffix in {".jpg", ".jpeg"}:
            return "jpg"
        if suffix == ".png":
            return "png"
        if suffix == ".webp":
            return "webp"
        if suffix in {".bmp"}:
            return "bmp"
        if suffix in {".tif", ".tiff"}:
            return "tiff"
        return "jpg"

    def _output_extension(self, source: Path) -> str:
        if self.format_conversion_enabled.get():
            return "." + self.output_format.get()
        suffix = source.suffix.lower()
        if suffix in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}:
            return suffix
        return ".jpg"

    def _selected_target_error(self) -> str:
        return self._target_error_for_jobs([job for job in self.jobs if job.selected])

    def _target_error_for_jobs(self, jobs: list[ConvertJob]) -> str:
        seen: dict[str, ConvertJob] = {}
        conflicts: list[tuple[ConvertJob, ConvertJob]] = []
        invalids: list[ConvertJob] = []
        for job in jobs:
            if not job.target.name or any(ch in job.target.name for ch in INVALID_FILENAME_CHARS):
                invalids.append(job)
                continue
            key = self._target_key(job.target)
            previous = seen.get(key)
            if previous:
                conflicts.append((previous, job))
            else:
                seen[key] = job
        if invalids:
            return f"目标文件名无效：{invalids[0].target.name}"
        if conflicts:
            first, second = conflicts[0]
            return f"仍有目标文件冲突：{first.source.name} 与 {second.source.name} -> {first.target.name}"
        return ""

    def _auto_resolve_same_stem_extension_conflicts(self) -> None:
        changed = True
        while changed:
            changed = False
            groups: dict[str, list[ConvertJob]] = {}
            for job in self.jobs:
                groups.setdefault(self._target_key(job.target), []).append(job)
            for group in groups.values():
                if len(group) < 2:
                    continue
                if not self._can_suffix_by_source_extension(group):
                    continue
                used = {self._target_key(job.target) for job in self.jobs if job not in group}
                for job in group:
                    suffix = job.source.suffix.lower().lstrip(".") or "file"
                    base_target = job.target.with_name(f"{job.target.stem}_{suffix}{job.target.suffix}")
                    target = base_target
                    counter = 2
                    while self._target_key(target) in used:
                        target = base_target.with_name(f"{base_target.stem}_{counter}{base_target.suffix}")
                        counter += 1
                    used.add(self._target_key(target))
                    if self._target_key(target) != self._target_key(job.target):
                        job.target = target
                        changed = True

    @staticmethod
    def _can_suffix_by_source_extension(jobs: list[ConvertJob]) -> bool:
        source_stems = {job.source.stem.lower() for job in jobs}
        source_parents = {str(job.source.parent.resolve()).lower() for job in jobs}
        target_parents = {str(job.target.parent.resolve()).lower() for job in jobs}
        suffixes = [job.source.suffix.lower().lstrip(".") for job in jobs]
        return len(source_stems) == 1 and len(source_parents) == 1 and len(target_parents) == 1 and len(set(suffixes)) == len(suffixes)

    @staticmethod
    def _target_key(target: Path) -> str:
        try:
            return str(target.resolve()).lower()
        except OSError:
            return str(target).lower()

    def _renamed_stem(self, src: Path, index: int) -> str:
        if not self.rename_enabled.get():
            return self._sanitize_stem(src.stem) or src.stem
        template = self.rename_template.get().strip() or "{name}"
        date_text = datetime.now().strftime("%Y%m%d")
        parent = src.parent.name
        values = {
            "name": src.stem,
            "parent": parent,
            "index": str(index),
            "index2": f"{index:02d}",
            "index3": f"{index:03d}",
            "date": date_text,
        }
        try:
            stem = template.format(**values)
        except Exception:
            stem = src.stem
        stem = f"{self.rename_prefix.get()}{stem}{self.rename_suffix.get()}"
        find = self.rename_find.get()
        if find:
            stem = stem.replace(find, self.rename_replace.get())
        for find_text, replace_text in self.rename_replace_rules:
            if find_text:
                stem = stem.replace(find_text, replace_text)
        return self._sanitize_stem(stem) or src.stem

    @staticmethod
    def _sanitize_stem(stem: str) -> str:
        cleaned = "".join("_" if ch in INVALID_FILENAME_CHARS else ch for ch in stem).strip().rstrip(".")
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned[:180]

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
            job.tree_id = self.tree.insert(parent_id, "end", text=rel.name, image=self.tree_icons[("file", "checked" if job.selected else "unchecked")])
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
        zoom = max(60, min(180, self.preview_zoom.get())) / 100
        thumb_size = (max(120, int(176 * zoom)), max(86, int(126 * zoom)))
        image_size = (thumb_size[0] + 8, thumb_size[1] + 6)
        text_width = max(18, int(25 * zoom))
        var = BooleanVar(value=job.selected)
        self.card_vars[idx] = var
        card = Frame(self.grid_inner, bd=1, relief="solid", padx=8, pady=8, bg="#f5f5f5")
        self.card_frames[idx] = card
        top = Frame(card, bg="#f5f5f5")
        top.pack(fill="x")
        Checkbutton(top, variable=var, command=lambda i=idx: self._set_job_selected(i, self.card_vars[i].get()), bg="#f5f5f5", activebackground="#eaf3ff").pack(side="left")
        Button(top, text="编辑", command=lambda i=idx: self.load_single_image(self.jobs[i].source), width=6).pack(side="right")
        thumb = self._get_thumbnail(job.source, thumb_size)
        image_label = Label(card, image=thumb, width=image_size[0], height=image_size[1], bg="#f7f7f4")
        image_label.image = thumb  # type: ignore[attr-defined]
        image_label.pack(fill="x", pady=(4, 0))
        rel = self._display_source_rel(job.source)
        name_label = Label(card, text=rel.name, width=text_width, anchor="center", bg="#f5f5f5")
        name_label.pack(pady=(4, 0))
        source_format = self._source_format_label(job.source)
        target_format = self._effective_output_format(job.source).upper()
        format_label = Label(card, text=f"{source_format} → {target_format}", width=text_width, anchor="center", fg="#666", bg="#f5f5f5")
        format_label.pack()
        target_label = Label(card, text=f"输出：{job.target.name}", width=text_width, anchor="center", fg="#0b5cad", bg="#f5f5f5")
        target_label.pack()
        status_label = Label(card, text="", width=text_width, anchor="center", fg="#b42318", bg="#f5f5f5")
        if job.status == "failed":
            status_label.config(text="失败：点击查看原因")
            status_label.pack()
        elif job.status == "done":
            status_label.config(text="已完成", fg="#667085")
            status_label.pack()
        elif job.status == "skipped":
            status_label.config(text="已跳过", fg="#9a6400")
            status_label.pack()
        card.bind("<Button-1>", lambda _e, i=idx: self._schedule_card_preview(i))
        self._bind_card_hover(card)
        for clickable in (image_label, name_label, format_label, target_label, status_label):
            clickable.bind("<Button-1>", lambda _e, i=idx: self._schedule_card_preview(i))
        status_label.bind("<Button-1>", lambda _e, i=idx: self._show_job_error(i))
        image_label.bind("<Double-Button-1>", lambda _e, i=idx: self._open_card_editor(i))
        for widget in [card, top, image_label, *card.winfo_children()]:
            widget.bind("<MouseWheel>", self._on_grid_mousewheel, add="+")

    @staticmethod
    def _source_format_label(path: Path) -> str:
        suffix = path.suffix.lower().lstrip(".")
        return "JPG" if suffix == "jpeg" else (suffix.upper() or "FILE")

    def _show_job_error(self, job_index: int) -> str:
        if 0 <= job_index < len(self.jobs):
            job = self.jobs[job_index]
            if job.message:
                messagebox.showerror("图片处理失败", f"源文件：\n{job.source}\n\n目标文件：\n{job.target}\n\n原因：\n{job.message}")
        return "break"

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
        canvas = Image.new("RGB", size, (247, 247, 244))
        try:
            if path.suffix.lower() in {".heic", ".heif"} and not HEIC_ENABLED:
                raise ValueError("HEIC未启用")
            with Image.open(path) as im:
                im = im.convert("RGB")
                im.thumbnail(size, Image.Resampling.LANCZOS)
                canvas.paste(im, ((size[0] - im.width) // 2, (size[1] - im.height) // 2))
        except Exception:
            draw = ImageDraw.Draw(canvas)
            draw.rectangle((10, 10, size[0] - 10, size[1] - 10), outline="#b42318", width=2)
            draw.text((18, size[1] // 2 - 8), "无法预览", fill="#b42318")
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
        zoom = max(60, min(180, self.preview_zoom.get())) / 100
        card_width = max(220, int(320 * zoom))
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
        self.selection_state[self._source_key(job.source)] = selected
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
        self.target_conflict_error = self._selected_target_error()
        self._update_start_button_state()
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
        self._update_workflow_summary()
        if self.target_conflict_error:
            self._set_status_parts([
                ("目标文件冲突：", False),
                (self.target_conflict_error, True),
                ("。请调整重命名规则。", False),
            ])
            return
        selected = sum(1 for job in self.jobs if job.selected)
        enabled_steps = len([module for module in self._workflow_modules() if module.enabled])
        self._set_status_parts([
            ("已扫描 ", False),
            (str(len(self.jobs)), True),
            (" 张图片，已选择 ", False),
            (str(selected), True),
            (" 张，启用 ", False),
            (str(enabled_steps), True),
            (" 个处理模块。", False),
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

    def _processing_steps_for_job(self, job: ConvertJob) -> list[ProcessingStep]:
        steps = []
        if self.rename_enabled.get():
            steps.append(ProcessingStep("rename", "应用命名规则", "rename"))
        steps.extend([
            ProcessingStep("prepare_output", "准备输出路径", "format"),
            ProcessingStep("read_image", "读取图片", "format"),
            ProcessingStep("fix_orientation", "修正图片方向", "format"),
        ])
        if self.size_compress_enabled.get() and self.resize_enabled.get() and self.resize_mode.get() != "none":
            steps.append(ProcessingStep("resize", "调整尺寸", "size"))
        if self.watermark_enabled.get():
            steps.append(ProcessingStep("watermark", "添加水印", "watermark"))
        steps.extend([
            ProcessingStep("convert_mode", "转换颜色模式", "format"),
            ProcessingStep("encode_save", f"编码保存 {self._effective_output_format(job.source).upper()}", "format"),
            ProcessingStep("verify_output", "验证输出文件", "format"),
        ])
        if self.delete_originals.get():
            steps.append(ProcessingStep("delete_original", "删除原图", "format"))
        steps.append(ProcessingStep("complete", "完成", "format"))
        return steps

    def _emit_processing_step(
        self,
        job: ConvertJob,
        steps: list[ProcessingStep],
        current_index: int,
        completed_steps: int,
        total_steps: int,
        status: str = "running",
        error: str = "",
        force: bool = False,
    ) -> None:
        now = time.monotonic()
        if not force and now - self.last_task_ui_update < 0.06:
            return
        self.last_task_ui_update = now
        self.events.put((
            "step",
            {
                "job_key": self._source_key(job.source),
                "file": job.source.name,
                "steps": steps,
                "current_index": current_index,
                "completed_steps": completed_steps,
                "total_steps": max(1, total_steps),
                "status": status,
                "error": error,
            },
        ))

    def start_convert(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("正在转换", "转换任务正在运行。")
            return
        if self.target_conflict_error:
            messagebox.showerror("目标文件冲突", f"{self.target_conflict_error}\n\n请调整重命名规则后再转换。")
            return
        selected_jobs = [job for job in self.jobs if job.selected]
        if not selected_jobs:
            messagebox.showwarning("没有选中图片", "请至少勾选一张图片。")
            return
        compression_enabled = self.size_compress_enabled.get() and self.compression_enabled.get()
        if compression_enabled and self.compression_mode.get() == "target" and any(self._effective_output_format(job.source) in {"jpg", "webp"} for job in selected_jobs):
            try:
                self._parse_target_size(self.target_size.get())
            except ValueError as exc:
                messagebox.showerror("目标体积格式错误", str(exc))
                return
        target_error = self._validate_selected_targets(selected_jobs)
        if target_error:
            messagebox.showerror("目标文件冲突", target_error)
            return
        if self.delete_originals.get():
            ok = messagebox.askyesno("确认删除原图", "转换成功后会删除原图。请确认你已经备份或确实不再需要原图。")
            if not ok:
                return
        for job in self.jobs:
            job.status = "pending"
            job.message = ""
        total_steps = sum(len(self._processing_steps_for_job(job)) for job in selected_jobs)
        self.progress.config(value=0, maximum=max(1, total_steps))
        self._set_task_status("-", "等待开始转换", "0%")
        self._set_status_message("开始转换...")
        self.worker = threading.Thread(target=self._convert_worker, args=(selected_jobs,), daemon=True)
        self.worker.start()

    def _validate_selected_targets(self, selected_jobs: list[ConvertJob]) -> str:
        seen: dict[Path, Path] = {}
        for job in selected_jobs:
            target = job.target.resolve()
            if target in seen:
                return f"以下两个源文件会输出到同一个目标文件，请调整重命名规则：\n{seen[target]}\n{job.source}\n\n目标：{job.target}"
            seen[target] = job.source
            if not job.target.name or any(ch in job.target.name for ch in INVALID_FILENAME_CHARS):
                return f"目标文件名无效：\n{job.target}"
        return ""

    def _resize_report_text(self) -> str:
        if not (self.size_compress_enabled.get() and self.resize_enabled.get()):
            return "off"
        mode = self.resize_mode.get()
        if mode == "scale":
            return f"scale {self._safe_int_var(self.resize_scale_percent, 100)}%"
        if mode == "exact":
            return f"exact {self._safe_int_var(self.resize_width, 0)}x{self._safe_int_var(self.resize_height, 0)} {self.resize_fit_mode.get()}"
        return "none"

    def _convert_worker(self, selected_jobs: list[ConvertJob]) -> None:
        ok = failed = skipped = 0
        unselected = len(self.jobs) - len(selected_jobs)
        failures: list[str] = []
        started_at = time.monotonic()
        total_steps = sum(len(self._processing_steps_for_job(job)) for job in selected_jobs)
        completed_steps = 0
        report = [
            f"Image conversion report: {datetime.now():%Y-%m-%d %H:%M:%S}",
            f"Format conversion enabled: {self.format_conversion_enabled.get()}",
            f"Output format: {self.output_format.get() if self.format_conversion_enabled.get() else 'source'}",
            f"Compression enabled: {self.size_compress_enabled.get() and self.compression_enabled.get()}",
            f"Compression mode: {self.compression_mode.get() if self.size_compress_enabled.get() and self.compression_enabled.get() else 'off'}",
            f"Resize: {self._resize_report_text()}",
            f"Total: {len(self.jobs)}",
            f"Selected: {len(selected_jobs)}",
            f"Unselected: {unselected}",
            "",
        ]
        for index, job in enumerate(selected_jobs, start=1):
            steps = self._processing_steps_for_job(job)
            step_index = 0

            def emit(step_id: str, force: bool = True) -> None:
                nonlocal step_index, completed_steps
                for found_index, step in enumerate(steps):
                    if step.id == step_id:
                        step_index = found_index
                        break
                self._emit_processing_step(job, steps, step_index, completed_steps, total_steps, force=force)

            def finish_step(step_id: str) -> None:
                nonlocal completed_steps
                emit(step_id, force=True)
                completed_steps += 1
                self._emit_processing_step(job, steps, step_index, completed_steps, total_steps, force=True)

            try:
                if job.target.exists() and not self.overwrite.get():
                    skipped += 1
                    completed_steps += len(steps)
                    job.status = "skipped"
                    job.message = "目标文件已存在，未启用覆盖。"
                    report.append(f"[SKIP] {job.source} -> {job.target} (target exists)")
                else:
                    before_size = job.source.stat().st_size if job.source.exists() else 0
                    if self.rename_enabled.get():
                        finish_step("rename")
                    self._convert_one(job.source, job.target, step_callback=finish_step)
                    after_size = job.target.stat().st_size if job.target.exists() else 0
                    if self.delete_originals.get() and job.source.resolve() != job.target.resolve():
                        emit("delete_original", force=True)
                        job.source.unlink()
                        completed_steps += 1
                    ok += 1
                    job.status = "done"
                    job.message = ""
                    if completed_steps < total_steps:
                        finish_step("complete")
                    report.append(f"[OK] {job.source} -> {job.target} ({self._format_bytes(before_size)} -> {self._format_bytes(after_size)})")
            except Exception as exc:  # noqa: BLE001
                failed += 1
                completed_steps += max(0, len(steps) - sum(1 for _step in steps[: step_index + 1]))
                job.status = "failed"
                job.message = str(exc)
                self._emit_processing_step(job, steps, step_index, completed_steps, total_steps, status="failed", error=str(exc), force=True)
                message = f"{job.source} -> {job.target} ({exc})"
                failures.append(message)
                report.append(f"[FAIL] {message}")
            self.events.put(("job_status", self._source_key(job.source)))
            self.events.put(("progress", (completed_steps, total_steps, index, len(selected_jobs), ok, failed, skipped)))
        report_path = Path(self.output_text.get().strip()) / "conversion_report.txt"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("\n".join(report), encoding="utf-8")
        elapsed = time.monotonic() - started_at
        self.events.put(("done", (ok, failed, skipped, unselected, report_path, failures, elapsed)))

    def _convert_one(self, source: Path, target: Path, step_callback=None) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        if step_callback:
            step_callback("prepare_output")
        if source.suffix.lower() in {".heic", ".heif"} and not HEIC_ENABLED:
            raise ValueError("当前环境未安装 HEIC 支持库，无法读取 HEIC/HEIF 图片")
        out_format = self._effective_output_format(source)
        bg = self._parse_color(self.alpha_bg.get())
        compression_enabled = self.size_compress_enabled.get() and self.compression_enabled.get()
        target_bytes = self._parse_target_size(self.target_size.get()) if compression_enabled and self.compression_mode.get() == "target" and out_format in {"jpg", "webp"} else None
        save_quality = self._safe_int_var(self.quality, 92) if compression_enabled else 95
        with Image.open(source) as im:
            if step_callback:
                step_callback("read_image")
            im = ImageOps.exif_transpose(im)
            if step_callback:
                step_callback("fix_orientation")
            im = self._resize_image(im, bg)
            if step_callback and self.size_compress_enabled.get() and self.resize_enabled.get() and self.resize_mode.get() != "none":
                step_callback("resize")
            im = self._apply_watermark(im)
            if step_callback and self.watermark_enabled.get():
                step_callback("watermark")
            if out_format == "jpg":
                im = self._flatten_alpha(im, bg)
            elif out_format == "webp":
                im = im.convert("RGBA") if im.mode in {"RGBA", "LA", "P"} else im.convert("RGB")
            elif out_format == "png":
                im = im.convert("RGBA") if im.mode in {"RGBA", "LA", "P"} else im.convert("RGB")
            if step_callback:
                step_callback("convert_mode")
            if out_format == "jpg":
                self._save_with_quality_target(im, target, "JPEG", save_quality, target_bytes, progressive=bool(self.progressive_jpg.get()))
            elif out_format == "webp":
                self._save_with_quality_target(im, target, "WEBP", save_quality, target_bytes)
            elif out_format == "png":
                im.save(target, format="PNG", optimize=True)
            elif out_format == "bmp":
                ImageConverterApp._flatten_alpha(im, bg).save(target, format="BMP")
            elif out_format == "tiff":
                im.convert("RGBA").save(target, format="TIFF")
            else:
                raise ValueError(f"Unsupported output format: {out_format}")
            if step_callback:
                step_callback("encode_save")
        if not target.exists():
            raise ValueError("输出文件未生成")
        if step_callback:
            step_callback("verify_output")

    @staticmethod
    def _flatten_alpha(im: Image.Image, bg: tuple[int, int, int]) -> Image.Image:
        if im.mode in {"RGBA", "LA"} or (im.mode == "P" and "transparency" in im.info):
            rgba = im.convert("RGBA")
            canvas = Image.new("RGBA", rgba.size, bg + (255,))
            canvas.alpha_composite(rgba)
            return canvas.convert("RGB")
        return im.convert("RGB")

    def _resize_image(self, im: Image.Image, bg: tuple[int, int, int]) -> Image.Image:
        if not (self.size_compress_enabled.get() and self.resize_enabled.get()):
            return im
        mode = self.resize_mode.get()
        target_w = max(0, self._safe_int_var(self.resize_width, 0))
        target_h = max(0, self._safe_int_var(self.resize_height, 0))
        if mode == "none":
            return im
        rgba = im.convert("RGBA")
        if mode == "scale":
            ratio = max(1, self._safe_int_var(self.resize_scale_percent, 100)) / 100
            target_w = max(1, int(rgba.width * ratio))
            target_h = max(1, int(rgba.height * ratio))
            return rgba.resize((target_w, target_h), Image.Resampling.LANCZOS)
        if mode != "exact" or target_w <= 0 or target_h <= 0:
            return rgba
        fit = self.resize_fit_mode.get()
        if fit == "stretch":
            return rgba.resize((target_w, target_h), Image.Resampling.LANCZOS)
        if fit == "crop":
            ratio = max(target_w / rgba.width, target_h / rgba.height)
            new_size = (max(1, int(rgba.width * ratio)), max(1, int(rgba.height * ratio)))
            resized = rgba.resize(new_size, Image.Resampling.LANCZOS)
            left = max(0, (resized.width - target_w) // 2)
            top = max(0, (resized.height - target_h) // 2)
            return resized.crop((left, top, left + target_w, top + target_h))
        ratio = min(target_w / rgba.width, target_h / rgba.height)
        new_size = (max(1, int(rgba.width * ratio)), max(1, int(rgba.height * ratio)))
        resized = rgba.resize(new_size, Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (target_w, target_h), bg + (255,))
        canvas.alpha_composite(resized, ((target_w - resized.width) // 2, (target_h - resized.height) // 2))
        return canvas

    def _apply_watermark(self, im: Image.Image) -> Image.Image:
        if not self.watermark_enabled.get():
            return im
        base = im.convert("RGBA")
        layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        mark = self._make_watermark_mark(base.size)
        if mark is None:
            return im
        x, y = self._watermark_position(base.size, mark.size, max(0, self._safe_int_var(self.watermark_margin, 24)))
        layer.alpha_composite(mark, (x, y))
        base.alpha_composite(layer)
        return base

    def _make_watermark_mark(self, base_size: tuple[int, int]) -> Image.Image | None:
        opacity = max(1, min(100, self._safe_int_var(self.watermark_opacity, 45)))
        alpha = int(255 * opacity / 100)
        scale = max(5, min(500, self._safe_int_var(self.watermark_scale_percent, 100))) / 100
        if self.watermark_type.get() == "logo":
            logo_path = Path(self.watermark_logo.get().strip())
            if not logo_path.exists():
                raise ValueError("水印 Logo 文件不存在")
            with Image.open(logo_path) as logo:
                mark = logo.convert("RGBA")
                max_w = max(1, int(base_size[0] * 0.25 * scale))
                max_h = max(1, int(base_size[1] * 0.25 * scale))
                mark.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
                if alpha < 255:
                    mark_alpha = mark.getchannel("A").point(lambda value: int(value * alpha / 255))
                    mark.putalpha(mark_alpha)
        else:
            text = self.watermark_text.get().strip()
            if not text:
                return None
            font_size = max(8, int(self._safe_int_var(self.watermark_font_size, 36) * scale))
            try:
                font = ImageFont.truetype("msyh.ttc", font_size)
            except OSError:
                font = ImageFont.load_default()
            color = self._parse_color(self.watermark_color.get()) + (alpha,)
            temp = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
            draw = ImageDraw.Draw(temp)
            box = draw.textbbox((0, 0), text, font=font)
            padding = max(8, font_size // 3)
            mark = Image.new("RGBA", (box[2] - box[0] + padding * 2 + 6, box[3] - box[1] + padding * 2 + 6), (0, 0, 0, 0))
            mark_draw = ImageDraw.Draw(mark)
            text_pos = (padding, padding)
            if self.watermark_shadow.get():
                mark_draw.text((text_pos[0] + 3, text_pos[1] + 3), text, fill=(0, 0, 0, max(80, alpha // 2)), font=font)
            if self.watermark_outline.get():
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    mark_draw.text((text_pos[0] + dx, text_pos[1] + dy), text, fill=(0, 0, 0, alpha), font=font)
            mark_draw.text(text_pos, text, fill=color, font=font)
        angle = self._safe_int_var(self.watermark_angle, 0)
        if angle:
            mark = mark.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
        return mark

    def _watermark_position(self, base_size: tuple[int, int], mark_size: tuple[int, int], margin: int) -> tuple[int, int]:
        bw, bh = base_size
        mw, mh = mark_size
        custom_x = float(self.watermark_custom_x.get())
        custom_y = float(self.watermark_custom_y.get())
        if custom_x >= 0 and custom_y >= 0:
            return (
                max(0, min(bw - mw, int((bw - mw) * custom_x))),
                max(0, min(bh - mh, int((bh - mh) * custom_y))),
            )
        mapping = {
            "左上": (margin, margin),
            "上中": ((bw - mw) // 2, margin),
            "右上": (bw - mw - margin, margin),
            "左中": (margin, (bh - mh) // 2),
            "居中": ((bw - mw) // 2, (bh - mh) // 2),
            "右中": (bw - mw - margin, (bh - mh) // 2),
            "左下": (margin, bh - mh - margin),
            "下中": ((bw - mw) // 2, bh - mh - margin),
            "右下": (bw - mw - margin, bh - mh - margin),
        }
        x, y = mapping.get(self.watermark_position.get(), mapping["右下"])
        return max(0, x), max(0, y)

    def _save_with_quality_target(
        self,
        im: Image.Image,
        target: Path,
        image_format: str,
        quality: int,
        target_bytes: int | None,
        progressive: bool = False,
    ) -> None:
        quality = max(1, min(100, quality))
        save_kwargs: dict[str, object] = {"quality": quality, "optimize": True}
        if image_format == "JPEG":
            save_kwargs["progressive"] = progressive
        elif image_format == "WEBP":
            save_kwargs["method"] = 6
        if not target_bytes:
            im.save(target, format=image_format, **save_kwargs)
            return
        best_data: bytes | None = None
        best_quality = quality
        low, high = 10, quality
        while low <= high:
            mid = (low + high) // 2
            attempt_kwargs = dict(save_kwargs)
            attempt_kwargs["quality"] = mid
            buffer = io.BytesIO()
            im.save(buffer, format=image_format, **attempt_kwargs)
            data = buffer.getvalue()
            if len(data) <= target_bytes:
                best_data = data
                best_quality = mid
                low = mid + 1
            else:
                high = mid - 1
        if best_data is None:
            buffer = io.BytesIO()
            attempt_kwargs = dict(save_kwargs)
            attempt_kwargs["quality"] = 10
            im.save(buffer, format=image_format, **attempt_kwargs)
            best_data = buffer.getvalue()
            best_quality = 10
        if len(best_data) > target_bytes:
            raise ValueError(f"最低质量 {best_quality} 仍无法压缩到目标体积 {self._format_bytes(target_bytes)} 以内")
        target.write_bytes(best_data)

    @staticmethod
    def _parse_target_size(value: str) -> int | None:
        text = value.strip().lower()
        if not text:
            return None
        match = re.match(r"^(\d+(?:\.\d+)?)\s*(b|kb|k|mb|m)?$", text)
        if not match:
            raise ValueError("目标体积请填写 200KB、500KB 或 1.5MB 这种格式")
        amount = float(match.group(1))
        unit = match.group(2) or "kb"
        if unit == "b":
            return int(amount)
        if unit in {"mb", "m"}:
            return int(amount * 1024 * 1024)
        return int(amount * 1024)

    @staticmethod
    def _format_bytes(size: int) -> str:
        if size >= 1024 * 1024:
            return f"{size / 1024 / 1024:.2f}MB"
        if size >= 1024:
            return f"{size / 1024:.1f}KB"
        return f"{size}B"

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
        self.notebook.add(page, text="图片编辑")
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
        Label(opt_row2, textvariable=self.single_result_size_text, fg="#475467", font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(8, 0))
        Label(opt_row2, textvariable=self.single_result_file_size_text, fg="#c05621", font=("Microsoft YaHei UI", 9, "bold")).pack(side="left", padx=(10, 0))

        self.single_editor_host = Frame(page)
        self.single_editor_host.pack(fill="both", expand=True, pady=(10, 0))
        self.single_editor = None
        self._show_empty_single_canvas()
        self._enable_file_drop(self.single_editor_host, self.load_single_image)
        self._on_single_output_format_change()

    def _update_single_result_size(self) -> None:
        if not self.single_editor:
            self.single_result_size_text.set("结果尺寸：-")
            self.single_result_file_size_text.set("结果大小：-")
            return
        try:
            width, height = self.single_editor.result_dimensions()
        except Exception:
            self.single_result_size_text.set("结果尺寸：-")
            self.single_result_file_size_text.set("结果大小：-")
            return
        self.single_result_size_text.set(f"结果尺寸：{width} x {height} px / {self.single_output_format.get().upper()}")
        self.single_result_file_size_text.set("结果大小：估算中...")
        if self.single_result_after_id:
            self.root.after_cancel(self.single_result_after_id)
        self.single_result_after_id = self.root.after(260, self._update_single_result_bytes)

    def _update_single_result_bytes(self) -> None:
        if not self.single_editor:
            return
        try:
            size = self._estimate_single_result_bytes()
            self.single_result_file_size_text.set(f"结果大小：约 {self._format_bytes(size)}")
        except Exception:
            self.single_result_file_size_text.set("结果大小：暂不可估算")

    def _estimate_single_result_bytes(self) -> int:
        if not self.single_editor:
            return 0
        out_format = self.single_output_format.get()
        quality = self._safe_int_var(self.single_quality, 92)
        bg = self._parse_color(self.single_alpha_bg.get())
        im = self.single_editor._edited_image()
        buf = io.BytesIO()
        if out_format == "jpg":
            im = self._flatten_alpha(im, bg)
            im.save(buf, format="JPEG", quality=quality, optimize=True, progressive=bool(self.single_progressive_jpg.get()))
        elif out_format == "webp":
            im = im.convert("RGBA") if im.mode in {"RGBA", "LA", "P"} else im.convert("RGB")
            im.save(buf, format="WEBP", quality=quality, method=6)
        elif out_format == "png":
            im = im.convert("RGBA") if im.mode in {"RGBA", "LA", "P"} else im.convert("RGB")
            im.save(buf, format="PNG", optimize=True)
        return len(buf.getvalue())

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
        self._update_single_result_size()

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
        self._update_single_result_size()
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

    def _apply_step_event(self, payload: dict[str, object]) -> None:
        steps = payload.get("steps", [])
        current_index = int(payload.get("current_index", 0) or 0)
        completed_steps = int(payload.get("completed_steps", 0) or 0)
        total_steps = int(payload.get("total_steps", 1) or 1)
        status = str(payload.get("status", "running"))
        error = str(payload.get("error", ""))
        if not isinstance(steps, list):
            return
        current_file = str(payload.get("file", "-"))
        current_step = steps[current_index].name if steps and 0 <= current_index < len(steps) else "-"
        if steps and 0 <= current_index < len(steps):
            new_active = steps[current_index].module_id
            if new_active != self.active_workflow_module_id:
                self.active_workflow_module_id = new_active
                self._schedule_workflow_render()
        if status == "failed":
            current_step = f"失败：{error or current_step}"
        percent = int(completed_steps * 100 / max(1, total_steps))
        self.task_current_file_text.set(f"当前文件：{current_file}")
        self.task_current_step_text.set(f"当前步骤：{current_step}")
        self.task_progress_text.set(f"总进度：{percent}%")
        self._render_current_steps(steps, current_index, completed_steps, status)

    def _render_current_steps(self, steps: list[ProcessingStep], current_index: int, completed_steps: int, status: str) -> None:
        if not hasattr(self, "task_line_frame"):
            return
        # Keep the compact current line stable; detailed step state is exposed in the status text.
        visible_start = max(0, min(current_index - 2, max(0, len(steps) - 5)))
        visible = steps[visible_start: visible_start + 5]
        parts: list[str] = []
        for absolute_index, step in enumerate(visible, start=visible_start):
            if status == "failed" and absolute_index == current_index:
                marker = "!"
            elif absolute_index < current_index:
                marker = "✓"
            elif absolute_index == current_index:
                marker = "●"
            else:
                marker = "○"
            parts.append(f"{marker}{step.name}")
        prefix = "…" if visible_start > 0 else ""
        suffix = "…" if visible_start + len(visible) < len(steps) else ""
        compact = "  ".join(parts)
        self.task_current_step_text.set(f"当前步骤：{prefix}{compact}{suffix}")

    def _refresh_job_card_by_key(self, source_key: str) -> None:
        for idx, job in enumerate(self.jobs):
            if self._source_key(job.source) == source_key:
                self._populate_grid()
                if job.tree_id:
                    self.tree.item(job.tree_id, image=self.tree_icons[("file", "checked" if job.selected else "unchecked")])
                break

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "step":
                    self._apply_step_event(payload)  # type: ignore[arg-type]
                elif kind == "job_status":
                    self._refresh_job_card_by_key(str(payload))
                if kind == "progress":
                    completed_steps, total_steps, index, total, ok, failed, skipped = payload  # type: ignore[misc]
                    self.progress.config(value=completed_steps, maximum=max(1, total_steps))
                    percent = int(completed_steps * 100 / max(1, total_steps))
                    self._set_status_parts([
                        ("处理中 ", False), (f"{index}/{total}", True),
                        ("，成功 ", False), (str(ok), True),
                        ("，失败 ", False), (str(failed), True),
                        ("，跳过 ", False), (str(skipped), True),
                    ])
                    self.task_progress_text.set(f"总进度：{percent}%")
                elif kind == "done":
                    ok, failed, skipped, unselected, report_path, failures, elapsed = payload  # type: ignore[misc]
                    self._set_status_parts([
                        ("完成：成功 ", False), (str(ok), True),
                        ("，失败 ", False), (str(failed), True),
                        ("，跳过 ", False), (str(skipped), True),
                        ("，未选 ", False), (str(unselected), True),
                        (f"。报告：{report_path}", False),
                    ])
                    self._set_task_status("-", "本次任务已完成", "100%")
                    self.active_workflow_module_id = None
                    self._schedule_workflow_render()
                    summary = f"成功 {ok}\n失败 {failed}\n跳过 {skipped}\n未选 {unselected}\n耗时 {elapsed:.1f} 秒\n\n报告：{report_path}"
                    if failures:
                        shown = "\n".join(str(item) for item in failures[:8])
                        more = "" if len(failures) <= 8 else f"\n... 还有 {len(failures) - 8} 条，详见报告。"
                        messagebox.showwarning("转换完成：存在失败项", f"{summary}\n\n失败列表：\n{shown}{more}")
                    else:
                        messagebox.showinfo("转换完成", summary)
        except queue.Empty:
            pass
        self.root.after(120, self._drain_events)


class WatermarkEditor:
    def __init__(self, app: ImageConverterApp, base_image: Image.Image, source: Path) -> None:
        self.app = app
        self.base_image = base_image.convert("RGBA")
        self.source = source
        self.original = {
            "enabled": app.watermark_enabled.get(),
            "opacity": app.watermark_opacity.get(),
            "scale": app.watermark_scale_percent.get(),
            "angle": app.watermark_angle.get(),
            "custom_x": app.watermark_custom_x.get(),
            "custom_y": app.watermark_custom_y.get(),
        }
        self.saved = False
        self.drag_mode: str | None = None
        self.drag_start = (0, 0)
        self.start_scale = app.watermark_scale_percent.get()
        self.display_scale = 1.0
        self.display_offset = (0, 0)
        self.mark_box = (0, 0, 0, 0)
        self.photo: ImageTk.PhotoImage | None = None

        self.window = Toplevel(app.root)
        self.window.title(f"预览/编辑水印 - {source.name}")
        self.window.geometry("1120x820")
        self.window.minsize(900, 680)
        self.window.transient(app.root)
        self.window.protocol("WM_DELETE_WINDOW", self._cancel)

        top = Frame(self.window, padx=10, pady=8)
        top.pack(fill="x")
        Label(top, text=f"样图：{source.name}    输出尺寸：{self.base_image.width} x {self.base_image.height}", font=("Microsoft YaHei UI", 10, "bold")).pack(side="left")

        controls = Frame(self.window, padx=10)
        controls.pack(fill="x")
        Label(controls, text="不透明").pack(side="left")
        Scale(controls, from_=1, to=100, orient="horizontal", variable=app.watermark_opacity, command=lambda _v: self._render(), length=150).pack(side="left", padx=(4, 16))
        Label(controls, text="缩放").pack(side="left")
        Scale(controls, from_=5, to=500, orient="horizontal", variable=app.watermark_scale_percent, command=lambda _v: self._render(), length=150).pack(side="left", padx=(4, 16))
        Label(controls, text="角度").pack(side="left")
        Scale(controls, from_=-180, to=180, orient="horizontal", variable=app.watermark_angle, command=lambda _v: self._render(), length=180).pack(side="left", padx=(4, 16))
        Button(controls, text="重置到九宫格位置", command=self._reset_position, width=16).pack(side="left")

        self.canvas = Canvas(self.window, bg="#202020", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=10, pady=10)
        self.canvas.bind("<Configure>", lambda _e: self._render())
        self.canvas.bind("<ButtonPress-1>", self._start_drag)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", lambda _e: self._render())

        bottom = Frame(self.window, padx=10)
        bottom.pack(fill="x", pady=(0, 10))
        Label(bottom, text="拖动水印调整位置；拖动右下角绿色点调整大小；滑块可调整不透明度和角度。", fg="#555").pack(side="left")
        Button(bottom, text="取消", command=self._cancel, width=10).pack(side="right")
        Button(bottom, text="保存水印设置", command=self._save, width=14, bg="#0b5cad", fg="white", activebackground="#084a8d", activeforeground="white").pack(side="right", padx=(0, 8))

        self._center()
        self._render()

    def _center(self) -> None:
        self.window.update_idletasks()
        w = self.window.winfo_width()
        h = self.window.winfo_height()
        sw = self.window.winfo_screenwidth()
        sh = self.window.winfo_screenheight()
        self.window.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2)}")

    def _compose(self) -> tuple[Image.Image, Image.Image | None, tuple[int, int]]:
        base = self.base_image.copy()
        mark = self.app._make_watermark_mark(base.size)
        if mark is None:
            return base, None, (0, 0)
        x, y = self.app._watermark_position(base.size, mark.size, max(0, self.app._safe_int_var(self.app.watermark_margin, 24)))
        layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        layer.alpha_composite(mark, (x, y))
        base.alpha_composite(layer)
        return base, mark, (x, y)

    def _render(self) -> None:
        if self.canvas.winfo_width() < 10:
            return
        composed, mark, xy = self._compose()
        max_w = max(1, self.canvas.winfo_width() - 24)
        max_h = max(1, self.canvas.winfo_height() - 24)
        scale = min(max_w / composed.width, max_h / composed.height, 1.0)
        display_size = (max(1, int(composed.width * scale)), max(1, int(composed.height * scale)))
        display = composed.convert("RGB").resize(display_size, Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(display)
        ox = (self.canvas.winfo_width() - display_size[0]) // 2
        oy = (self.canvas.winfo_height() - display_size[1]) // 2
        self.display_scale = scale
        self.display_offset = (ox, oy)
        self.canvas.delete("all")
        self.canvas.create_image(ox, oy, image=self.photo, anchor="nw")
        if mark:
            x, y = xy
            x1 = ox + int(x * scale)
            y1 = oy + int(y * scale)
            x2 = ox + int((x + mark.width) * scale)
            y2 = oy + int((y + mark.height) * scale)
            self.mark_box = (x1, y1, x2, y2)
            self.canvas.create_rectangle(x1, y1, x2, y2, outline="#00d084", width=2)
            self.canvas.create_rectangle(x2 - 8, y2 - 8, x2 + 8, y2 + 8, fill="#00d084", outline="#00d084")

    def _start_drag(self, event) -> None:
        x1, y1, x2, y2 = self.mark_box
        if x2 - 14 <= event.x <= x2 + 14 and y2 - 14 <= event.y <= y2 + 14:
            self.drag_mode = "scale"
        elif x1 <= event.x <= x2 and y1 <= event.y <= y2:
            self.drag_mode = "move"
        else:
            self.drag_mode = None
            return
        self.drag_start = (event.x, event.y)
        self.start_scale = self.app.watermark_scale_percent.get()

    def _drag(self, event) -> None:
        if not self.drag_mode:
            return
        mark = self.app._make_watermark_mark(self.base_image.size)
        if mark is None:
            return
        if self.drag_mode == "scale":
            delta = event.x - self.drag_start[0] + event.y - self.drag_start[1]
            self.app.watermark_scale_percent.set(max(5, min(500, int(self.start_scale + delta / 2))))
            self._render()
            return
        ox, oy = self.display_offset
        scale = max(self.display_scale, 0.0001)
        x = int((event.x - ox) / scale - mark.width / 2)
        y = int((event.y - oy) / scale - mark.height / 2)
        max_x = max(1, self.base_image.width - mark.width)
        max_y = max(1, self.base_image.height - mark.height)
        self.app.watermark_custom_x.set(max(0.0, min(1.0, x / max_x)))
        self.app.watermark_custom_y.set(max(0.0, min(1.0, y / max_y)))
        self._render()

    def _reset_position(self) -> None:
        self.app.watermark_custom_x.set(-1.0)
        self.app.watermark_custom_y.set(-1.0)
        self._render()

    def _save(self) -> None:
        self.app.watermark_enabled.set(True)
        self.app._update_control_states()
        self.saved = True
        self.window.destroy()

    def _cancel(self) -> None:
        if not self.saved:
            self.app.watermark_enabled.set(bool(self.original["enabled"]))
            self.app.watermark_opacity.set(int(self.original["opacity"]))
            self.app.watermark_scale_percent.set(int(self.original["scale"]))
            self.app.watermark_angle.set(int(self.original["angle"]))
            self.app.watermark_custom_x.set(float(self.original["custom_x"]))
            self.app.watermark_custom_y.set(float(self.original["custom_y"]))
            self.app._update_control_states()
        self.window.destroy()


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
        self.mask_ref: ImageTk.PhotoImage | None = None
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
        self.width_var.trace_add("write", lambda *_args: self._notify_result_size())
        self.height_var.trace_add("write", lambda *_args: self._notify_result_size())

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
        Label(top, textvariable=self.crop_size_text, fg="#667085", font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(18, 0))
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
        mask = Image.new("RGBA", (cw, ch), (0, 0, 0, 215))
        clear = Image.new("RGBA", (max(1, x2 - x1), max(1, y2 - y1)), (0, 0, 0, 0))
        mask.paste(clear, (x1, y1))
        self.mask_ref = ImageTk.PhotoImage(mask)
        self.canvas.create_image(0, 0, image=self.mask_ref, anchor="nw", tags="overlay")
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
        self._notify_result_size()

    def _notify_result_size(self) -> None:
        if hasattr(self.app, "_update_single_result_size"):
            self.app._update_single_result_size()

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

    def result_dimensions(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.output_box
        ix, iy = self.image_offset
        sx1 = max(0, int((x1 - ix) / self.scale))
        sy1 = max(0, int((y1 - iy) / self.scale))
        sx2 = min(self.original.width, int((x2 - ix) / self.scale))
        sy2 = min(self.original.height, int((y2 - iy) / self.scale))
        crop_w = max(1, sx2 - sx1)
        crop_h = max(1, sy2 - sy1)
        w, h = max(1, int(self.width_var.get())), max(1, int(self.height_var.get()))
        if self.keep_ratio.get():
            ratio = crop_w / crop_h
            if w / h > ratio:
                w = max(1, int(h * ratio))
            else:
                h = max(1, int(w / ratio))
        return w, h

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
        self.mask_ref: ImageTk.PhotoImage | None = None
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
        self.width_var.trace_add("write", lambda *_args: self._notify_result_size())
        self.height_var.trace_add("write", lambda *_args: self._notify_result_size())

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
