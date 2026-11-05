"""Probe actual Linux mount/UID boundaries using the application runtime image."""

import json
import subprocess
from pathlib import Path
from uuid import uuid4


def docker(*args: str) -> str:
    return subprocess.check_output(["docker", *args], text=True, stderr=subprocess.STDOUT)


def test_only_release_uid_can_read_private_outcomes(tmp_path: Path) -> None:
    volume = "atlas-isolation-test-" + uuid4().hex
    docker("volume", "create", volume)
    try:
        docker(
            "run",
            "--rm",
            "--network=none",
            "--user=0",
            "-v",
            volume + ":/private-snapshot",
            "atlas-runtime:local",
            "python",
            "-c",
            "import os,pathlib; p=pathlib.Path('/private-snapshot/observations.jsonl'); "
            "p.write_text('private-test-sentinel'); os.chown(p,10002,10002); p.chmod(0o600); "
            "os.chown(p.parent,10002,10002); p.parent.chmod(0o700)",
        )
        probe = (
            "from pathlib import Path; "
            "print(Path('/private-snapshot/observations.jsonl').read_text())"
        )
        base = [
            "run",
            "--rm",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
        ]
        assert "private-test-sentinel" in docker(
            *base,
            "--user=10002:10002",
            "-v",
            volume + ":/private-snapshot:ro",
            "atlas-runtime:local",
            "python",
            "-c",
            probe,
        )
        for uid in (10001, 10003, 10004):
            for mount in ([], ["-v", volume + ":/private-snapshot:ro"]):
                result = subprocess.run(
                    [
                        "docker",
                        *base,
                        f"--user={uid}:{uid}",
                        *mount,
                        "atlas-runtime:local",
                        "python",
                        "-c",
                        probe,
                    ],
                    capture_output=True,
                    text=True,
                )
                assert result.returncode != 0
                assert "private-test-sentinel" not in result.stdout
                assert (
                    "PermissionError" in result.stderr
                    if mount
                    else "FileNotFoundError" in result.stderr
                )
        config = json.loads(
            docker(
                "compose",
                "-f",
                "infra/compose/compose.yaml",
                "-f",
                "infra/compose/isolated.yaml",
                "--profile",
                "workers",
                "config",
                "--format",
                "json",
            )
        )
        for name in ("api", "planner", "trainer"):
            service = config["services"][name]
            assert not service.get("volumes")
            assert service["read_only"] and service["cap_drop"] == ["ALL"]
        mounts = config["services"]["release"]["volumes"]
        assert len(mounts) == 1 and mounts[0]["read_only"]
    finally:
        docker("volume", "rm", volume)
