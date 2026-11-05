"""Run only trusted compiled work orders in a credential-free vendor container."""

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from atlas_instrument_gateway.compiler import compile_protocol
from atlas_instrument_gateway.spec import RunPlan

IMAGE = "atlas-opentrons-sim:10.1.0"


def simulate_plan(plan: RunPlan, output: Path, timeout: float = 120) -> dict[str, Any]:
    artifact = compile_protocol(plan)
    if output.exists():
        raise FileExistsError("Refusing to overwrite an existing simulation attempt")
    image_id = subprocess.check_output(
        ["docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"], text=True, timeout=15
    ).strip()
    output.mkdir(parents=True)
    (output / "protocol.py").write_text(artifact.source)
    (output / "run_spec.json").write_text(plan.model_dump_json(indent=2) + "\n")
    receipt_directory = output / "receipt"
    receipt_directory.mkdir()
    receipt_directory.chmod(0o777)  # Writable only output mount for the non-root container UID.
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        f"atlas-sim-{plan.run_id}",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--memory=1g",
        "--cpus=1",
        "--pids-limit=128",
        "--tmpfs",
        "/tmp:rw,nosuid,size=128m",
        "--mount",
        f"type=bind,source={output.resolve()},target=/input,readonly",
        "--mount",
        f"type=bind,source={receipt_directory.resolve()},target=/output",
        image_id,
    ]
    manifest: dict[str, Any] = {
        "run_id": str(plan.run_id),
        "plan_hash": artifact.plan_hash,
        "protocol_hash": artifact.protocol_hash,
        "image_id": image_id,
        "execution_mode": "simulation",
        "status": "EXECUTION_UNKNOWN",
    }
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=False
        )
        (output / "stdout.log").write_text(result.stdout)
        (output / "stderr.log").write_text(result.stderr)
        if result.returncode != 0:
            manifest.update(status="EXECUTION_FAILED", exit_code=result.returncode)
        else:
            receipt = json.loads(result.stdout.strip().splitlines()[-1])
            if (
                receipt.get("run_id") != str(plan.run_id)
                or receipt["protocol_hash"] != artifact.protocol_hash
                or receipt["simulator_version"] != "10.1.0"
                or receipt["status"] != "SIMULATED"
            ):
                raise ValueError("Vendor receipt does not match the compiled protocol")
            durable = json.loads((receipt_directory / "receipt.json").read_text())
            if durable != receipt:
                raise ValueError("Durable receipt differs from vendor output")
            manifest.update(status="SIMULATED", receipt=receipt)
    except subprocess.TimeoutExpired:
        # CLI timeout does not prove container completion; do not redispatch.
        manifest["reason"] = "Container outcome unknown after client timeout; reconcile manually"
    finally:
        (output / "simulation_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = simulate_plan(RunPlan.model_validate_json(args.spec.read_bytes()), args.output)
    print(
        json.dumps(
            {"status": result["status"], "manifest": str(args.output / "simulation_manifest.json")}
        )
    )
    if result["status"] != "SIMULATED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
