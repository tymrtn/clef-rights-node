#!/usr/bin/env python3
"""Force grant/withdrawal overlap against a fresh, isolated SQLite or PostgreSQL DB."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import tempfile
import threading
from verify_rightsholder_workflow import BACKEND, configure_environment, require_empty_postgres


def run(database_path, database_url=None):
    if database_url:
        require_empty_postgres(database_url)
    configure_environment(database_path, 'concurrency-operator@example.test', database_url=database_url)
    os.environ.update(NODE_DEPLOYMENT_MODE='public_sandbox', SANDBOX_GUEST_ACCESS='true',
        FEDERATION_ENABLED='false', FEDERATION_PEERS_JSON='[]', AUTH_SIGNUP_MODE='operator_only', WEBHOOK_DELIVERY_ENABLED='false', DDEX_LIVE_MESSAGES='false')
    from alembic import command
    from alembic.config import Config
    config = Config(str(BACKEND / 'alembic.ini'))
    config.set_main_option('script_location',str(BACKEND / 'alembic'))
    command.upgrade(config,'head')
    from fastapi.testclient import TestClient
    from sqlalchemy import event
    import main
    main.limiter.enabled=False
    postgres=main.engine.dialect.name=='postgresql'
    if postgres:
        @event.listens_for(main.engine, 'checkout')
        def timeout(dbapi_connection, *_):
            # Bound a broken lock order rather than leaving CI stuck.
            with dbapi_connection.cursor() as cursor:
                cursor.execute("SET statement_timeout = '8s'")
    grant_boundary=threading.Event(); withdrawal_boundary=threading.Event(); resume=threading.Event()
    original=main._issue_permission_receipt
    def paused_issue(*args,**kwargs):
        grant_boundary.set()
        if not resume.wait(10): raise RuntimeError('Grant barrier timed out')
        return original(*args,**kwargs)
    def before_sql(_conn,_cursor,statement,_parameters,_context,_many):
        if grant_boundary.is_set() and 'rn_authority_claims.org_id =' in statement and 'FOR UPDATE' in statement:
            withdrawal_boundary.set()
    with TestClient(main.app, raise_server_exceptions=False) as client:
        session=client.post('/v1/sandbox/session')
        assert session.status_code==200, 'Synthetic guest setup failed'
        headers={'X-Session-Id':session.json()['session']['id']}
        prepared=client.post('/v1/sandbox/tour',headers=headers)
        assert prepared.status_code==200, 'Synthetic catalog setup failed'
        side=prepared.json()['sides'][0]
        root=f"/v1/organizations/{side['orgId']}/authority-claims/{side['authority']['id']}"
        preview=client.get(root+'/withdrawal-preview',headers=headers)
        assert preview.status_code==200
        withdraw={'expected_digest':preview.json()['expectedDigest'], 'reason':'Fictional mandate ended', 'confirm_withdrawal':True}
        approval={'decision':'approved','note':'Fictional bounded generation approval','obligations':{
            'attribution':{'required':True,'credit_text':'Paper Skies — Mara Vale (fictional sandbox example)','placements':['description','metadata']},
            'publication_reporting_required':True,'publication_evidence_due_days':30,'usage_reporting_frequency':'once'}}
        main._issue_permission_receipt=paused_issue
        event.listen(main.engine,'before_cursor_execute',before_sql)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                grant=pool.submit(client.post,f"/v1/permission-requests/{side['permissionId']}/decide",headers=headers,json=approval)
                assert grant_boundary.wait(5), 'Approval did not reach the receipt boundary'
                withdrawal=pool.submit(client.post,root+'/withdraw',headers=headers,json=withdraw)
                if postgres:
                    assert withdrawal_boundary.wait(5), 'Withdrawal did not reach the claim lock'
                else:
                    # The entire SQLite approval owns the local decision lock. A
                    # withdrawal cannot commit against its pre-decision snapshot.
                    threading.Event().wait(.15)
                    assert not withdrawal.done(), 'Withdrawal bypassed an active SQLite decision'
                resume.set()
                grant_result=grant.result(timeout=12); withdrawal_result=withdrawal.result(timeout=12)
            assert grant_result.status_code==200, f'Concurrent approval returned {grant_result.status_code}'
            assert withdrawal_result.status_code==200, f'Concurrent withdrawal returned {withdrawal_result.status_code}'
            assert withdrawal_result.json()['approvedGrants']==1
            assert client.post('/v1/receipts/verify',json={'receipt':grant_result.json()['receipt']}).json()['valid']
            assert client.post('/v1/permission-requests',headers=headers,json=side['request']).status_code==409
            # The accepted grant is ordered before withdrawal; no later grant is possible.
            current=client.get(f"/v1/permission-requests/{side['permissionId']}",headers=headers).json()
            assert current['status']=='approved'
        finally:
            resume.set(); main._issue_permission_receipt=original
            event.remove(main.engine,'before_cursor_execute',before_sql)
    main.engine.dispose()
    return {'ok':True,'database':'postgresql' if postgres else 'sqlite', 'forcedOverlap':True,
        'grantBeforeWithdrawal':True,'laterRequestBlocked':True,'signedReceiptValid':True,'externalRequests':0}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--postgres-test-url-env',help='Environment variable naming a dedicated empty PostgreSQL database')
    args=parser.parse_args()
    url=os.environ.get(args.postgres_test_url_env,'') if args.postgres_test_url_env else None
    if args.postgres_test_url_env and not url: parser.error('The PostgreSQL test environment variable is empty')
    with tempfile.TemporaryDirectory(prefix='clef-authority-concurrency-') as temporary:
        print(json.dumps(run(Path(temporary)/'rights.db',url)))
