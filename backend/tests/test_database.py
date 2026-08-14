from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from services.database import (
    database_revision_state,
    expected_alembic_heads,
    require_database_at_head,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_database_revision_check_fails_closed_until_migration_head_is_recorded():
    engine = create_engine("sqlite:///:memory:")
    expected = expected_alembic_heads(BACKEND_ROOT)
    assert expected == frozenset({"0015_permission_administration"})

    unversioned = database_revision_state(engine, backend_root=BACKEND_ROOT)
    assert unversioned.current is False
    with pytest.raises(RuntimeError, match="Run `alembic upgrade head`"):
        require_database_at_head(engine, backend_root=BACKEND_ROOT)

    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
            {"revision": next(iter(expected))},
        )

    current = require_database_at_head(engine, backend_root=BACKEND_ROOT)
    assert current.current is True
    assert current.current_heads == expected
