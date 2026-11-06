import io
import json
import time
from collections.abc import Iterator
from typing import Any
from unittest.mock import Mock

import jwt
import pytest
from atlas_api.auth import CognitoSettings, CognitoVerifier, authentication_profile, principal
from atlas_api.main import create_app
from atlas_campaigns.secrets import ConfigurationError
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient

SETTINGS = CognitoSettings(
    "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TestPool",
    "testclient",
    "atlas/access",
    "https://atlas.example.com",
)


@pytest.fixture(autouse=True)
def auth_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "ATLAS_RUNTIME_PROFILE",
        "ATLAS_LOCAL_DEMO_AUTH",
        "ATLAS_COGNITO_ISSUER",
        "ATLAS_COGNITO_CLIENT_ID",
        "ATLAS_COGNITO_REQUIRED_SCOPE",
        "ATLAS_COGNITO_API_AUDIENCE",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def token(key: rsa.RSAPrivateKey, **overrides: Any) -> str:
    now = int(time.time())
    claims = {
        "sub": "stable-person",
        "iss": SETTINGS.issuer,
        "client_id": SETTINGS.client_id,
        "aud": SETTINGS.audience,
        "token_use": "access",
        "iat": now,
        "exp": now + 300,
        "scope": SETTINGS.scope,
        "cognito:groups": ["atlas-scientists"],
    }
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "key1"})


@pytest.fixture
def verifier(key: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch) -> Iterator[CognitoVerifier]:
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    public.update(kid="key1", alg="RS256", use="sig")

    def fetch(request: Any, **kwargs: Any) -> io.BytesIO:
        assert request.full_url == SETTINGS.issuer + "/.well-known/jwks.json"
        return io.BytesIO(json.dumps({"keys": [public]}).encode())

    monkeypatch.setattr(
        "jwt.jwks_client.urllib.request.build_opener", lambda *args: Mock(open=fetch)
    )
    yield CognitoVerifier(SETTINGS)


def test_verified_identity_uses_subject_and_supports_multiple_roles(
    key: rsa.RSAPrivateKey, verifier: CognitoVerifier
) -> None:
    identity = verifier.verify(
        token(key, **{"cognito:groups": ["atlas-scientists", "atlas-reviewers"]})
    )
    assert identity.actor.startswith("cognito:") and len(identity.actor) == 72
    assert identity.has_role("scientist") and identity.has_role("reviewer")
    assert identity.role == "reviewer"
    assert verifier.verify(token(key, email="changed@example.com")).actor == identity.actor
    assert verifier.verify(token(key, sub="other-person")).actor != identity.actor


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://attacker.example.com"},
        {"client_id": "other-client"},
        {"token_use": "id"},
        {"aud": "wrong-resource"},
        {"exp": 1},
        {"exp": None},
        {"iat": int(time.time()) + 1000},
        {"nbf": int(time.time()) + 1000},
        {"sub": ""},
        {"sub": 123},
        {"exp": str(int(time.time()) + 1000)},
        {"cognito:groups": "atlas-reviewers"},
    ],
)
def test_invalid_claims_are_rejected(
    key: rsa.RSAPrivateKey, verifier: CognitoVerifier, overrides: dict[str, Any]
) -> None:
    with pytest.raises(HTTPException) as error:
        verifier.verify(token(key, **overrides))
    assert error.value.status_code == 401


@pytest.mark.parametrize(
    "overrides",
    [
        {"scope": "openid"},
        {"scope": "atlas/access-extra"},
        {"cognito:groups": ["admin"]},
    ],
)
def test_scope_and_role_denials(
    key: rsa.RSAPrivateKey, verifier: CognitoVerifier, overrides: dict[str, Any]
) -> None:
    with pytest.raises(HTTPException) as error:
        verifier.verify(token(key, **overrides))
    assert error.value.status_code == 403


