"""Celery side of consumer receipts.

Three tasks: `fetch_receipt` is one attempt on one receipt and is what
`POST /scan` dispatches; `sweep_due` runs on beat every minute and
dispatches whatever is due (including claims left by a dead worker and
pages an improved parser should re-read); `expire_raw_html` drops stored
pages past their TTL once a day.

Each run builds its own engine and Redis client: `asyncio.run` gives every
task a fresh event loop, and connections bound to a previous loop do not
survive that.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

import redis.asyncio as redis_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models.receipt import Receipt
from app.receipts.fetcher import Fetcher, RedisGate
from app.services import price_service, receipt_service
from app.worker import celery_app

logger = logging.getLogger(__name__)


def _make_session_maker():
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _make_fetcher(redis_client: redis_asyncio.Redis) -> Fetcher:
    settings = get_settings()
    return Fetcher(
        RedisGate(redis_client),
        timeout_seconds=settings.receipts_fetch_timeout_seconds,
        min_interval_ms=settings.receipts_min_interval_ms,
        circuit_failures=settings.receipts_circuit_failures,
        circuit_open_seconds=settings.receipts_circuit_open_seconds,
        user_agent=settings.receipts_user_agent,
    )


async def _fetch_one(receipt_id: uuid.UUID) -> str:
    engine, session_maker = _make_session_maker()
    redis_client = redis_asyncio.from_url(get_settings().redis_url, decode_responses=True)
    try:
        async with session_maker() as session:
            receipt = await receipt_service.process_receipt(
                session, receipt_id, fetcher=_make_fetcher(redis_client)
            )
            return receipt.status if receipt is not None else "skipped"
    finally:
        await redis_client.aclose()
        await engine.dispose()


async def _sweep() -> int:
    engine, session_maker = _make_session_maker()
    try:
        async with session_maker() as session:
            due = await receipt_service.due_receipt_ids(session)
            stale = await receipt_service.stale_parse_error_ids(session)
            unenriched = await price_service.unenriched_receipt_ids(session)
        for receipt_id in [*due, *stale]:
            fetch_receipt.delay(str(receipt_id))
        for receipt_id in unenriched:
            enrich_receipt.delay(str(receipt_id))
        return len(due) + len(stale) + len(unenriched)
    finally:
        await engine.dispose()


async def _enrich_one(receipt_id: uuid.UUID) -> int:
    """Notes authorised before the catalogue existed, or whose enrichment
    did not finish: place their lines and refresh every workspace's
    variation. Never touches the portal."""
    engine, session_maker = _make_session_maker()
    try:
        async with session_maker() as session:
            receipt = await session.get(Receipt, receipt_id)
            if receipt is None:
                return 0
            placed = await price_service.enrich_receipt(session, receipt)
            await price_service.refresh_variations(session, receipt)
            await session.commit()
            return placed
    finally:
        await engine.dispose()


async def _expire() -> int:
    engine, session_maker = _make_session_maker()
    try:
        async with session_maker() as session:
            return await receipt_service.expire_raw_html(session)
    finally:
        await engine.dispose()


@celery_app.task(name="app.tasks.receipt_tasks.fetch_receipt")
def fetch_receipt(receipt_id: str) -> str:
    result = asyncio.run(_fetch_one(uuid.UUID(receipt_id)))
    logger.info("receipt %s: %s", receipt_id, result)
    return result


@celery_app.task(name="app.tasks.receipt_tasks.sweep_due")
def sweep_due() -> int:
    count = asyncio.run(_sweep())
    if count:
        logger.info("receipt sweep dispatched %d", count)
    return count


@celery_app.task(name="app.tasks.receipt_tasks.enrich_receipt")
def enrich_receipt(receipt_id: str) -> int:
    placed = asyncio.run(_enrich_one(uuid.UUID(receipt_id)))
    logger.info("receipt %s: %d lines placed in the catalogue", receipt_id, placed)
    return placed


@celery_app.task(name="app.tasks.receipt_tasks.expire_raw_html")
def expire_raw_html() -> int:
    count = asyncio.run(_expire())
    if count:
        logger.info("expired raw html on %d receipts", count)
    return count
