"""Independent additive schema; Clawith owns existing authentication and Runtime tables."""

import asyncio

from sqlalchemy.schema import CreateSchema

from alembic import context
from app.database import engine
from app.services.desktop_automation.models import AutomationBase


def configure(connection):
    context.configure(
        connection=connection,
        target_metadata=AutomationBase.metadata,
        version_table="alembic_version",
        version_table_schema="desktop_automation",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run():
    async with engine.connect() as connection:
        await connection.execute(CreateSchema("desktop_automation", if_not_exists=True))
        await connection.commit()
        await connection.run_sync(configure)
    await engine.dispose()


asyncio.run(run())
