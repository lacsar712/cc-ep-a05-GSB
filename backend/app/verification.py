"""产物指纹校验：格式校验 + 与 event_store 原始事件一致性比对。"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EventStore, RunProjection

SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

CHECKS = {
    "sha_nonempty": "指纹非空",
    "sha_format": "SHA-256 格式（64 位小写十六进制）",
    "uri_nonempty": "URI 非空",
    "event_consistency": "与 event_store 事件指纹一致",
}


def list_artifacts(db: Session) -> list[dict[str, Any]]:
    """跨 Run 汇总已挂载产物（查询侧：读投影）。"""
    stmt = select(RunProjection).order_by(RunProjection.started_at.desc())
    runs = list(db.scalars(stmt).all())
    ledger: list[dict[str, Any]] = []
    for run in runs:
        for index, artifact in enumerate(run.artifacts_json or []):
            ledger.append(
                {
                    "run_id": run.id,
                    "project": run.project,
                    "run_name": run.name,
                    "run_status": run.status,
                    "name": artifact.get("name"),
                    "uri": artifact.get("uri", ""),
                    "content_sha256": artifact.get("content_sha256", ""),
                    "media_type": artifact.get("media_type"),
                    "attached_at": artifact.get("attached_at"),
                    "attached_by": artifact.get("actor"),
                    "artifact_index": index,
                }
            )
    return ledger


def _checks(sha: str, uri: str, event_sha: str | None) -> list[dict[str, Any]]:
    def item(key: str, ok: bool, detail: str) -> dict[str, Any]:
        return {"key": key, "label": CHECKS[key], "passed": ok, "detail": detail}

    nonempty = bool(sha and sha.strip())
    well_formed = bool(nonempty and SHA256_HEX_RE.match(sha.strip()))
    uri_ok = bool(uri and uri.strip())
    checks = [
        item("sha_nonempty", nonempty, "指纹非空" if nonempty else "指纹为空"),
        item(
            "sha_format",
            well_formed,
            "符合 64 位十六进制" if well_formed else "不符合 SHA-256（64 位小写十六进制）",
        ),
        item("uri_nonempty", uri_ok, "URI 非空" if uri_ok else "URI 为空"),
    ]
    if event_sha is None:
        checks.append(item("event_consistency", False, "未在 event_store 找到对应 ArtifactAttached 事件"))
    else:
        ok = nonempty and sha.strip().lower() == event_sha.lower()
        checks.append(
            item(
                "event_consistency",
                ok,
                "投影与原始事件指纹一致" if ok else f"投影指纹与事件不一致（事件记录 {event_sha}）",
            )
        )
    return checks


def verify_artifact(
    db: Session,
    *,
    run_id: UUID,
    artifact_index: int,
) -> dict[str, Any]:
    """校验单条产物指纹，返回逐项检查结果与通过/失败结论。"""
    proj = db.get(RunProjection, run_id)
    if proj is None:
        return {"passed": False, "checks": [], "message": "所属 Run 不存在"}

    artifacts = proj.artifacts_json or []
    if artifact_index < 0 or artifact_index >= len(artifacts):
        return {"passed": False, "checks": [], "message": "产物不存在（索引越界）"}

    artifact = artifacts[artifact_index]
    sha = (artifact.get("content_sha256") or "").strip()
    uri = artifact.get("uri") or ""

    # 从 event_store 取该 Run 的 ArtifactAttached 事件，按挂载顺序对齐
    stmt = (
        select(EventStore)
        .where(EventStore.aggregate_id == run_id, EventStore.event_type == "ArtifactAttached")
        .order_by(EventStore.version.asc())
    )
    events = list(db.scalars(stmt).all())
    event_sha: str | None = None
    if artifact_index < len(events):
        event_sha = (events[artifact_index].payload_json or {}).get("content_sha256")

    checks = _checks(sha, uri, event_sha)
    passed = all(c["passed"] for c in checks)
    return {
        "passed": passed,
        "checks": checks,
        "message": "校验通过：指纹格式有效，且与 event_store 一致"
        if passed
        else "校验失败：存在未通过的检查项",
    }
