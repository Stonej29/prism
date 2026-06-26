"""Entry point for the PRISM worker (`prism-worker`).

Default: start a blocking scheduler that runs feed ingestion (and, once enabled,
graph traversal) on cron schedules from `feeds.yaml`.

One-shot CLI for manual runs / testing:
    python -m prism.worker ingest      # run feed ingestion once and exit
    python -m prism.worker backup      # commit the vault + snapshot SQLite once
    python -m prism.worker reembed     # re-embed notes with stale embeddings once
"""
from __future__ import annotations

import logging
import os
import sys

from prism.config import load_settings
from prism.services import Services, build_services
from prism.worker.config import WorkerConfig, load_worker_config
from prism.worker.ingest import run_feed_ingestion

LOGGER = logging.getLogger("prism.worker")


def _setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


def _build() -> tuple[Services, WorkerConfig]:
    services = build_services(load_settings(require_telegram=False))
    config = load_worker_config()
    return services, config


def run_ingestion_once() -> None:
    services, config = _build()
    if not config.feeds:
        LOGGER.info("No feeds configured (set PRISM_FEEDS_PATH / feeds.yaml). Nothing to ingest.")
        return
    run_feed_ingestion(services.notes, config.feeds)


def run_backup_once() -> None:
    from prism.worker.backup import run_backup

    services, _ = _build()
    run_backup(services)


def run_reembed_once() -> None:
    from prism.worker.reembed import run_reembed

    services, _ = _build()
    run_reembed(services)


def run_extract_images_once() -> None:
    services, _ = _build()
    summary = services.notes.extract_images_all()
    LOGGER.info(
        "Image backfill: %d image(s) across %d/%d note(s), %d failed",
        summary.images, summary.processed, summary.total, len(summary.errors),
    )


def run_scheduler() -> None:
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    services, config = _build()
    tz = _timezone(config.timezone)
    scheduler = BlockingScheduler(timezone=tz)

    scheduler.add_job(
        lambda: run_feed_ingestion(services.notes, config.feeds),
        CronTrigger.from_crontab(config.ingestion_cron, timezone=tz),
        id="feed_ingestion",
        name="feed ingestion",
        max_instances=1,
        coalesce=True,
    )
    LOGGER.info("Scheduled feed ingestion (%s %s) for %d feed(s)", config.ingestion_cron, config.timezone, len(config.feeds))

    # Graph traversal (3b) registers here once enabled.
    if config.traversal_enabled:
        _register_traversal(scheduler, services, config)

    if config.backup_enabled:
        _register_backup(scheduler, services, config)

    if config.reembed_enabled:
        _register_reembed(scheduler, services, config)

    if os.getenv("PRISM_WORKER_RUN_AT_START") == "1":
        LOGGER.info("PRISM_WORKER_RUN_AT_START=1: running feed ingestion now")
        run_feed_ingestion(services.notes, config.feeds)

    LOGGER.info("PRISM worker started")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        LOGGER.info("PRISM worker stopping")


def _register_traversal(scheduler, services: Services, config: WorkerConfig) -> None:
    try:
        from apscheduler.triggers.cron import CronTrigger

        from prism.worker.traversal import run_graph_traversal
    except Exception:  # traversal module not present yet
        LOGGER.info("Traversal enabled but module unavailable; skipping")
        return
    scheduler.add_job(
        lambda: run_graph_traversal(services, config.traversal),
        CronTrigger.from_crontab(config.traversal_cron, timezone=_timezone(config.timezone)),
        id="graph_traversal",
        name="graph traversal",
        max_instances=1,
        coalesce=True,
    )
    LOGGER.info("Scheduled graph traversal (%s %s)", config.traversal_cron, config.timezone)


def _register_backup(scheduler, services: Services, config: WorkerConfig) -> None:
    from apscheduler.triggers.cron import CronTrigger

    from prism.worker.backup import run_backup

    scheduler.add_job(
        lambda: run_backup(services),
        CronTrigger.from_crontab(config.backup_cron, timezone=_timezone(config.timezone)),
        id="backup",
        name="backup",
        max_instances=1,
        coalesce=True,
    )
    LOGGER.info("Scheduled backup (%s %s)", config.backup_cron, config.timezone)


def _register_reembed(scheduler, services: Services, config: WorkerConfig) -> None:
    from apscheduler.triggers.cron import CronTrigger

    from prism.worker.reembed import run_reembed

    scheduler.add_job(
        lambda: run_reembed(services),
        CronTrigger.from_crontab(config.reembed_cron, timezone=_timezone(config.timezone)),
        id="reembed",
        name="reembed",
        max_instances=1,
        coalesce=True,
    )
    LOGGER.info("Scheduled re-embed (%s %s)", config.reembed_cron, config.timezone)


def _timezone(name: str):
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:
        LOGGER.warning("Unknown timezone %r; falling back to UTC", name)
        from zoneinfo import ZoneInfo

        return ZoneInfo("UTC")


def main(argv: list[str] | None = None) -> None:
    _setup_logging()
    args = argv if argv is not None else sys.argv[1:]
    if args and args[0] == "ingest":
        run_ingestion_once()
        return
    if args and args[0] == "backup":
        run_backup_once()
        return
    if args and args[0] == "reembed":
        run_reembed_once()
        return
    if args and args[0] == "extract_images":
        run_extract_images_once()
        return
    if args and args[0] not in {"run", "serve"}:
        print("Usage: prism-worker [run|ingest|backup|reembed|extract_images]")
        raise SystemExit(2)
    run_scheduler()


if __name__ == "__main__":
    main()
