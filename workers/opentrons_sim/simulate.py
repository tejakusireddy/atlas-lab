"""Container entry point for vendor simulation of an internally compiled protocol."""

import hashlib
import importlib.metadata
import json
from pathlib import Path

from opentrons import simulate

path = Path("/input/protocol.py")
with path.open() as protocol:
    runlog, _ = simulate.simulate(protocol, file_name=str(path))
print(
    json.dumps(
        {
            "status": "SIMULATED",
            "simulator": "opentrons",
            "simulator_version": importlib.metadata.version("opentrons"),
            "protocol_hash": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
            "commands": runlog,
        },
        default=str,
    )
)
