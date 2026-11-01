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
    assert expected == frozenset({"0021_federated_requests"})

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


def test_privacy_migration_preserves_existing_receipt_bytes(tmp_path, monkeypatch):
    import json
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect
    from models import PermissionReceiptRecord
    from services.receipts import ReceiptSigner

    url = f"sqlite:///{tmp_path / 'upgrade.sqlite'}"
    monkeypatch.setenv('DATABASE_URL', url)
    config = Config(str(BACKEND_ROOT / 'alembic.ini'))
    config.set_main_option('script_location', str(BACKEND_ROOT / 'alembic'))
    command.upgrade(config, '0016_service_heartbeats')
    engine = create_engine(url)
    original = ReceiptSigner(node_id='urn:test:legacy', private_key_b64=None, app_env='test').sign_receipt(
        payload={'schemaVersion':'clef.permission-receipt.v1','receiptId':'legacy-receipt',
                 'agreement':{'note':'Original private terms é'}},
        transparency_sequence=1, previous_entry_hash=None)
    proof = original['proof']; log = original['transparency']
    with engine.begin() as connection:
        # Insert directly to model an existing v0016 signed envelope. SQLite FKs are
        # intentionally off in this isolated fixture; this tests unchanged storage bytes.
        connection.execute(PermissionReceiptRecord.__table__.insert().values(
            id='legacy-receipt', permission_request_id='legacy-permission', receipt_kind='grant',
            schema_version='clef.permission-receipt.v1', node_id='urn:test:legacy', payload=original['payload'],
            payload_hash=proof['payloadHash'], signature=proof['signature'], public_key=proof['publicKey'],
            key_id=proof['keyId'], transparency_sequence=1, previous_entry_hash=None, entry_hash=log['entryHash']))
        before = tuple(connection.execute(text('SELECT * FROM rn_permission_receipts')).one())
    command.upgrade(config, 'head')
    with engine.connect() as connection:
        after = tuple(connection.execute(text('SELECT * FROM rn_permission_receipts')).one())
        assert after == before
        assert connection.execute(text('SELECT count(*) FROM rn_receipt_disclosures')).scalar_one() == 0
        assert connection.execute(text('SELECT count(*) FROM rn_organization_privacy')).scalar_one() == 0
    assert {'rn_receipt_disclosures', 'rn_organization_privacy', 'rn_privacy_erasure_requests'} <= set(inspect(engine).get_table_names())
    assert require_database_at_head(engine, backend_root=BACKEND_ROOT).current
    assert ReceiptSigner.verify_receipt(original).valid
    engine.dispose()


@pytest.mark.parametrize('table, values', [
    ('rn_organization_privacy', {'org_id': 'fixture-org'}),
    ('rn_receipt_disclosures', {'receipt_id': 'fixture-receipt', 'public_id': 'fixture-public',
       'authority_org_id': 'fixture-org', 'requester_org_id': 'fixture-requester', 'private_commitment': 'fixture-commitment'}),
    ('rn_privacy_erasure_requests', {'id': 'fixture-erasure', 'org_id': 'fixture-org', 'kind': 'receipt',
       'resource_id': 'fixture-receipt', 'resource_hash': 'fixture-hash', 'required_org_ids': '[]', 'approved_org_ids': '[]'}),
    ('rn_sandbox_tours', {'user_id': 'fixture-guest', 'manifest': '{"title":"Fictional saved example"}'}),
    ('rn_catalog_publications', {'id': 'fixture-publication', 'org_id': 'fixture-org',
       'authority_claim_id': 'fixture-claim', 'public_payload': '{}', 'search_text': '', 'basis_hash': 'hash',
       'revision': 1, 'approved_by_user_id': 'fixture-user', 'approved_at': '2026-09-18'}),
    ('rn_catalog_import_rows', {'id':'fixture-row', 'batch_id':'fixture-batch', 'row_number':2,
       'source_json':'{}', 'normalized_json':'{}', 'status':'ready', 'errors':'[]',
       'review_basis':'a' * 64, 'created_at':'2026-09-18'}),
    ('rn_federated_inbound_requests', {'id':'fixture-inbound', 'peer_node_id':'urn:peer', 'request_id':'fixture-request-0001',
       'statement_hash':'hash', 'statement':'{}', 'permission_request_id':'fixture-permission', 'received_at':'2026-11-01'}),
    ('rn_federated_outbound_requests', {'id':'fixture-outbound-0001', 'requester_org_id':'fixture-org', 'peer_id':'peer',
       'peer_node_id':'urn:peer', 'peer_origin':'https://peer.example.test', 'publication_id':'fixture-publication',
       'request_statement':'{}', 'status':'pending', 'created_at':'2026-11-01'}),
])
def test_downgrades_preserve_existing_privacy_and_tour_records(tmp_path, monkeypatch, table, values):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    url = f"sqlite:///{tmp_path / 'downgrade.sqlite'}"
    monkeypatch.setenv('DATABASE_URL', url)
    config = Config(str(BACKEND_ROOT / 'alembic.ini'))
    config.set_main_option('script_location', str(BACKEND_ROOT / 'alembic'))
    revision, previous = {
        'rn_sandbox_tours': ('0018_sandbox_tour', '0017_receipt_privacy'),
        'rn_catalog_publications': ('0019_catalog_federation', '0018_sandbox_tour'),
        'rn_catalog_import_rows': ('0020_catalog_review_basis', '0019_catalog_federation'),
        'rn_federated_inbound_requests': ('0021_federated_requests', '0020_catalog_review_basis'),
        'rn_federated_outbound_requests': ('0021_federated_requests', '0020_catalog_review_basis'),
    }.get(table, ('0017_receipt_privacy', '0016_service_heartbeats'))
    command.upgrade(config, revision)
    engine = create_engine(url)
    # Isolated fixture with FKs disabled: verify migration refusal and untouched bytes.
    with engine.begin() as connection:
        connection.execute(text(f"INSERT INTO {table} ({', '.join(values)}) VALUES ({', '.join(':' + key for key in values)})"), values)
        before = tuple(connection.execute(text(f'SELECT * FROM {table}')).one())
    with pytest.raises(RuntimeError, match='Downgrade blocked'):
        command.downgrade(config, previous)
    assert table in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert tuple(connection.execute(text(f'SELECT * FROM {table}')).one()) == before
        assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == revision
    engine.dispose()


def test_empty_privacy_and_tour_tables_can_downgrade_and_upgrade(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    url = f"sqlite:///{tmp_path / 'empty.sqlite'}"
    monkeypatch.setenv('DATABASE_URL', url)
    config = Config(str(BACKEND_ROOT / 'alembic.ini'))
    config.set_main_option('script_location', str(BACKEND_ROOT / 'alembic'))
    command.upgrade(config, 'head')
    command.downgrade(config, '0016_service_heartbeats')
    command.upgrade(config, 'head')
    command.check(config)
