"""Reference milestone: real source, HTTP review, vendor simulation, and replay."""

import hashlib
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from atlas_api.main import create_app
from atlas_api.main import database as database_dependency
from atlas_api.register import register_snapshot
from atlas_campaigns import telemetry
from atlas_campaigns.analysis import analyze
from atlas_campaigns.database import Connection
from atlas_campaigns.execution import execute_next, reconcile, recover_expired
from atlas_campaigns.service import Conflict, NotFound
from atlas_domain.hashing import content_hash
from atlas_measurements.oracle import reveal
from atlas_science.records import Candidate
from atlas_science.splits import create_split
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from tests.support import crash_dispatch


@pytest.mark.parametrize(
    ("strategy", "predictor"),
    [
        ("random", "random_forest"),
        ("greedy", "random_forest"),
        ("diversity", "random_forest"),
        ("ensemble_ucb", "random_forest"),
        ("ensemble_ucb", "catboost"),
    ],
)
def test_reproducible_six_batch_reference(
    database: Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    strategy: str,
    predictor: str,
) -> None:
    spans = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(spans))
    monkeypatch.setattr(telemetry, "provider", provider)
    snapshot = Path(os.environ.get("ATLAS_REFERENCE_SNAPSHOT", "data/snapshots/doyle2018-v1"))
    assert snapshot.exists(), "Import the pinned Doyle snapshot before running this milestone"
    original_open = Path.open
    allow_oracle = False
    oracle_accesses = 0

    def guarded_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        nonlocal oracle_accesses
        if "oracle" in path.parts:
            assert allow_oracle, "Hidden outcome access outside the release worker"
            oracle_accesses += 1
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    snapshot_id = register_snapshot(database, snapshot)
    candidates = [
        Candidate.model_validate_json(line)
        for line in (snapshot / "candidates.jsonl").read_text().splitlines()
    ]
    split = create_split(candidates, seed=42)
    group = next(c.group_id for c in candidates if c.candidate_id == split.campaign_ids[0])
    assert not {c.candidate_id for c in candidates if c.group_id == group} & set(split.train_ids)
    monkeypatch.setenv("ATLAS_LOCAL_DEMO_AUTH", "true")
    app = create_app()

    def connection() -> Iterator[Connection]:
        yield database

    app.dependency_overrides[database_dependency] = connection
    scientist = {"Authorization": "Bearer local-scientist"}
    reviewer = {"Authorization": "Bearer local-reviewer"}
    trajectories: list[Any] = []
    with TestClient(app) as client:
        for repeat in range(2):

            def post(
                url: str,
                body: dict[str, Any],
                key: str,
                review: bool = False,
                expected: int = 200,
                repeat: int = repeat,
            ) -> dict[str, Any]:
                response = client.post(
                    url,
                    json=body,
                    headers={
                        **(reviewer if review else scientist),
                        "Idempotency-Key": f"{repeat}-{key}",
                    },
                )
                assert response.status_code == expected, response.text
                data: dict[str, Any] = response.json()["data"]
                return data

            campaign = post(
                "/v1/campaigns",
                {
                    "dataset_snapshot_id": snapshot_id,
                    "campaign_group_id": group,
                    "seed": 42,
                    "acquisition_strategy": strategy,
                    "predictor": predictor,
                },
                "create",
                expected=201,
            )
            cid = campaign["id"]
            previous_hash = None
            seen: set[str] = set()
            trajectory = []
            released_yields: list[float] = []
            for batch_number in range(1, 7):
                campaign = client.get(f"/v1/campaigns/{cid}", headers=scientist).json()["data"]
                command = {
                    "expected_version": campaign["version"],
                    "previous_snapshot_hash": previous_hash,
                }
                if batch_number > 1:
                    wrong = client.post(
                        f"/v1/campaigns/{cid}/plan",
                        json={**command, "previous_snapshot_hash": "sha256:" + "0" * 64},
                        headers={**scientist, "Idempotency-Key": f"{repeat}-wrong-{batch_number}"},
                    )
                    assert wrong.status_code == 409
                batch = post(
                    f"/v1/campaigns/{cid}/plan", command, f"plan-{batch_number}", expected=201
                )
                selected = batch["run_spec"]["candidate_ids"]
                assert len(selected) == 8 and not seen.intersection(selected)
                seen.update(selected)
                rid = batch["run_id"]
                with pytest.raises(NotFound):
                    reveal(database, UUID(rid), snapshot)
                unapproved = client.post(
                    f"/v1/runs/{rid}/simulate",
                    json={"expected_version": 0},
                    headers={**scientist, "Idempotency-Key": f"{repeat}-early-{batch_number}"},
                )
                assert unapproved.status_code == 404
                post(
                    f"/v1/campaigns/{cid}/batches/{batch['id']}/approve",
                    {"expected_version": 0, "plan_hash": batch["plan_hash"]},
                    f"approve-{batch_number}",
                    review=True,
                )
                with pytest.raises(Conflict):
                    reveal(database, UUID(rid), snapshot)
                post(
                    f"/v1/runs/{rid}/simulate",
                    {"expected_version": 0},
                    f"dispatch-{batch_number}",
                    expected=202,
                )
                completed: dict[str, Any] | None
                if (
                    strategy == "greedy"
                    and predictor == "random_forest"
                    and repeat == 0
                    and batch_number == 1
                ):
                    lost = crash_dispatch(database, tmp_path / "runs", "lost_ack")
                    assert lost.returncode == 137
                    database.execute(
                        "UPDATE experiment_runs SET lease_until=now()-interval '1 second' "
                        "WHERE id=%s",
                        (UUID(rid),),
                    )
                    assert recover_expired(database) == 1
                    completed = reconcile(
                        database,
                        UUID(rid),
                        5,
                        "local-reviewer",
                        "lost-ack-recovery",
                        UUID(rid),
                        "recovery",
                    )
                else:
                    completed = execute_next(database, tmp_path / "runs")
                assert completed is not None and completed["status"] == "SIMULATED"
                assert str(completed["id"]) == rid
                assert execute_next(database, tmp_path / "runs") is None
                allow_oracle = True
                try:
                    measurements = reveal(database, UUID(rid), snapshot)
                finally:
                    allow_oracle = False
                assert len(measurements) == 8
                assert all(
                    m["source_kind"] == "historical_observed" and m["qc_state"] == "PASSED"
                    for m in measurements
                )
                run = client.get(f"/v1/runs/{rid}", headers=scientist).json()["data"]
                premature = client.post(
                    f"/v1/campaigns/{cid}/plan",
                    json=command,
                    headers={**scientist, "Idempotency-Key": f"{repeat}-premature-{batch_number}"},
                )
                assert premature.status_code == 409
                if strategy == "greedy" and repeat == 0 and batch_number == 2:
                    import atlas_campaigns.analysis as analysis_module

                    def fail_training(*args: Any, **kwargs: Any) -> Any:
                        raise RuntimeError("PRIVATE_OUTCOME_SENTINEL")

                    with monkeypatch.context() as patch:
                        patch.setattr(analysis_module, "decide", fail_training)
                        with pytest.raises(RuntimeError, match="PRIVATE_OUTCOME_SENTINEL"):
                            analyze(
                                database,
                                UUID(rid),
                                run["version"],
                                "local-scientist",
                                "training-recovery",
                                UUID(rid),
                                "recovery",
                            )
                    pending = database.execute(
                        "SELECT status FROM experiment_runs WHERE id=%s", (UUID(rid),)
                    ).fetchone()
                    assert pending is not None and pending["status"] == "QC_COMPLETE"
                    assert (
                        database.execute(
                            "SELECT * FROM campaign_analyses WHERE run_id=%s", (UUID(rid),)
                        ).fetchone()
                        is None
                    )
                analysis = post(
                    f"/v1/runs/{rid}/analyze",
                    {"expected_version": run["version"]},
                    f"analyze-{batch_number}",
                )
                frozen = analysis["snapshot"]
                assert content_hash(frozen) == analysis["snapshot_hash"]
                assert frozen["batch_number"] == batch_number
                assert frozen["selected_candidate_ids"] == selected
                assert frozen["previous_snapshot_hash"] == previous_hash
                assert frozen["approved_work_order_hash"] == batch["plan_hash"]
                assert frozen["batch_qc_counts"] == {"PASSED": 8, "QUARANTINED": 0, "UNOBSERVED": 0}
                assert len(frozen["observations"]) == batch_number * 8
                batch_yields = [m["observed_yield_pct"] for m in measurements]
                released_yields.extend(batch_yields)
                assert frozen["batch_best_observed"]["observed_yield_pct"] == max(batch_yields)
                assert frozen["cumulative_best_observed"]["observed_yield_pct"] == max(
                    released_yields
                )
                assert set(frozen["released_measurement_ids"]) == {
                    str(m["id"]) for m in measurements
                }
                receipt = database.execute(
                    "SELECT * FROM execution_receipts WHERE run_id=%s", (UUID(rid),)
                ).fetchone()
                assert receipt is not None
                assert frozen["simulation_receipt_hash"] == content_hash(receipt["receipt"])
                duplicate = post(
                    f"/v1/runs/{rid}/analyze",
                    {"expected_version": run["version"]},
                    f"another-analysis-{batch_number}",
                )
                assert duplicate == analysis
                if strategy != "random":
                    decision = frozen["next_decision"]
                    assert content_hash(decision) == frozen["next_decision_hash"]
                    assert decision["training_candidate_ids"] == sorted(seen)
                    assert {m["candidate_id"] for m in decision["training_measurements"]} == seen
                    assert decision["external_training"] is None
                    if strategy != "diversity":
                        saved = database.execute(
                            "SELECT artifact FROM model_artifacts WHERE model_hash=%s",
                            (decision["model_hash"],),
                        ).fetchone()
                        assert saved is not None
                        assert (
                            "sha256:" + hashlib.sha256(saved["artifact"]).hexdigest()
                            == decision["model_hash"]
                        )
                if batch_number > 1 and strategy != "random":
                    assert batch["selection_context"]["selected_ids"] == selected
                    assert batch["selection_context"]["previous_snapshot_hash"] == previous_hash
                previous_hash = analysis["snapshot_hash"]
                trajectory.append(
                    {
                        "selected": selected,
                        "outcomes": sorted(
                            (m["candidate_id"], m["observed_yield_pct"]) for m in measurements
                        ),
                        "best": frozen["cumulative_best_observed"]["observed_yield_pct"],
                        "acquisition_version": frozen["acquisition_version"],
                    }
                )
            final = client.get(f"/v1/campaigns/{cid}", headers=scientist).json()["data"]
            assert final["status"] == "COMPLETE" and final["budget_used"] == len(seen) == 48
            exhausted = client.post(
                f"/v1/campaigns/{cid}/plan",
                json={
                    "expected_version": final["version"],
                    "previous_snapshot_hash": previous_hash,
                },
                headers={**scientist, "Idempotency-Key": f"{repeat}-exhausted"},
            )
            assert exhausted.status_code == 409
            trajectories.append(trajectory)
    assert oracle_accesses == 12
    assert trajectories[0] == trajectories[1]
    assert content_hash({"trajectory": trajectories[0]}) == content_hash(
        {"trajectory": trajectories[1]}
    )

    finished = spans.get_finished_spans()
    roots = [s for s in finished if s.name == "campaign.create"]
    root_ids = {s.context.trace_id for s in roots if s.context is not None}
    assert len(root_ids) == 2
    for name in (
        "batch.propose",
        "batch.decision",
        "lab.dispatch",
        "lab.simulate",
        "oracle.reveal",
        "campaign.analyze",
    ):
        relevant = [
            s
            for s in finished
            if s.name == name and s.attributes and s.attributes.get("atlas.campaign_id")
        ]
        assert relevant and all(s.context and s.context.trace_id in root_ids for s in relevant)
    if strategy != "random":
        assert any(
            s.name == "model.update" and s.context and s.context.trace_id in root_ids
            for s in finished
        )
    assert "PRIVATE_OUTCOME_SENTINEL" not in "".join(s.to_json() for s in finished)
    provider.shutdown()
