import io
import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import Mock

import pytest
from atlas_api.auth import verifier
from atlas_api.main import create_app
from atlas_api.main import database as database_dependency
from atlas_campaigns.database import Connection
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm

from tests.unit.test_cognito_auth import SETTINGS, token

pytestmark = pytest.mark.integration


def test_signed_cognito_tokens_preserve_ownership_and_independent_review(
    database: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATLAS_RUNTIME_PROFILE", "production")
    monkeypatch.delenv("ATLAS_LOCAL_DEMO_AUTH", raising=False)
    monkeypatch.setenv("ATLAS_COGNITO_ISSUER", SETTINGS.issuer)
    monkeypatch.setenv("ATLAS_COGNITO_CLIENT_ID", SETTINGS.client_id)
    monkeypatch.setenv("ATLAS_COGNITO_REQUIRED_SCOPE", SETTINGS.scope)
    monkeypatch.setenv("ATLAS_COGNITO_API_AUDIENCE", str(SETTINGS.audience))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    public.update(kid="key1", alg="RS256", use="sig")

    def fetch(*args: Any, **kwargs: Any) -> io.BytesIO:
        return io.BytesIO(json.dumps({"keys": [public]}).encode())

    monkeypatch.setattr(
        "jwt.jwks_client.urllib.request.build_opener", lambda *args: Mock(open=fetch)
    )
    verifier.cache_clear()
    app = create_app()

    def connection() -> Iterator[Connection]:
        yield database

    app.dependency_overrides[database_dependency] = connection
    with TestClient(app) as client:
        owner = {
            "Authorization": "Bearer "
            + token(key, **{"cognito:groups": ["atlas-scientists", "atlas-reviewers"]}),
            "Idempotency-Key": "create",
        }
        reviewer = {
            "Authorization": "Bearer "
            + token(key, sub="independent-reviewer", **{"cognito:groups": ["atlas-reviewers"]}),
            "Idempotency-Key": "review",
        }
        viewer = {
            "Authorization": "Bearer "
            + token(key, sub="other-viewer", **{"cognito:groups": ["atlas-viewers"]}),
            "Idempotency-Key": "view",
        }
        body = {"dataset_snapshot_id": "synthetic-snapshot", "campaign_group_id": "synthetic-group"}
        assert client.post("/v1/campaigns", json=body, headers=viewer).status_code == 403
        result = client.post("/v1/campaigns", json=body, headers=owner)
        assert result.status_code == 201
        campaign = result.json()["data"]["id"]
        assert client.get(f"/v1/campaigns/{campaign}", headers=viewer).status_code == 404
        batch = client.post(
            f"/v1/campaigns/{campaign}/plan",
            json={"expected_version": 0},
            headers={**owner, "Idempotency-Key": "plan"},
        ).json()["data"]
        url = f"/v1/campaigns/{campaign}/batches/{batch['id']}/approve"
        approval = {"expected_version": 0, "plan_hash": batch["plan_hash"]}
        assert client.post(url, json=approval, headers=owner).status_code == 403
        assert client.post(url, json=approval, headers=viewer).status_code == 403
        assert client.post(url, json=approval, headers=reviewer).status_code == 200
        assert (
            client.get(
                "/v1/campaigns", headers={"Authorization": "Bearer local-scientist"}
            ).status_code
            == 401
        )
        # A privileged migration connection cannot qualify as a production API runtime role.
        assert client.get("/health/ready").status_code == 503
    verifier.cache_clear()
