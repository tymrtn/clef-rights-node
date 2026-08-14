import argparse
import datetime
import json
import uuid
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import RightsContractRecord, RightsHistoryRecord
from main import compute_effective_matrix, default_contract_template
from services.database import require_database_at_head
from services.settings import Settings


def load_fixtures(path: Path):
    with path.open() as f:
        data = json.load(f)
    # Accept either {items: [...]} or list
    if isinstance(data, dict) and "items" in data:
        return data["items"]
    if isinstance(data, list):
        return data
    raise ValueError("Fixture file must be a list or contain an 'items' list")


def upsert_contract(session, key: str, artist: str, contract: dict, note: str | None = None):
    now = datetime.datetime.utcnow()
    record = (
        session.query(RightsContractRecord)
        .filter(RightsContractRecord.key == key, RightsContractRecord.artist == artist)
        .order_by(RightsContractRecord.version.desc())
        .first()
    )
    version = 1
    if record:
        version = record.version + 1
    else:
        record = RightsContractRecord(
            id=str(uuid.uuid4()),
            key=key,
            artist=artist,
            created_at=now,
        )
    compute_effective_matrix(contract)
    record.contract_json = contract
    record.effective_matrix = contract.get("matrix")
    record.version = version
    record.updated_at = now
    session.merge(record)
    session.flush()

    history = RightsHistoryRecord(
        contract_id=record.id,
        key=key,
        artist=artist,
        version=version,
        editor="seed-script",
        batch_id=None,
        note=note,
        contract_json=contract,
        effective_matrix=contract.get("matrix"),
        created_at=now,
    )
    session.add(history)


def main():
    parser = argparse.ArgumentParser(description="Seed Rights Console data from fixtures")
    parser.add_argument("--fixtures", type=Path, required=True, help="Path to sample_catalog.json")
    args = parser.parse_args()

    settings = Settings()
    connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args=connect_args,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_pre_ping=True,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    require_database_at_head(engine, backend_root=Path(__file__).resolve().parent)

    fixtures = load_fixtures(args.fixtures)
    with SessionLocal() as session:
        for item in fixtures:
            key = item.get("key") or str(uuid.uuid4())
            artist = item.get("artist") or "Demo Artist"
            contract = item.get("contract") or default_contract_template(artist)
            note = item.get("note")
            upsert_contract(session, key, artist, contract, note=note)
        session.commit()
    print(f"Seeded {len(fixtures)} contracts from {args.fixtures}")


if __name__ == "__main__":
    main()
