import hashlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cqrs import attach_artifact, complete_run, start_run
from app.database import Base
from app.models import RunProjection
from app.verification import list_artifacts, verify_artifact


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    from sqlalchemy import JSON
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.ext.compiler import compiles

    @compiles(JSONB, "sqlite")
    def _compile_jsonb_sqlite(_type, compiler, **kw):
        return "JSON"

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _attach_one(db):
    run = start_run(
        db,
        actor="researcher",
        project="p1",
        name="n1",
        dataset_content_sha256=sha("ds"),
        code_commit_sha="abc1234",
        description=None,
    )
    run = attach_artifact(
        db,
        run_id=run.id,
        actor="researcher",
        name="model.bin",
        uri="s3://bucket/model.bin",
        content_sha256=sha("model"),
        media_type="application/octet-stream",
        expected_version=run.version,
    )
    return run


def test_ledger_lists_artifacts_across_runs(db):
    run = _attach_one(db)
    ledger = list_artifacts(db)
    assert len(ledger) == 1
    item = ledger[0]
    assert item["run_id"] == run.id
    assert item["project"] == "p1"
    assert item["run_name"] == "n1"
    assert item["uri"] == "s3://bucket/model.bin"
    assert item["content_sha256"] == sha("model")
    assert item["artifact_index"] == 0


def test_verify_passes_for_valid_seed_style_artifact(db):
    run = _attach_one(db)
    result = verify_artifact(db, run_id=run.id, artifact_index=0)
    assert result["passed"] is True
    keys = {c["key"]: c for c in result["checks"]}
    assert all(c["passed"] for c in result["checks"])
    assert keys["sha_nonempty"]["passed"]
    assert keys["sha_format"]["passed"]
    assert keys["event_consistency"]["passed"]


def test_verify_fails_on_tampered_projection(db):
    run = _attach_one(db)
    proj = db.get(RunProjection, run.id)
    proj.artifacts_json = [{**proj.artifacts_json[0], "content_sha256": "deadbeef"}]
    db.commit()

    result = verify_artifact(db, run_id=run.id, artifact_index=0)
    assert result["passed"] is False
    keys = {c["key"]: c for c in result["checks"]}
    assert keys["sha_format"]["passed"] is False
    assert keys["event_consistency"]["passed"] is False


def test_verify_fails_on_empty_sha(db):
    run = _attach_one(db)
    proj = db.get(RunProjection, run.id)
    proj.artifacts_json = [{**proj.artifacts_json[0], "content_sha256": ""}]
    db.commit()

    result = verify_artifact(db, run_id=run.id, artifact_index=0)
    assert result["passed"] is False
    keys = {c["key"]: c for c in result["checks"]}
    assert keys["sha_nonempty"]["passed"] is False
    assert keys["sha_format"]["passed"] is False


def test_verify_index_out_of_range(db):
    run = _attach_one(db)
    result = verify_artifact(db, run_id=run.id, artifact_index=7)
    assert result["passed"] is False
    assert "索引越界" in result["message"]


def test_ledger_includes_artifacts_from_completed_runs(db):
    run = _attach_one(db)
    complete_run(db, run_id=run.id, actor="researcher", result_summary="done", expected_version=run.version)
    ledger = list_artifacts(db)
    assert len(ledger) == 1
    assert ledger[0]["run_status"] == "completed"
