"""Register verified, outcome-free dataset metadata for local campaigns."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from atlas_campaigns.database import connect
from atlas_campaigns.service import Conflict
from atlas_science.records import Candidate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    args = parser.parse_args()
    snapshot: Path = args.snapshot
    manifest_bytes = (snapshot / "source_manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    candidate_bytes = (snapshot / "candidates.jsonl").read_bytes()
    if (
        hashlib.sha256(candidate_bytes).hexdigest()
        != manifest["artifact_hashes"]["candidates.jsonl"]
    ):
        raise ValueError("Candidate artifact checksum mismatch")
    quality_bytes = (snapshot / "quality_report.json").read_bytes()
    if (
        hashlib.sha256(quality_bytes).hexdigest()
        != manifest["artifact_hashes"]["quality_report.json"]
    ):
        raise ValueError("Quality report checksum mismatch")
    candidates = [Candidate.model_validate_json(line) for line in candidate_bytes.splitlines()]
    counts = Counter(candidate.group_id for candidate in candidates)
    quality = json.loads(quality_bytes)
    if quality["qc_counts"] != {"PASSED": len(candidates)}:
        raise ValueError(
            "Registration currently requires every retained candidate to pass source QC"
        )
    if len({c.candidate_id for c in candidates}) != len(candidates):
        raise ValueError("Duplicate candidate IDs")
    if len({c.reaction_key for c in candidates}) != len(candidates):
        raise ValueError("Duplicate reaction identities")
    if any(c.source_file_sha256 != manifest["source_file_sha256"] for c in candidates):
        raise ValueError("Source provenance mismatch")
    eligible = {group: count for group, count in counts.items() if count >= 48}
    if not eligible or eligible != quality["eligible_groups"]:
        raise ValueError("Candidate eligibility differs from quality report")
    digest = "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()
    snapshot_id = f"{manifest['source']}:{digest}"
    with connect() as connection, connection.transaction():
        connection.execute("SELECT pg_advisory_xact_lock(737164921)")
        previous = connection.execute(
            "SELECT manifest_hash FROM dataset_snapshots WHERE id=%s", (snapshot_id,)
        ).fetchone()
        if previous:
            if previous["manifest_hash"] != digest:
                raise Conflict("Snapshot already registered with a different manifest")
        else:
            connection.execute(
                "INSERT INTO dataset_snapshots(id,manifest_hash) VALUES (%s,%s)",
                (snapshot_id, digest),
            )
            for group_id, count in eligible.items():
                connection.execute(
                    "INSERT INTO dataset_groups VALUES (%s,%s,%s)", (snapshot_id, group_id, count)
                )
    print(json.dumps({"snapshot_id": snapshot_id, "eligible_groups": len(eligible)}, indent=2))


if __name__ == "__main__":
    main()