def test_forged_signatures_and_algorithm_confusion(
    key: rsa.RSAPrivateKey, verifier: CognitoVerifier
) -> None:
    forged = token(rsa.generate_private_key(public_exponent=65537, key_size=2048))
    hmac = jwt.encode({"sub": "attacker"}, "x" * 64, algorithm="HS256", headers={"kid": "key1"})
    untrusted_jku = jwt.encode(
        {"sub": "attacker"},
        key,
        algorithm="RS256",
        headers={"kid": "key1", "jku": "https://attacker.example/jwks"},
    )
    for value in (forged, hmac, untrusted_jku, "local-reviewer", "not-a-jwt"):
        with pytest.raises(HTTPException) as error:
            verifier.verify(value)
        assert error.value.status_code == 401


def test_key_rotation_refreshes_jwks(
    key: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    public1 = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    key2 = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public2 = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key2.public_key()))
    public1.update(kid="key1", alg="RS256", use="sig")
    public2.update(kid="key2", alg="RS256", use="sig")
    keys = [public1]
    requests: list[str] = []

    def fetch(request: Any, **kwargs: Any) -> io.BytesIO:
        requests.append(request.full_url)
        return io.BytesIO(json.dumps({"keys": keys}).encode())

    monkeypatch.setattr(
        "jwt.jwks_client.urllib.request.build_opener", lambda *args: Mock(open=fetch)
    )
    clock = [time.monotonic()]
    monkeypatch.setattr("jwt.jwks_client.time.monotonic", lambda: clock[0])
    verifier = CognitoVerifier(SETTINGS)
    original = token(key)
    verifier.verify(original)
    verifier.verify(original)
    assert len(requests) == 1
    claims = jwt.decode(original, options={"verify_signature": False})
    rotated = jwt.encode(claims, key2, algorithm="RS256", headers={"kid": "key2"})
    keys[:] = [public2]
    with pytest.raises(HTTPException) as error:
        verifier.verify(rotated)
    assert error.value.status_code == 401
    clock[0] += 31
    verifier.verify(rotated)
    assert len(requests) == 2


def test_key_service_failure_is_unavailable(
    verifier: CognitoVerifier, monkeypatch: pytest.MonkeyPatch, key: rsa.RSAPrivateKey
) -> None:
    monkeypatch.setattr(
        verifier.keys,
        "get_signing_key_from_jwt",
        Mock(side_effect=jwt.PyJWKClientConnectionError("private internal detail")),
    )
    with pytest.raises(HTTPException) as error:
        verifier.verify(token(key))
    assert error.value.status_code == 503 and "private" not in str(error.value.detail)


def test_production_rejects_demo_and_missing_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATLAS_RUNTIME_PROFILE", "production")
    monkeypatch.setenv("ATLAS_LOCAL_DEMO_AUTH", "true")
    with pytest.raises(ConfigurationError, match="demonstration"):
        principal("Bearer local-reviewer")
    response = TestClient(create_app()).get(
        "/v1/campaigns", headers={"Authorization": "Bearer local-scientist"}
    )
    assert response.status_code == 503
    monkeypatch.delenv("ATLAS_LOCAL_DEMO_AUTH")
    with pytest.raises(ConfigurationError, match="Cognito"):
        authentication_profile()


def test_cognito_configuration_is_trusted_not_token_selected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATLAS_RUNTIME_PROFILE", "production")
    monkeypatch.setenv("ATLAS_COGNITO_ISSUER", SETTINGS.issuer)
    monkeypatch.setenv("ATLAS_COGNITO_CLIENT_ID", SETTINGS.client_id)
    monkeypatch.setenv("ATLAS_COGNITO_REQUIRED_SCOPE", SETTINGS.scope)
    assert authentication_profile() == "cognito"
    for issuer in (
        "http://cognito-idp.us-east-1.amazonaws.com/us-east-1_TestPool",
        "https://attacker.example.com/us-east-1_TestPool",
        SETTINGS.issuer + "?extra=1",
    ):
        monkeypatch.setenv("ATLAS_COGNITO_ISSUER", issuer)
        with pytest.raises(ConfigurationError):
            CognitoSettings.from_environment()
