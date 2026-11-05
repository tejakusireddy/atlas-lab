"""Container entry point retaining a durable receipt before returning to the caller."""

import hashlib
import importlib.metadata
import json
from pathlib import Path

from opentrons import simulate

path = Path("/input/protocol.py")
spec = json.loads(Path("/input/run_spec.json").read_text())
receipt = {
    "run_id": spec["run_id"],
    "status": "EXECUTION_FAILED",
    "simulator": "opentrons",
    "simulator_version": importlib.metadata.version("opentrons"),
    "protocol_hash": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
}
try:
    with path.open() as protocol:
        runlog, _ = simulate.simulate(protocol, file_name=str(path))
    receipt.update(status="SIMULATED", commands=runlog)
except Exception as error:
    receipt["error_type"] = type(error).__name__
    raise
finally:
    encoded = json.dumps(receipt, default=str)
    temporary = Path("/output/receipt.tmp")
    temporary.write_text(encoded + "\n")
    temporary.replace("/output/receipt.json")
    print(encoded)
