import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models.workspace import WorkspaceMember
from app.services import notification_service
from app.worker import celery_app

logger = logging.getLogger(__name__)


def _make_session_maker():
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _generate_all() -> int:
    engine, session_maker = _make_session_maker()
    try:
        total = 0
        async with session_maker() as session:
            rows = await session.execute(
                select(WorkspaceMember.workspace_id, WorkspaceMember.user_id)
            )
            pairs = [(r[0], r[1]) for r in rows.all()]

        for workspace_id, user_id in pairs:
            try:
                async with session_maker() as session:
                    created = await notification_service.generate_for_workspace(
                        session, workspace_id, user_id
                    )
                    total += created
            except Exception:
                logger.exception(
                    "notification generation failed for ws=%s user=%s", workspace_id, user_id
                )
    finally:
        await engine.dispose()
    return total


@celery_app.task(name="app.tasks.notification_tasks.generate_all_notifications")
def generate_all_notifications() -> dict:
    total = asyncio.run(_generate_all())
    logger.info("Notification generation complete: %d created", total)
    return {"created": total}
