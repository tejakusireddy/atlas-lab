from collections.abc import Iterator

import pytest
from atlas_api.main import create_app
from atlas_api.main import database as database_dependency
from atlas_campaigns.database import Connection
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


@pytest.fixture
def client(database: Connection, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("ATLAS_LOCAL_DEMO_AUTH", "true")
    app = create_app()

    def connection() -> Iterator[Connection]:
        yield database

    app.dependency_overrides[database_dependency] = connection
    with TestClient(app) as test_client:
        yield test_client


def payload() -> dict[str, str]:
    return {"dataset_snapshot_id": "synthetic-snapshot", "campaign_group_id": "synthetic-group"}


def headers(key: str = "test-key", actor: str = "scientist") -> dict[str, str]:
    return {"Authorization": f"Bearer local-{actor}", "Idempotency-Key": key}


def test_create_get_list_and_duplicate(client: TestClient) -> None:
    first = client.post("/v1/campaigns", json=payload(), headers=headers())
    assert first.status_code == 201
    body = first.json()
    assert body["errors"] == []
    assert body["meta"]["request_id"] == first.headers["x-request-id"]
    campaign_id = body["data"]["id"]
    duplicate = client.post("/v1/campaigns", json=payload(), headers=headers())
    assert duplicate.json()["data"]["id"] == campaign_id
    assert client.get(f"/v1/campaigns/{campaign_id}", headers=headers()).status_code == 200
    assert len(client.get("/v1/campaigns", headers=headers()).json()["data"]) == 1
    assert (
        client.get(f"/v1/campaigns/{campaign_id}", headers=headers(actor="viewer")).status_code
        == 404
    )


def test_roles_authentication_and_conflicts(client: TestClient) -> None:
    assert (
        client.post("/v1/campaigns", json=payload(), headers={"Idempotency-Key": "x"}).status_code
        == 401
    )
    assert (
        client.post("/v1/campaigns", json=payload(), headers=headers(actor="viewer")).status_code
        == 403
    )
    client.post("/v1/campaigns", json=payload(), headers=headers())
    conflict = client.post("/v1/campaigns", json={**payload(), "seed": 3}, headers=headers())
    assert conflict.status_code == 409
    assert conflict.json()["errors"][0]["code"] == "conflict"


def test_invalid_inputs_and_missing_key_use_error_envelope(client: TestClient) -> None:
    response = client.post(
        "/v1/campaigns", json={**payload(), "mode": "physical"}, headers=headers()
    )
    assert response.status_code == 422
    assert response.json()["data"] is None
    assert response.json()["errors"]
    assert (
        client.post(
            "/v1/campaigns", json=payload(), headers={"Authorization": "Bearer local-scientist"}
        ).status_code
        == 422
    )


def test_authentication_is_disabled_by_default(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ATLAS_LOCAL_DEMO_AUTH")
    assert client.get("/v1/campaigns", headers=headers()).status_code == 503
    caps = client.get("/v1/system/capabilities").json()["data"]
    assert caps["physical_dispatch"] is False
    assert caps["auth_profile"] == "disabled"


def test_http_proposal_and_independent_review(client: TestClient) -> None:
    campaign = client.post("/v1/campaigns", json=payload(), headers=headers()).json()["data"]
    proposed = client.post(
        f"/v1/campaigns/{campaign['id']}/plan",
        json={"expected_version": 0},
        headers=headers("plan"),
    )
    assert proposed.status_code == 201
    batch = proposed.json()["data"]
    pending = client.get("/v1/approvals/pending", headers=headers(actor="reviewer"))
    assert pending.json()["data"][0]["id"] == batch["id"]
    url = f"/v1/campaigns/{campaign['id']}/batches/{batch['id']}/approve"
    body = {"expected_version": 0, "plan_hash": batch["plan_hash"]}
    assert client.post(url, json=body, headers=headers("approve")).status_code == 403
    approved = client.post(url, json=body, headers=headers("approve", actor="reviewer"))
    assert approved.status_code == 200
    assert approved.json()["data"]["status"] == "APPROVED"
