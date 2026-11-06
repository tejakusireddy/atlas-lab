"""Bounded, reloadable credentials supplied through deployment-owned files."""

import os
from pathlib import Path


class ConfigurationError(ValueError):
    """Deployment configuration is absent or inconsistent; never includes secret values."""


def production_profile() -> bool:
    profile = os.environ.get("ATLAS_RUNTIME_PROFILE", "local")
    if profile not in {"local", "production"}:
        raise ConfigurationError("ATLAS_RUNTIME_PROFILE must be local or production")
    return profile == "production"


def read_secret_file(filename: str) -> str:
    """Read on each use so an atomic file replacement rotates future connections."""
    try:
        with Path(filename).open("rb") as source:
            value = source.read(4097)
        if len(value) > 4096:
            raise ConfigurationError("Secret file exceeds the supported size")
        secret = value.decode("utf-8").rstrip("\r\n")
        if not secret or "\x00" in secret or "\n" in secret or "\r" in secret:
            raise ConfigurationError("Secret file must contain one nonempty line")
        return secret
    except (OSError, UnicodeError):
        raise ConfigurationError("Secret file is unavailable or invalid") from None
