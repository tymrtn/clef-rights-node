import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Base, ServiceHeartbeatRecord
from services.worker_heartbeat import record_service_heartbeat


def test_worker_heartbeat_upserts_success_and_redacts_failure_detail():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    first = datetime.datetime(2026, 8, 14, 10, 0, 0)
    second = first + datetime.timedelta(minutes=1)
    try:
        row = record_service_heartbeat(
            session,
            service_name="webhook_worker",
            succeeded=True,
            details={"selected": 2, "delivered": 2},
            attempted_at=first,
        )
        assert row.status == "healthy"
        assert row.last_success_at == first

        row = record_service_heartbeat(
            session,
            service_name="webhook_worker",
            succeeded=False,
            error_type="ConnectionError",
            attempted_at=second,
        )
        assert row.status == "error"
        assert row.last_attempt_at == second
        assert row.last_success_at == first
        assert row.details == {"errorType": "ConnectionError"}
        assert session.query(ServiceHeartbeatRecord).count() == 1
    finally:
        session.close()
