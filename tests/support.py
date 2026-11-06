"""Subprocess fault probes shared by recovery and reference integration tests."""

import os
import subprocess
import sys
from pathlib import Path

from atlas_campaigns.database import Connection

WORKER = """
import os
from pathlib import Path
from psycopg import sql
from atlas_campaigns.database import connect
from atlas_campaigns.execution import claim_next
from atlas_instrument_gateway.simulator import simulate_plan
from atlas_instrument_gateway.spec import RunPlan
with connect(os.environ["ATLAS_TEST_DATABASE_URL"]) as db:
    db.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(os.environ["TEST_SCHEMA"])))
    run = claim_next(db, Path(os.environ["TEST_ARTIFACTS"]))
    assert run is not None
    if os.environ["TEST_PHASE"] != "before_simulation":
        result = simulate_plan(
            RunPlan.model_validate(run["run_spec"]), Path(run["artifact_directory"]))
        assert result["status"] == "SIMULATED"
    if os.environ["TEST_PHASE"] == "database_disconnect":
        db.close()
        db.execute("SELECT 1")
    os._exit(137)
"""


def crash_dispatch(
    database: Connection, directory: Path, phase: str
) -> subprocess.CompletedProcess[str]:
    schema = database.execute("SELECT current_schema() AS name").fetchone()
    assert schema is not None
    return subprocess.run(
        [sys.executable, "-c", WORKER],
        env=os.environ
        | {"TEST_SCHEMA": schema["name"], "TEST_ARTIFACTS": str(directory), "TEST_PHASE": phase},
        capture_output=True,
        text=True,
        timeout=150,
    )
