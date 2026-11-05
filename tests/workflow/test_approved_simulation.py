from collections.abc import Iterator
from pathlib import Path

import pytest
from atlas_api.main import create_app
from atlas_api.main import database as database_dependency
from atlas_campaigns.database import Connection
from atlas_campaigns.execution import execute_next
from fastapi.testclient import TestClient


def test_http_to_outbox_to_real_vendor_simulator(
    database: Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATLAS_LOCAL_DEMO_AUTH", "true")
    app = create_app()

    def connection() -> Iterator[Connection]:
        yield database

    app.dependency_overrides[database_dependency] = connection
    scientist = {"Authorization": "Bearer local-scientist", "Idempotency-Key": "create"}
    reviewer = {"Authorization": "Bearer local-reviewer", "Idempotency-Key": "approve"}
    with TestClient(app) as client:
        created = client.post(
            "/v1/campaigns",
            headers=scientist,
            json={
                "dataset_snapshot_id": "synthetic-snapshot",
                "campaign_group_id": "synthetic-group",
            },
        )
        assert created.status_code == 201
        campaign_id = created.json()["data"]["id"]
        proposed = client.post(
            f"/v1/campaigns/{campaign_id}/plan",
            headers={**scientist, "Idempotency-Key": "plan"},
            json={"expected_version": 0},
        )
        assert proposed.status_code == 201
        batch = proposed.json()["data"]
        approved = client.post(
            f"/v1/campaigns/{campaign_id}/batches/{batch['id']}/approve",
            headers=reviewer,
            json={"expected_version": 0, "plan_hash": batch["plan_hash"]},
        )
        assert approved.status_code == 200
        run_id = batch["run_id"]
        queued = client.post(
            f"/v1/runs/{run_id}/simulate",
            headers={**scientist, "Idempotency-Key": "dispatch"},
            json={"expected_version": 0},
        )
        assert queued.status_code == 202
        assert queued.json()["data"]["status"] == "DISPATCH_PENDING"
        completed = execute_next(database, tmp_path / "runs")
        assert completed is not None and completed["status"] == "SIMULATED"
        assert execute_next(database, tmp_path / "runs") is None
        result = client.get(f"/v1/runs/{run_id}", headers=scientist).json()["data"]
        assert result["status"] == "SIMULATED"
        assert (Path(result["artifact_directory"]) / "receipt/receipt.json").exists()
        events = client.get(f"/v1/runs/{run_id}/events", headers=scientist).json()["data"]
        assert [event["sequence"] for event in events] == [1, 2, 3, 4, 5, 6]
