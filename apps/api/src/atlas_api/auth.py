"""Cognito access-token verification and explicit local demonstration identities."""

import hashlib
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import urlsplit

import jwt
from atlas_campaigns.secrets import ConfigurationError, production_profile
from fastapi import Header, HTTPException

Role = Literal["scientist", "reviewer", "viewer"]
GROUP_ROLES: dict[str, Role] = {
    "atlas-scientists": "scientist",
    "atlas-reviewers": "reviewer",
    "atlas-viewers": "viewer",
}


@dataclass(frozen=True)
class Principal:
    actor: str
    roles: frozenset[Role]

    @property
    def role(self) -> Role:
        """Reviewer visibility is independent of permission to create scientific work."""
        return (
            "reviewer"
            if "reviewer" in self.roles
            else ("scientist" if "scientist" in self.roles else "viewer")
        )

    def has_role(self, role: Role) -> bool:
        return role in self.roles


LOCAL_IDENTITIES = {
    f"local-{role}": Principal(f"local-{role}", frozenset([role]))
    for role in ("scientist", "reviewer", "viewer")
}


@dataclass(frozen=True)
class CognitoSettings:
    issuer: str
    client_id: str
    scope: str
    audience: str | None

    @classmethod
    def from_environment(cls) -> "CognitoSettings":
        issuer = os.environ.get("ATLAS_COGNITO_ISSUER", "")
        client = os.environ.get("ATLAS_COGNITO_CLIENT_ID", "")
        scope = os.environ.get("ATLAS_COGNITO_REQUIRED_SCOPE", "")
        audience = os.environ.get("ATLAS_COGNITO_API_AUDIENCE")
        url = urlsplit(issuer)
        host = re.fullmatch(
            r"cognito-idp\.([a-z]{2}(?:-[a-z]+)+-\d)\.amazonaws\.com(\.cn)?", url.netloc
        )
        pool = re.fullmatch(r"/([a-z]{2}(?:-[a-z]+)+-\d)_[A-Za-z0-9]+", url.path)
        if (
            url.scheme != "https"
            or not host
            or not pool
            or host[1] != pool[1]
            or url.query
            or url.fragment
            or not re.fullmatch(r"[A-Za-z0-9]{1,128}", client)
            or not re.fullmatch(r"[^\s/]+/[^\s/]+", scope)
        ):
            raise ConfigurationError(
                "Configure a Cognito issuer, app client and API-specific scope"
            )
        if audience is not None and not audience:
            raise ConfigurationError("Cognito API audience cannot be empty")
        return cls(issuer, client, scope, audience)


def authentication_profile() -> str:
    production = production_profile()
    demo = os.environ.get("ATLAS_LOCAL_DEMO_AUTH") == "true"
    if production and demo:
        raise ConfigurationError("Production cannot enable demonstration authentication")
    if production or os.environ.get("ATLAS_COGNITO_ISSUER"):
        CognitoSettings.from_environment()
        return "cognito"
    return "local_demo" if demo else "disabled"


class CognitoVerifier:
    def __init__(self, settings: CognitoSettings) -> None:
        self.settings = settings
        self.keys = jwt.PyJWKClient(
            settings.issuer + "/.well-known/jwks.json",
            cache_keys=False,
            cache_jwk_set=True,
            lifespan=300,
            timeout=3,
            cooldown_duration=30,
        )

    def verify(self, token: str) -> Principal:
        try:
            header = jwt.get_unverified_header(token)
            if (
                header.get("alg") != "RS256"
                or not isinstance(header.get("kid"), str)
                or not 1 <= len(header["kid"]) <= 256
                or "jku" in header
                or "x5u" in header
            ):
                raise jwt.InvalidTokenError("Unsupported signing header")
            key = self.keys.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                issuer=self.settings.issuer,
                audience=self.settings.audience,
                options={
                    "require": ["exp", "iat", "sub", "iss", "client_id", "token_use"],
                    "verify_aud": self.settings.audience is not None,
                },
            )
            if (
                claims["token_use"] != "access"
                or claims["client_id"] != self.settings.client_id
                or type(claims["iat"]) is not int
                or type(claims["exp"]) is not int
                or not 0 < claims["exp"] - claims["iat"] <= 86400
                or not isinstance(claims["sub"], str)
                or not 1 <= len(claims["sub"]) <= 200
            ):
                raise jwt.InvalidTokenError("Invalid access-token claims")
            scopes = claims.get("scope", "")
            if not isinstance(scopes, str) or self.settings.scope not in scopes.split():
                raise HTTPException(403, "Required API scope is absent")
            groups = claims.get("cognito:groups", [])
            if not isinstance(groups, list) or not all(isinstance(group, str) for group in groups):
                raise jwt.InvalidTokenError("Invalid group claims")
            roles = frozenset(GROUP_ROLES[group] for group in groups if group in GROUP_ROLES)
            if not roles:
                raise HTTPException(403, "An ATLAS role is required")
            actor = (
                "cognito:"
                + hashlib.sha256(
                    (self.settings.issuer + "\x00" + claims["sub"]).encode()
                ).hexdigest()
            )
            return Principal(actor, roles)
        except jwt.PyJWKClientConnectionError:
            raise HTTPException(503, "Identity signing keys are unavailable") from None
        except (jwt.PyJWTError, ValueError, TypeError):
            raise unauthorized() from None


@lru_cache(maxsize=4)
def verifier(settings: CognitoSettings) -> CognitoVerifier:
    return CognitoVerifier(settings)


def unauthorized() -> HTTPException:
    return HTTPException(
        401, "Valid bearer credentials are required", headers={"WWW-Authenticate": "Bearer"}
    )


def principal(authorization: Annotated[str | None, Header()] = None) -> Principal:
    profile = authentication_profile()
    if profile == "disabled":
        raise HTTPException(503, "Authentication is not configured")
    if not authorization or not authorization.startswith("Bearer ") or len(authorization) > 16384:
        raise unauthorized()
    token = authorization[7:]
    if profile == "local_demo":
        identity = LOCAL_IDENTITIES.get(token)
        if identity is None:
            raise unauthorized()
        return identity
    return verifier(CognitoSettings.from_environment()).verify(token)
