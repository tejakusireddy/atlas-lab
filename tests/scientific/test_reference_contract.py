"""Scientific changes require an explicit reference revision, never silent regeneration."""

import hashlib
import json
from pathlib import Path

from atlas_science.decisions import VERSION


def test_locked_scientific_reference() -> None:
    reference = json.loads(Path("contracts/scientific_reference.v1.json").read_text())
    assert reference["name"] == "scientific-reference-v1"
    assert VERSION == "released-acquisition-v1"
    assert reference["budget"] == 48 and reference["batch_size"] == 8
    assert hashlib.sha256(Path("uv.lock").read_bytes()).hexdigest() == reference["lock_sha256"]
    for filename, expected in reference["scientific_code_sha256"].items():
        assert hashlib.sha256(Path(filename).read_bytes()).hexdigest() == expected, filename
    assert len(reference["expected_trajectory_hashes"]) == 5
