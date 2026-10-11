#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
subsplit_core.py —— SubSplit 核心逻辑：双语字幕分离 + 视频内封字幕提取 + 样式调节。

提供：
    extract_english / extract_chinese —— 从单条 Dialogue 文本中分离中/英
    process_file                      —— 按模式与样式配置处理整个文件
    collect_inputs                    —— 收集输入文件（单文件或目录）
    probe_subtitle_tracks / extract_subtitle —— 从视频提取内封软字幕
    rgb_to_ass                        —— RGB -> ASS 颜色
"""

import json
import os
import re
import shutil
import subprocess

# 英文对白标记：\N 后紧跟 {\fn微软雅黑...\i1...}（斜体灰字）。
# 注意区别于画面注释 {\an3\fs16\bord0\fn微软雅黑...}：其不在 \N 之后、无 \i1。
EN_MARKER_RE = re.compile(r"\\N\{([^{}]*)\}")
TAG_RE = re.compile(r"\{[^{}]*\}")

# 样式行（V4+ Styles）中 Default 各字段的位置
STYLE_FONTNAME = 1
STYLE_FONTSIZE = 2
STYLE_PRIMARY = 3
STYLE_BOLD = 7
STYLE_ITALIC = 8
STYLE_ALIGNMENT = 18
STYLE_MARGIN_V = 21


def rgb_to_ass(r, g, b, alpha=0):
    """RGB(0-255) -> ASS 颜色 &HAABBGGRR。"""
    return "&H%02X%02X%02X%02X&" % (alpha, b, g, r)


def find_english_markers(text):
    """返回文本中所有英文对白标记的匹配对象。"""
    marks = []
    for m in EN_MARKER_RE.finditer(text):
        block = m.group(1)
        if "微软雅黑" in block and "\\i1" in block:
            marks.append(m)
    return marks


def strip_tags(s):
    return TAG_RE.sub("", s)


def extract_english(text):
    """从一条 Dialogue 的 Text 字段提取英文；无英文返回 None。"""
    marks = find_english_markers(text)
    if not marks:
        return None
    # 取最后一个英文标记之后的内容（个别行会有两个标记）
    english = text[marks[-1].end():].split("\\N")[0]
    english = strip_tags(english).strip()
    return english if english else None


def extract_chinese(text):
    """从一条 Dialogue 的 Text 字段提取中文；无中文返回 None。

    双语行（含英文标记）取换行符之前的中文；纯中文行（画面文字/注释/名单）原样保留。
    """
    if find_english_markers(text):
        chinese = text.split("\\N", 1)[0]
        chinese = strip_tags(chinese).strip()
        return chinese if chinese else None
    stripped = text.strip()
    return stripped if stripped else None


def extract_text(text, mode):
    """mode: 'en' 提取英文，'zh' 提取中文。"""
    return extract_english(text) if mode == "en" else extract_chinese(text)


def lang_suffix(mode):
    """语言后缀标记：'en' -> '英'，'zh' -> '中'（用于输出文件名）。"""
    return "英" if mode == "en" else "中"


def apply_style(line, style):
    """按 style 修改 Default 样式行；style 中缺失的字段保持原值。"""
    if not style:
        return line
    s = line.rstrip("\r\n")
    if not s.startswith("Style: Default,"):
        return line
    parts = s.split(",")
    if len(parts) < 23:
        return line
    if style.get("fontname"):
        parts[STYLE_FONTNAME] = style["fontname"]
    if "fontsize" in style:
        parts[STYLE_FONTSIZE] = str(style["fontsize"])
    if "color" in style:
        parts[STYLE_PRIMARY] = rgb_to_ass(*style["color"])
    if "bold" in style:
        parts[STYLE_BOLD] = "-1" if style["bold"] else "0"
    if "italic" in style:
        parts[STYLE_ITALIC] = "-1" if style["italic"] else "0"
    if "alignment" in style:
        parts[STYLE_ALIGNMENT] = str(style["alignment"])
    if "margin_v" in style:
        parts[STYLE_MARGIN_V] = str(style["margin_v"])
    return ",".join(parts) + "\n"


def _split_sections(lines):
    """把文件行拆分为 (header, events格式行, 事件体)。"""
    header = []
    events_fmt = []
    body = []
    in_events = False
    seen_format = False
    for line in lines:
        if not in_events:
            if line.startswith("[Events]"):
                in_events = True
                header.append(line)
            else:
                header.append(line)
        else:
            if not seen_format:
                events_fmt.append(line)
                if line.startswith("Format:"):
                    seen_format = True
            else:
                body.append(line)
    return header, events_fmt, body


def _read_text(path):
    """按多种常见编码尝试读取文件，失败抛出带文件名信息的异常。"""
    for enc in ("utf-8-sig", "utf-8", "utf-16", "gbk", "big5"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.readlines()
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise RuntimeError("无法识别文件编码（不支持的文件格式）：%s" % path)


def process_file(src, dst, mode="en", style=None):
    """处理单个 .ass 文件，返回 (保留行数, 丢弃行数)。"""
    lines = _read_text(src)

    header, events_fmt, body = _split_sections(lines)
    if style:
        header = [apply_style(l, style) for l in header]

    kept = dropped = 0
    out = []
    for line in body:
        if not line.startswith("Dialogue:"):
            out.append(line)
            continue
        parts = line.split(",", 9)
        if len(parts) < 10:
            continue
        text = parts[9].rstrip("\r\n")
        result = extract_text(text, mode)
        if result is None:
            dropped += 1
            continue
        kept += 1
        out.append(",".join(parts[:9]) + "," + result + "\n")

    parent = os.path.dirname(dst)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(dst, "w", encoding="utf-8-sig", newline="") as f:
        f.writelines(header)
        f.writelines(events_fmt)
        f.writelines(out)

    return kept, dropped


def collect_inputs(path):
    """返回待处理的 .ass 文件列表（支持单文件或目录）。"""
    if os.path.isdir(path):
        return sorted(
            os.path.join(path, n)
            for n in os.listdir(path)
            if n.lower().endswith(".ass")
        )
    if os.path.isfile(path):
        return [path]
    return []


# ---------------------------------------------------------------------------
# 视频内封（软）字幕提取：依赖 ffmpeg / ffprobe
# ---------------------------------------------------------------------------

# 图形字幕（烧录型位图轨），无法直接转文本，需 OCR，不在本工具范围内
IMAGE_CODECS = {
    "hdmv_pgs_subtitle", "pgssub", "dvd_subtitle", "dvdsub",
    "dvb_subtitle", "xsub", "hdmv_pgs",
}


def _find_exe(exe_names, ffmpeg_dir=None):
    """按指定目录、PATH、常见安装目录、盘符根目录依次查找可执行文件。"""
    if ffmpeg_dir:
        for n in exe_names:
            cand = os.path.join(ffmpeg_dir, n)
            if os.path.isfile(cand):
                return cand
    for n in exe_names:
        w = shutil.which(n)
        if w:
            return w
    for d in (r"C:\ffmpeg\bin", r"C:\Program Files\ffmpeg\bin"):
        for n in exe_names:
            cand = os.path.join(d, n)
            if os.path.isfile(cand):
                return cand
    # 扫描盘符根目录下的 ffmpeg-* 构建目录（Gyan/BtbN 解压后的形态）
    for drive in ("C:/", "D:/", "E:/", "F:/"):
        try:
            entries = os.listdir(drive)
        except OSError:
            continue
        for d in entries:
            if not d.lower().startswith("ffmpeg-"):
                continue
            bin_dir = os.path.join(drive, d, "bin")
            if not os.path.isdir(bin_dir):
                continue
            for n in exe_names:
                cand = os.path.join(bin_dir, n)
                if os.path.isfile(cand):
                    return cand
    return None


def find_ffmpeg(ffmpeg_dir=None):
    return _find_exe(("ffmpeg.exe", "ffmpeg"), ffmpeg_dir)


def find_ffprobe(ffmpeg_dir=None):
    return _find_exe(("ffprobe.exe", "ffprobe"), ffmpeg_dir)


def probe_subtitle_tracks(video_path, ffmpeg_dir=None):
    """用 ffprobe 探测视频中的字幕轨，返回 [{index, codec, language, title}]。"""
    ffprobe = find_ffprobe(ffmpeg_dir)
    if not ffprobe:
        raise RuntimeError("未找到 ffprobe，请先安装 ffmpeg（含 ffprobe）")
    cmd = [
        ffprobe, "-v", "error", "-select_streams", "s",
        "-show_entries", "stream=index,codec_name:stream_tags=language,title",
        "-of", "json", video_path,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    if res.returncode != 0:
        raise RuntimeError("ffprobe 读取失败：" + (res.stderr or "").strip()[-400:])
    data = json.loads(res.stdout or "{}")
    tracks = []
    for st in data.get("streams", []):
        tags = st.get("tags") or {}
        tracks.append({
            "index": st.get("index"),
            "codec": st.get("codec_name", ""),
            "language": tags.get("language", ""),
            "title": tags.get("title", ""),
        })
    return tracks


def subtitle_track_label(track):
    """把字幕轨信息拼成一行可读标签。"""
    parts = []
    idx = track.get("index")
    if idx is not None:
        parts.append("#%s" % idx)
    codec = track.get("codec", "")
    if codec:
        parts.append(codec)
    lang = track.get("language", "")
    if lang:
        parts.append(lang)
    title = track.get("title", "")
    if title:
        parts.append(title)
    return "  ".join(str(p) for p in parts) if parts else "(无信息)"


def extract_subtitle(video_path, stream_index, out_path, codec="", ffmpeg_dir=None):
    """用 ffmpeg 提取指定字幕轨为文本字幕，返回实际输出文件路径。

    文本字幕（ass/srt/mov_text 等）直接提取/转换；图形字幕抛异常提示需 OCR。
    """
    ffmpeg = find_ffmpeg(ffmpeg_dir)
    if not ffmpeg:
        raise RuntimeError("未找到 ffmpeg，请先安装 ffmpeg")

    codec = (codec or "").lower()
    if codec in IMAGE_CODECS:
        raise RuntimeError(
            "该字幕轨是图形字幕（%s），无法直接提取为文本，需 OCR（超出本工具范围）" % codec
        )

    if codec in ("ass", "ssa"):
        cflag, ext = "copy", ".ass"
    elif codec in ("subrip", "srt"):
        cflag, ext = "copy", ".srt"
    else:
        # mov_text / webvtt / text 等：转成 srt
        cflag, ext = "srt", ".srt"

    root, _ = os.path.splitext(out_path)
    out_path = root + ext

    cmd = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-i", video_path,
        "-map", "0:%d" % stream_index,
        "-c:s", cflag,
        out_path,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    if res.returncode != 0:
        raise RuntimeError("ffmpeg 提取失败：" + (res.stderr or "").strip()[-400:])
    return out_path
