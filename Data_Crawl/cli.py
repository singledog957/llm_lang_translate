#!/usr/bin/env python3
"""
cli.py - 命令行入口

用法示例：
  # 单次采集（使用默认配置）
  python cli.py collect

  # 覆盖配置参数
  python cli.py collect --languages zh en --domains technology politics --total 500

  # 指定配置文件路径
  python cli.py collect --config /path/to/config.yaml --sources /path/to/sources.yaml

  # 定时采集（interval 模式，interval_hours 由配置文件决定）
  python cli.py schedule

  # 列出所有可用数据源
  python cli.py sources

  # 验证配置
  python cli.py validate
"""
import argparse
import asyncio
import sys
import time
from pathlib import Path

from loguru import logger

# 项目根目录加入 path
sys.path.insert(0, str(Path(__file__).parent))

from src.models import load_config, load_sources
from src.engine import run_collection


DEFAULT_CONFIG = Path(__file__).parent / "config" / "config.yaml"
DEFAULT_SOURCES = Path(__file__).parent / "config" / "sources.yaml"


def setup_logging(cfg):
    logger.remove()
    logger.add(sys.stderr, level=cfg.logging.level,
               format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")
    log_path = Path(cfg.logging.file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger.add(log_path, level="DEBUG", rotation="10 MB", retention="7 days",
               encoding="utf-8")


def cmd_collect(args):
    cfg = load_config(args.config)
    sources = load_sources(args.sources)
    setup_logging(cfg)

    # CLI 参数覆盖配置文件
    if args.languages:
        cfg.collection.languages = args.languages
    if args.domains:
        cfg.collection.domains = args.domains
    if args.total is not None:
        cfg.collection.limits.total = args.total
    if args.per_source is not None:
        cfg.collection.limits.per_source = args.per_source
    if args.output:
        cfg.output.path = args.output
    if args.format:
        cfg.output.format = args.format
    if args.start:
        cfg.collection.time_range.start = args.start
    if args.end:
        cfg.collection.time_range.end = args.end

    # 过滤指定的来源名（--source-names）
    if args.source_names:
        names = set(args.source_names)
        sources = [s for s in sources if s.name in names]
        logger.info(f"仅使用指定来源: {[s.name for s in sources]}")

    summary = asyncio.run(run_collection(cfg, sources, concurrency=args.concurrency))
    print(f"\n✓ 采集完成，共 {summary.get('total', 0)} 条")


def cmd_schedule(args):
    cfg = load_config(args.config)
    sources = load_sources(args.sources)
    setup_logging(cfg)

    interval = cfg.collection.schedule.interval_hours * 3600
    logger.info(f"定时模式：每 {cfg.collection.schedule.interval_hours} 小时采集一次")

    while True:
        logger.info("开始采集周期...")
        asyncio.run(run_collection(cfg, sources, concurrency=args.concurrency))
        logger.info(f"等待 {cfg.collection.schedule.interval_hours} 小时...")
        time.sleep(interval)


def cmd_sources(args):
    sources = load_sources(args.sources)
    enabled = [s for s in sources if s.enabled]
    disabled = [s for s in sources if not s.enabled]
    print(f"\n{'='*60}")
    print(f"  已启用数据源（{len(enabled)} 个）")
    print(f"{'='*60}")
    for s in enabled:
        feeds_info = f"  feeds={len(s.feeds)}" if s.feeds else ""
        print(f"  ✓ [{s.type:15s}] {s.name} (lang={s.language}{feeds_info})")
        print(f"    domains: {', '.join(s.domains)}")
    if disabled:
        print(f"\n  已禁用数据源（{len(disabled)} 个）")
        for s in disabled:
            print(f"  ✗ [{s.type:15s}] {s.name}")
    print()


def cmd_validate(args):
    try:
        cfg = load_config(args.config)
        sources = load_sources(args.sources)
        print("✓ config.yaml 格式正确")
        print(f"  语言: {cfg.collection.languages}")
        print(f"  领域: {cfg.collection.domains}")
        print(f"  输出格式: {cfg.output.format} → {cfg.output.path}")
        print(f"✓ sources.yaml 格式正确，共 {len(sources)} 个来源")
        for s in sources:
            status = "✓" if s.enabled else "✗"
            print(f"  {status} {s.name} ({s.type}, {s.language})")
    except Exception as e:
        print(f"✗ 配置错误: {e}")
        sys.exit(1)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="collector",
        description="多语言文本采集系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # 公共参数
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--config", default=str(DEFAULT_CONFIG), help="主配置文件路径")
    parent.add_argument("--sources", default=str(DEFAULT_SOURCES), help="数据源配置文件路径")

    sub = parser.add_subparsers(dest="command", required=True)

    # collect
    p_collect = sub.add_parser("collect", parents=[parent], help="执行一次采集")
    p_collect.add_argument("--languages", nargs="+", metavar="LANG", help="目标语言（覆盖配置）")
    p_collect.add_argument("--domains", nargs="+", metavar="DOMAIN", help="目标领域（覆盖配置）")
    p_collect.add_argument("--total", type=int, metavar="N", help="总采集数量上限")
    p_collect.add_argument("--per-source", type=int, metavar="N", help="每个来源上限")
    p_collect.add_argument("--start", metavar="DATE", help="起始时间 YYYY-MM-DD")
    p_collect.add_argument("--end", metavar="DATE", help="结束时间 YYYY-MM-DD")
    p_collect.add_argument("--output", metavar="DIR", help="输出目录（覆盖配置）")
    p_collect.add_argument("--format", choices=["jsonl", "parquet"], help="输出格式")
    p_collect.add_argument("--source-names", nargs="+", metavar="NAME", help="只使用指定来源名")
    p_collect.add_argument("--concurrency", type=int, default=3, help="并发采集器数量（默认3）")
    p_collect.set_defaults(func=cmd_collect)

    # schedule
    p_schedule = sub.add_parser("schedule", parents=[parent], help="定时采集模式")
    p_schedule.add_argument("--concurrency", type=int, default=3)
    p_schedule.set_defaults(func=cmd_schedule)

    # sources
    p_sources = sub.add_parser("sources", parents=[parent], help="列出数据源")
    p_sources.set_defaults(func=cmd_sources)

    # validate
    p_validate = sub.add_parser("validate", parents=[parent], help="验证配置文件")
    p_validate.set_defaults(func=cmd_validate)

    return parser


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
