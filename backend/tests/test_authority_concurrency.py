import json
from pathlib import Path
import subprocess
import sys


def test_actual_sqlite_api_serializes_withdrawal_against_grant_issuance():
    root=Path(__file__).resolve().parents[2]
    result=subprocess.run([sys.executable,str(root/'scripts/verify_authority_concurrency.py')],
        cwd=root, capture_output=True,text=True,timeout=40)
    assert result.returncode==0, result.stdout+result.stderr
    report=json.loads(result.stdout.strip().splitlines()[-1])
    assert report['ok'] and report['forcedOverlap'] and report['signedReceiptValid']
    assert report['externalRequests']==0
