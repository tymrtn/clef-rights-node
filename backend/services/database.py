from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


@dataclass(frozen=True)
class DatabaseRevisionState:
    expected_heads: frozenset[str]
    current_heads: frozenset[str]

    @property
    def current(self) -> bool:
        return bool(self.expected_heads) and self.current_heads == self.expected_heads


def expected_alembic_heads(backend_root: str | Path) -> frozenset[str]:
    root = Path(backend_root).resolve()
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    return frozenset(ScriptDirectory.from_config(config).get_heads())


def database_revision_state(
    engine: Engine,
    *,
    backend_root: str | Path,
) -> DatabaseRevisionState:
    expected = expected_alembic_heads(backend_root)
    with engine.connect() as connection:
        if not inspect(connection).has_table("alembic_version"):
            current = frozenset()
        else:
            current = frozenset(
                row[0]
                for row in connection.execute(
                    text("SELECT version_num FROM alembic_version")
                )
            )
    return DatabaseRevisionState(expected_heads=expected, current_heads=current)


def require_database_at_head(
    engine: Engine,
    *,
    backend_root: str | Path,
) -> DatabaseRevisionState:
    state = database_revision_state(engine, backend_root=backend_root)
    if not state.current:
        expected = ", ".join(sorted(state.expected_heads)) or "<no migration head>"
        current = ", ".join(sorted(state.current_heads)) or "<unversioned>"
        raise RuntimeError(
            "Database migration revision is not current "
            f"(expected {expected}; found {current}). Run `alembic upgrade head` "
            "before starting the Rights Node."
        )
    return state
