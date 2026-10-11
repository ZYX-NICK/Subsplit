#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
subsplit_gui.py —— SubSplit 双语字幕分离工具的可视化界面。

功能：
    - 选择分离英文或中文；
    - 从视频提取内封（软）字幕；
    - 调节字幕字体、字号、颜色、粗体/斜体、对齐方式、底边距；
    - 批量处理单个文件或整个目录，实时显示日志。

运行：python subsplit_gui.py
"""

import json
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, colorchooser, font as tkfont

import subsplit_core as core

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# 对齐方式：显示名 -> ASS Alignment 码（1-9 小键盘布局）
ALIGNMENTS = [
    ("底部居中", 2),
    ("底部居左", 1),
    ("底部居右", 3),
    ("中间居中", 5),
    ("顶部居中", 8),
    ("顶部居左", 7),
    ("顶部居右", 9),
]
ALIGN_BY_NAME = dict(ALIGNMENTS)


def pick_default_font():
    fams = set(tkfont.families())
    for f in ("微软雅黑", "Microsoft YaHei", "Arial", "SimHei"):
        if f in fams:
            return f
    return sorted(fams)[0] if fams else "Arial"


def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class App:
    def __init__(self, root):
        self.root = root
        root.title("SubSplit · 双语字幕分离工具")
        root.minsize(620, 640)

        self.running = False
        self.q = queue.Queue()
        self.color_rgb = (255, 255, 255)

        # 变量
        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.mode_var = tk.StringVar(value="en")
        self.font_var = tk.StringVar(value=pick_default_font())
        self.size_var = tk.IntVar(value=150)
        self.bold_var = tk.BooleanVar(value=False)
        self.italic_var = tk.BooleanVar(value=False)
        self.align_var = tk.StringVar(value="底部居中")
        self.margin_var = tk.IntVar(value=40)

        # 视频提取相关
        self.video_var = tk.StringVar()
        self.track_var = tk.StringVar()
        self.ffmpeg_dir_var = tk.StringVar()
        self.video_tracks = []

        # 默认输入：脚本同级的 test 目录
        test_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test")
        if os.path.isdir(test_dir):
            self.input_var.set(test_dir)

        self._apply_config(load_config())

        self._build_ui()
        self.refresh_preview()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- 配置 ----------
    def _apply_config(self, cfg):
        if not cfg:
            return
        if cfg.get("ffmpeg_dir"):
            self.ffmpeg_dir_var.set(cfg["ffmpeg_dir"])
        if cfg.get("input"):
            self.input_var.set(cfg["input"])
        if cfg.get("output"):
            self.output_var.set(cfg["output"])
        if cfg.get("mode") in ("en", "zh"):
            self.mode_var.set(cfg["mode"])
        st = cfg.get("style") or {}
        if st.get("fontname"):
            self.font_var.set(st["fontname"])
        if isinstance(st.get("fontsize"), int):
            self.size_var.set(st["fontsize"])
        if isinstance(st.get("color"), (list, tuple)) and len(st["color"]) == 3:
            self.color_rgb = tuple(int(c) for c in st["color"])
        if "bold" in st:
            self.bold_var.set(bool(st["bold"]))
        if "italic" in st:
            self.italic_var.set(bool(st["italic"]))
        if st.get("alignment") in ALIGN_BY_NAME:
            self.align_var.set(st["alignment"])
        if isinstance(st.get("margin_v"), int):
            self.margin_var.set(st["margin_v"])

    @staticmethod
    def _get_int(var, default):
        try:
            return int(var.get())
        except (tk.TclError, ValueError):
            return default

    def _collect_config(self):
        return {
            "ffmpeg_dir": self.ffmpeg_dir_var.get().strip(),
            "input": self.input_var.get().strip(),
            "output": self.output_var.get().strip(),
            "mode": self.mode_var.get(),
            "style": {
                "fontname": self.font_var.get(),
                "fontsize": self._get_int(self.size_var, 150),
                "color": list(self.color_rgb),
                "bold": self.bold_var.get(),
                "italic": self.italic_var.get(),
                "alignment": self.align_var.get(),
                "margin_v": self._get_int(self.margin_var, 40),
            },
        }

    def _on_close(self):
        try:
            save_config(self._collect_config())
        except Exception:
            pass
        self.root.destroy()

    # ---------- UI ----------
    def _build_ui(self):
        # 输入 / 输出
        io = ttk.LabelFrame(self.root, text=" 输入 / 输出 ", padding=10)
        io.pack(fill="x", padx=12, pady=(12, 4))

        ttk.Label(io, text="输入：").grid(row=0, column=0, sticky="w")
        ttk.Entry(io, textvariable=self.input_var).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(io, text="文件…", command=self.pick_input_file).grid(row=0, column=2, padx=2)
        ttk.Button(io, text="目录…", command=self.pick_input_dir).grid(row=0, column=3, padx=2)

        ttk.Label(io, text="输出：").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(io, textvariable=self.output_var).grid(row=1, column=1, sticky="ew", padx=6, pady=(6, 0))
        ttk.Button(io, text="目录…", command=self.pick_output_dir).grid(row=1, column=2, columnspan=2, padx=2, pady=(6, 0), sticky="w")
        io.columnconfigure(1, weight=1)

        # 从视频提取字幕
        vid = ttk.LabelFrame(self.root, text=" 从视频提取字幕（内封软字幕） ", padding=10)
        vid.pack(fill="x", padx=12, pady=4)

        ttk.Label(vid, text="视频：").grid(row=0, column=0, sticky="w")
        ttk.Entry(vid, textvariable=self.video_var).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(vid, text="选择…", command=self.pick_video).grid(row=0, column=2, padx=2)

        ttk.Label(vid, text="字幕轨：").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.track_box = ttk.Combobox(vid, textvariable=self.track_var, state="readonly", width=34)
        self.track_box.grid(row=1, column=1, sticky="ew", padx=6, pady=(6, 0))
        ttk.Button(vid, text="探测字幕轨", command=self.probe_tracks).grid(row=1, column=2, padx=2, pady=(6, 0))

        ttk.Label(vid, text="ffmpeg：").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(vid, textvariable=self.ffmpeg_dir_var).grid(row=2, column=1, sticky="ew", padx=6, pady=(6, 0))
        ttk.Button(vid, text="提取字幕", command=self.extract_video_subtitle).grid(row=2, column=2, padx=2, pady=(6, 0))
        ttk.Label(vid, text="ffmpeg 留空则自动在 PATH 中查找，否则填 ffmpeg.exe 所在目录",
                  foreground="#888888").grid(row=3, column=1, columnspan=2, sticky="w", pady=(2, 0))
        vid.columnconfigure(1, weight=1)

        # 分离模式
        mode = ttk.LabelFrame(self.root, text=" 分离内容 ", padding=10)
        mode.pack(fill="x", padx=12, pady=4)
        ttk.Radiobutton(mode, text="仅英文（English）", variable=self.mode_var, value="en").pack(side="left", padx=(0, 20))
        ttk.Radiobutton(mode, text="仅中文（中文）", variable=self.mode_var, value="zh").pack(side="left")

        # 格式调节
        fmt = ttk.LabelFrame(self.root, text=" 字幕格式 ", padding=10)
        fmt.pack(fill="x", padx=12, pady=4)

        ttk.Label(fmt, text="字体：").grid(row=0, column=0, sticky="w")
        self.font_box = ttk.Combobox(fmt, textvariable=self.font_var,
                                     values=sorted(tkfont.families()), width=22)
        self.font_box.grid(row=0, column=1, sticky="w", padx=6)
        self.font_box.bind("<<ComboboxSelected>>", lambda e: self.refresh_preview())
        self.font_var.trace_add("write", lambda *a: self.refresh_preview())

        ttk.Label(fmt, text="字号：").grid(row=0, column=2, sticky="w", padx=(18, 0))
        ttk.Spinbox(fmt, from_=20, to=400, textvariable=self.size_var, width=6,
                    command=self.refresh_preview).grid(row=0, column=3, sticky="w", padx=6)

        ttk.Label(fmt, text="颜色：").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.swatch = tk.Label(fmt, width=4, height=1, relief="ridge", bg="#FFFFFF",
                               cursor="hand2")
        self.swatch.grid(row=1, column=1, sticky="w", padx=6, pady=(8, 0))
        self.swatch.bind("<Button-1>", lambda e: self.pick_color())
        ttk.Button(fmt, text="选择颜色…", command=self.pick_color).grid(row=1, column=2, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Checkbutton(fmt, text="粗体", variable=self.bold_var,
                        command=self.refresh_preview).grid(row=2, column=1, sticky="w", pady=(8, 0))
        ttk.Checkbutton(fmt, text="斜体", variable=self.italic_var,
                        command=self.refresh_preview).grid(row=2, column=2, sticky="w", pady=(8, 0))

        ttk.Label(fmt, text="对齐：").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Combobox(fmt, textvariable=self.align_var, values=[n for n, _ in ALIGNMENTS],
                     state="readonly", width=10).grid(row=3, column=1, sticky="w", padx=6, pady=(8, 0))

        ttk.Label(fmt, text="底边距：").grid(row=3, column=2, sticky="w", padx=(18, 0), pady=(8, 0))
        ttk.Spinbox(fmt, from_=0, to=500, textvariable=self.margin_var, width=6).grid(row=3, column=3, sticky="w", padx=6, pady=(8, 0))

        # 预览
        prev = ttk.LabelFrame(self.root, text=" 预览 ", padding=10)
        prev.pack(fill="x", padx=12, pady=4)
        self.preview = tk.Label(prev, text="Aa Bb 中文字幕 Sample 123", anchor="w")
        self.preview.pack(fill="x")

        # 操作按钮
        btns = ttk.Frame(self.root)
        btns.pack(fill="x", padx=12, pady=8)
        self.start_btn = ttk.Button(btns, text="开始转换", command=self.start)
        self.start_btn.pack(side="left")
        ttk.Button(btns, text="打开输出目录", command=self.open_output).pack(side="left", padx=8)

        # 日志
        logf = ttk.LabelFrame(self.root, text=" 日志 ", padding=6)
        logf.pack(fill="both", expand=True, padx=12, pady=(4, 12))
        self.log_text = tk.Text(logf, height=10, state="disabled", wrap="word")
        scroll = ttk.Scrollbar(logf, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True)

    # ---------- 交互 ----------
    def pick_input_file(self):
        p = filedialog.askopenfilename(
            title="选择字幕文件", filetypes=[("ASS 字幕", "*.ass"), ("所有文件", "*.*")])
        if p:
            self.input_var.set(p)

    def pick_input_dir(self):
        p = filedialog.askdirectory(title="选择字幕目录")
        if p:
            self.input_var.set(p)

    def pick_output_dir(self):
        p = filedialog.askdirectory(title="选择输出目录")
        if p:
            self.output_var.set(p)

    def pick_video(self):
        p = filedialog.askopenfilename(
            title="选择视频文件",
            filetypes=[("视频文件", "*.mkv *.mp4 *.ts *.m2ts *.webm *.mov *.avi"),
                       ("所有文件", "*.*")])
        if p:
            self.video_var.set(p)
            self.track_var.set("")
            self.video_tracks = []
            self.track_box["values"] = []

    def _ffmpeg_dir(self):
        d = self.ffmpeg_dir_var.get().strip()
        return d or None

    def probe_tracks(self):
        video = self.video_var.get().strip()
        if not video or not os.path.isfile(video):
            self.log("[!] 请先选择有效的视频文件")
            return
        try:
            tracks = core.probe_subtitle_tracks(video, ffmpeg_dir=self._ffmpeg_dir())
        except Exception as e:
            self.log("[!] 探测失败：%s" % e)
            self.log("[提示] 请确认已安装 ffmpeg（含 ffprobe），或在“ffmpeg”栏填写其所在目录")
            return
        if not tracks:
            self.log("[!] 该视频没有内封字幕轨")
            self.video_tracks = []
            self.track_box["values"] = []
            return
        self.video_tracks = tracks
        labels = [core.subtitle_track_label(t) for t in tracks]
        self.track_box["values"] = labels
        self.track_var.set(labels[0])
        self.log("探测到 %d 条字幕轨：" % len(tracks))
        for lbl in labels:
            self.log("  " + lbl)

    def extract_video_subtitle(self):
        video = self.video_var.get().strip()
        if not video or not os.path.isfile(video):
            self.log("[!] 请先选择有效的视频文件")
            return
        if not self.video_tracks:
            self.log("[!] 请先点击“探测字幕轨”")
            return
        idx = self.track_box.current()
        if idx < 0:
            self.log("[!] 请选择要提取的字幕轨")
            return
        track = self.video_tracks[idx]
        out_dir = self.output_var.get().strip() or os.path.dirname(os.path.abspath(video))
        os.makedirs(out_dir, exist_ok=True)
        stem = os.path.splitext(os.path.basename(video))[0]
        out_path = os.path.join(out_dir, stem + "_track%d" % track["index"])
        try:
            dst = core.extract_subtitle(video, track["index"], out_path,
                                        codec=track["codec"], ffmpeg_dir=self._ffmpeg_dir())
        except Exception as e:
            self.log("[!] 提取失败：%s" % e)
            return
        self.log("已提取：%s" % dst)
        if dst.lower().endswith(".ass"):
            self.input_var.set(dst)
            self.log("已填入“输入”，可继续选择中/英文后点“开始转换”")
        else:
            self.log("已提取为 SRT（纯文本轨），可直接使用；如需中英分离请用双语 ASS 字幕")

    def pick_color(self):
        hex_current = "#%02X%02X%02X" % self.color_rgb
        rgb, _ = colorchooser.askcolor(color=hex_current, parent=self.root,
                                       title="选择字幕颜色")
        if rgb:
            self.color_rgb = tuple(int(c) for c in rgb)
            self.refresh_preview()

    def refresh_preview(self):
        try:
            size = max(8, min(int(self.size_var.get()), 40))
        except (tk.TclError, ValueError):
            size = 24
        f = (self.font_var.get(), size,
             "bold" if self.bold_var.get() else "normal",
             "italic" if self.italic_var.get() else "roman")
        self.preview.configure(font=f, foreground="#%02X%02X%02X" % self.color_rgb)
        self.swatch.configure(bg="#%02X%02X%02X" % self.color_rgb)

    def log(self, msg):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def open_output(self):
        out = self.output_var.get().strip()
        if out and os.path.isdir(out):
            os.startfile(out)
        else:
            self.log("[!] 输出目录不存在")

    # ---------- 转换 ----------
    def _build_style(self):
        return {
            "fontname": self.font_var.get().strip(),
            "fontsize": self._get_int(self.size_var, 150),
            "color": self.color_rgb,
            "bold": self.bold_var.get(),
            "italic": self.italic_var.get(),
            "alignment": ALIGN_BY_NAME.get(self.align_var.get(), 2),
            "margin_v": self._get_int(self.margin_var, 40),
        }

    def start(self):
        if self.running:
            return
        src = self.input_var.get().strip()
        if not src or not os.path.exists(src):
            self.log("[!] 请选择有效的输入文件或目录")
            return
        files = core.collect_inputs(src)
        if not files:
            self.log("[!] 未找到 .ass 字幕文件")
            return

        try:
            mode = self.mode_var.get()
            single_file = os.path.isfile(src)
            if self.output_var.get().strip():
                out_dir = self.output_var.get().strip()
            elif single_file:
                out_dir = os.path.dirname(os.path.abspath(src))
            else:
                out_dir = os.path.abspath(src).rstrip(os.sep) + "_out"
            os.makedirs(out_dir, exist_ok=True)
            style = self._build_style()
        except Exception as e:
            self.log("[!] 启动失败：%s" % e)
            return
        self.running = True
        self.start_btn.configure(state="disabled")
        self.log("开始转换：%d 个文件，模式=%s" % (len(files), "英文" if mode == "en" else "中文"))
        self.log("输出目录：%s" % out_dir)

        t = threading.Thread(target=self._worker,
                             args=(files, out_dir, mode, style),
                             daemon=True)
        t.start()
        self.root.after(100, self._poll)

    def _worker(self, files, out_dir, mode, style):
        suffix = "." + core.lang_suffix(mode)
        total_kept = total_dropped = 0
        try:
            for src in files:
                base = os.path.basename(src)
                dst = os.path.join(out_dir, base[:-4] + suffix + ".ass")
                try:
                    kept, dropped = core.process_file(src, dst, mode=mode, style=style)
                except Exception as e:
                    self.q.put(("log", "  [失败] %s：%s" % (base, e)))
                    continue
                total_kept += kept
                total_dropped += dropped
                self.q.put(("log", "  %s -> 保留 %d / 丢弃 %d" % (base, kept, dropped)))
            self.q.put(("done", "完成：%d 个文件，保留 %d 行，丢弃 %d 行" % (len(files), total_kept, total_dropped)))
        except Exception as e:
            self.q.put(("done", "转换出错：%s" % e))

    def _poll(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    self.log(val)
                else:
                    self.log(val)
                    self.running = False
                    self.start_btn.configure(state="normal")
        except queue.Empty:
            pass
        if self.running:
            self.root.after(100, self._poll)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
