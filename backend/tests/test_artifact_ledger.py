import hashlib

from app.cqrs import (
    DomainError,
    attach_artifact,
    complete_run,
    list_artifacts,
    start_run,
    verify_artifact,
)


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _make_run_with_artifact(db, *, run_id=None, project="p1", name="n1", digest=None):
    run = start_run(
        db,
        actor="researcher",
        project=project,
        name=name,
        dataset_content_sha256=sha("ds"),
        code_commit_sha="abc1234",
        description=None,
        run_id=run_id,
    )
    run = attach_artifact(
        db,
        run_id=run.id,
        actor="researcher",
        name="model.bin",
        uri="s3://bucket/model.bin",
        content_sha256=digest or sha("model"),
        media_type="application/octet-stream",
        expected_version=run.version,
    )
    return run


def test_list_artifacts_across_runs(db):
    run1 = _make_run_with_artifact(db, project="p1", name="run-a")
    run2 = _make_run_with_artifact(
        db, project="p2", name="run-b", digest=sha("other")
    )

    ledger = list_artifacts(db)
    assert len(ledger) == 2
    by_run = {item["run_id"]: item for item in ledger}
    assert set(by_run) == {run1.id, run2.id}
    item = by_run[run2.id]
    assert item["uri"] == "s3://bucket/model.bin"
    assert item["content_sha256"] == sha("other")
    assert item["project"] == "p2"
    assert item["run_name"] == "run-b"


def test_verify_artifact_passes_for_valid_sha(db):
    run = _make_run_with_artifact(db, digest=sha("seed-structure"))
    result = verify_artifact(db, run_id=run.id, uri="s3://bucket/model.bin")
    assert result["passed"] is True
    assert {c["name"] for c in result["checks"]} == {"指纹非空", "SHA-256 格式"}
    assert all(c["passed"] for c in result["checks"])
    assert result["content_sha256"] == sha("seed-structure")


def test_verify_artifact_fails_for_malformed_sha(db):
    # 直接写入一条指纹格式非法的产物投影，绕过命令层校验，模拟脏数据
    run = _make_run_with_artifact(db)
    artifacts = list(run.artifacts_json)
    artifacts.append(
        {
            "name": "corrupt.txt",
            "uri": "s3://bucket/corrupt.txt",
            "content_sha256": "not-a-sha256",
            "media_type": "text/plain",
            "attached_at": None,
            "actor": "researcher",
        }
    )
    run.artifacts_json = artifacts
    db.commit()

    result = verify_artifact(db, run_id=run.id, uri="s3://bucket/corrupt.txt")
    assert result["passed"] is False
    by_name = {c["name"]: c for c in result["checks"]}
    assert by_name["指纹非空"]["passed"] is True
    assert by_name["SHA-256 格式"]["passed"] is False


def test_verify_artifact_fails_for_empty_sha(db):
    run = _make_run_with_artifact(db)
    artifacts = list(run.artifacts_json)
    artifacts.append(
        {
            "name": "empty.bin",
            "uri": "s3://bucket/empty.bin",
            "content_sha256": "",
            "media_type": None,
            "attached_at": None,
            "actor": "researcher",
        }
    )
    run.artifacts_json = artifacts
    db.commit()

    result = verify_artifact(db, run_id=run.id, uri="s3://bucket/empty.bin")
    assert result["passed"] is False
    by_name = {c["name"]: c for c in result["checks"]}
    assert by_name["指纹非空"]["passed"] is False
    assert by_name["SHA-256 格式"]["passed"] is False


def test_verify_unknown_artifact_raises(db):
    run = _make_run_with_artifact(db)
    import pytest
    from uuid import uuid4

    with pytest.raises(DomainError):
        verify_artifact(db, run_id=run.id, uri="s3://bucket/missing.bin")
    with pytest.raises(DomainError):
        verify_artifact(db, run_id=uuid4(), uri="s3://bucket/model.bin")
