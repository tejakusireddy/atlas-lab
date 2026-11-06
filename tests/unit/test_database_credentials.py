import os
from pathlib import Path
from unittest.mock import Mock

import pytest
from atlas_campaigns.database import LOCAL_DSN, connect
from atlas_campaigns.secrets import ConfigurationError, read_secret_file


@pytest.fixture(autouse=True)
def clean_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ATLAS_DATABASE_URL", "ATLAS_DATABASE_PASSWORD_FILE", "ATLAS_RUNTIME_PROFILE"):
        monkeypatch.delenv(name, raising=False)


def test_local_default_remains_explicitly_local(monkeypatch: pytest.MonkeyPatch) -> None:
    driver = Mock()
    monkeypatch.setattr("atlas_campaigns.database.psycopg.connect", driver)
    connect()
    assert driver.call_args.kwargs["password"] == "atlas-local-only"


def test_production_requires_explicit_secret_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATLAS_RUNTIME_PROFILE", "production")
    with pytest.raises(ConfigurationError, match="ATLAS_DATABASE_URL"):
        connect()
    monkeypatch.setenv("ATLAS_DATABASE_URL", LOCAL_DSN)
    with pytest.raises(ConfigurationError, match="PASSWORD_FILE"):
        connect()
    monkeypatch.setenv("ATLAS_DATABASE_PASSWORD_FILE", "/absent")
    with pytest.raises(ConfigurationError, match="one database credential source"):
        connect()


def test_rotation_reloads_without_putting_secret_in_dsn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    filename = tmp_path / "password"
    filename.write_text("first-secret\n")
    monkeypatch.setenv("ATLAS_RUNTIME_PROFILE", "production")
    monkeypatch.setenv("ATLAS_DATABASE_URL", "postgresql://service@database/atlas")
    monkeypatch.setenv("ATLAS_DATABASE_PASSWORD_FILE", str(filename))
    driver = Mock()
    monkeypatch.setattr("atlas_campaigns.database.psycopg.connect", driver)
    connect()
    assert driver.call_args.kwargs["password"] == "first-secret"
    replacement = tmp_path / "replacement"
    replacement.write_text("rotated-secret")
    replacement.replace(filename)
    connect()
    assert driver.call_args.kwargs["password"] == "rotated-secret"
    filename.unlink()
    with pytest.raises(ConfigurationError, match="unavailable"):
        connect()
    assert driver.call_count == 2


@pytest.mark.parametrize("content", [b"", b"x" * 4097, b"a\nb", b"a\x00b", b"\xff"])
def test_bad_secret_never_exposes_contents(tmp_path: Path, content: bytes) -> None:
    filename = tmp_path / "password"
    filename.write_bytes(content)
    with pytest.raises(ConfigurationError):
        read_secret_file(str(filename))


def test_invalid_profile_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATLAS_RUNTIME_PROFILE", "prodution")
    with pytest.raises(ConfigurationError, match="PROFILE"):
        connect()


def test_secret_rejects_pipe_without_waiting_for_a_writer(tmp_path: Path) -> None:
    filename = tmp_path / "password-pipe"
    os.mkfifo(filename)
    with pytest.raises(ConfigurationError, match="regular file"):
        read_secret_file(str(filename))
