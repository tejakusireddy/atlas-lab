import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from atlas_campaigns.broker import BrokerConfig
from atlas_campaigns.secrets import ConfigurationError

IMAGE = "sha256:" + "a" * 64


def test_broker_requires_pinned_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "ATLAS_BROKER_ARTIFACT_ROOT",
        "ATLAS_BROKER_DOCKER_SOCKET",
        "ATLAS_SIMULATOR_IMAGE_ID",
        "ATLAS_BROKER_DAEMON_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ConfigurationError):
        BrokerConfig.from_environment()
    monkeypatch.setenv("ATLAS_BROKER_ARTIFACT_ROOT", "/var/lib/atlas-dispatch")
    monkeypatch.setenv("ATLAS_BROKER_DOCKER_SOCKET", "/run/atlas-dispatch/docker.sock")
    monkeypatch.setenv("ATLAS_BROKER_DAEMON_ID", "dedicated-daemon-1234")
    monkeypatch.setenv("ATLAS_SIMULATOR_IMAGE_ID", "atlas-opentrons-sim:latest")
    with pytest.raises(ConfigurationError):
        BrokerConfig.from_environment()
    monkeypatch.setenv("ATLAS_SIMULATOR_IMAGE_ID", IMAGE)
    assert BrokerConfig.from_environment().docker_host == "unix:///run/atlas-dispatch/docker.sock"


@pytest.mark.parametrize(
    "info",
    [
        {"ID": "wrong-daemon", "SecurityOptions": ["name=rootless"]},
        {"ID": "dedicated-daemon-1234", "SecurityOptions": []},
    ],
)
def test_broker_rejects_shared_or_rootful_engine(
    info: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = Mock(return_value=json.dumps(info))
    monkeypatch.setattr("atlas_campaigns.broker.subprocess.check_output", engine)
    config = BrokerConfig(
        Path("/private-artifacts"), Path("/private-socket"), IMAGE, "dedicated-daemon-1234"
    )
    with pytest.raises(ConfigurationError, match="dedicated rootless"):
        config.inspect_engine()
    assert engine.call_count == 1
    assert engine.call_args.args[0][:3] == ["docker", "--host", "unix:///private-socket"]


def test_broker_requires_exact_image_and_detects_occupied_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = BrokerConfig(
        Path("/private-artifacts"), Path("/private-socket"), IMAGE, "dedicated-daemon-1234"
    )
    info = json.dumps({"ID": config.daemon_id, "SecurityOptions": ["name=rootless"]})
    monkeypatch.setattr(
        "atlas_campaigns.broker.subprocess.check_output",
        Mock(side_effect=[info, "sha256:" + "b" * 64]),
    )
    with pytest.raises(ConfigurationError, match="immutable"):
        config.inspect_engine()
    monkeypatch.setattr("atlas_campaigns.broker.subprocess.check_output", Mock(return_value="busy"))
    assert not config.slot_available()


def test_broker_refuses_other_operating_systems_and_service_users(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = BrokerConfig(tmp_path, tmp_path / "socket", IMAGE, "dedicated-daemon-1234")
    monkeypatch.setattr("atlas_campaigns.broker.os.geteuid", lambda: 0)
    with pytest.raises(ConfigurationError, match="UID 10005"):
        config.validate_filesystem()
