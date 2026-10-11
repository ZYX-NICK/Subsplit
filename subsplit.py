#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
subsplit.py —— SubSplit 双语字幕分离工具的命令行入口。

用法：
    python subsplit.py <输入文件或目录> [输出目录] [--mode en|zh]

说明：
    - 输入可以是单个 .ass 文件，也可以是包含 .ass 文件的目录（批量处理）。
    - --mode en  提取英文（默认）；--mode zh 提取中文。
    - 未指定输出目录时：
        * 输入为目录 -> 生成同级目录 "<目录名>_out"；
        * 输入为文件 -> 生成 "<原名>.英.ass" 或 "<原名>.中.ass"。
"""

import argparse
import os
import sys

import subsplit_core as core


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="subsplit",
        description="SubSplit —— 从中英双语 ASS 字幕中分离中文或英文字幕",
        epilog="示例：python subsplit.py test --mode zh",
    )
    parser.add_argument("input", help="输入 .ass 文件或目录")
    parser.add_argument("output", nargs="?", help="输出目录（可选）")
    parser.add_argument("--mode", choices=["en", "zh"], default="en",
                        help="分离英文(en)还是中文(zh)，默认 en")
    args = parser.parse_args(argv)

    files = core.collect_inputs(args.input)
    if not files:
        print("[!] 未找到可处理的 .ass 文件：%s" % args.input)
        return 1

    single_file = os.path.isfile(args.input)
    if args.output:
        out_dir = args.output
    elif single_file:
        out_dir = os.path.dirname(os.path.abspath(args.input))
    else:
        out_dir = os.path.abspath(args.input).rstrip(os.sep) + "_out"
    os.makedirs(out_dir, exist_ok=True)

    suffix = "." + core.lang_suffix(args.mode)
    total_kept = total_dropped = 0
    for src in files:
        base = os.path.basename(src)
        dst = os.path.join(out_dir, base[:-4] + suffix + ".ass")
        kept, dropped = core.process_file(src, dst, mode=args.mode)
        total_kept += kept
        total_dropped += dropped
        print("  %s -> 保留 %d 行 / 丢弃 %d 行" % (base, kept, dropped))

    print("\n完成：共 %d 个文件，保留 %d 行，丢弃 %d 行" % (len(files), total_kept, total_dropped))
    print("输出目录：%s" % out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
