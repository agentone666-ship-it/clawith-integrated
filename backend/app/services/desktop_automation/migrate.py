"""Apply only the feature-owned migration stream; Runtime revisions remain unchanged."""

from pathlib import Path

from alembic.config import Config

from alembic import command


def migrate() -> None:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    command.upgrade(config, "head")


if __name__ == "__main__":
    migrate()
