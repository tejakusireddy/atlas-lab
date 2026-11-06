"""Single-slot dispatch broker for a dedicated Linux/rootless Docker worker.

The authenticated database outbox is the only work input. Deployment configuration
owns the daemon, immutable image ID and artifact root; clients cannot supply them.
"""

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from atlas_instrument_gateway.simulator import simulate_plan

from atlas_campaigns.database import Connection, connect
from atlas_campaigns.execution import execute_next, reconcile, recover_expired
from atlas_campaigns.secrets import ConfigurationError, production_profile
from atlas_campaigns.service import Conflict

BROKER_UID = 10005
LOCK_ID = 737164921
SLOT = "atlas-dispatch-slot"


@dataclass(frozen=True)
class BrokerConfig:
    root: Path
    socket: Path
    image_id: str
    daemon_id: str

    @classmethod
    def from_environment(cls) -> "BrokerConfig":
        root = Path(os.environ.get("ATLAS_BROKER_ARTIFACT_ROOT", ""))
        socket = Path(os.environ.get("ATLAS_BROKER_DOCKER_SOCKET", ""))
        image = os.environ.get("ATLAS_SIMULATOR_IMAGE_ID", "")
        daemon = os.environ.get("ATLAS_BROKER_DAEMON_ID", "")
        if (
            not root.is_absolute()
            or not socket.is_absolute()
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", image)
            or not re.fullmatch(r"[A-Za-z0-9:-]{8,200}", daemon)
        ):
            raise ConfigurationError("Configure absolute broker paths and pinned image/daemon IDs")
        return cls(root, socket, image, daemon)

    @property
    def docker_host(self) -> str:
        return "unix://" + str(self.socket)

    def validate_filesystem(self) -> None:
        if sys.platform != "linux" or os.geteuid() != BROKER_UID:
            raise ConfigurationError("Broker requires the dedicated Linux service UID 10005")
        for path, expected in ((self.root, stat.S_ISDIR), (self.socket, stat.S_ISSOCK)):
            metadata = path.lstat()
            if (
                path.resolve() != path
                or not expected(metadata.st_mode)
                or metadata.st_uid != BROKER_UID
                or stat.S_IMODE(metadata.st_mode) & 0o077
            ):
                raise ConfigurationError(
                    "Broker paths must be private and owned by its service UID"
                )

    def inspect_engine(self) -> None:
        info = json.loads(
            subprocess.check_output(
                ["docker", "--host", self.docker_host, "info", "--format", "{{json .}}"],
                text=True,
                timeout=15,
            )
        )
        if info.get("ID") != self.daemon_id or "name=rootless" not in info.get(
            "SecurityOptions", []
        ):
            raise ConfigurationError(
                "Dispatch requires the pinned, dedicated rootless Docker daemon"
            )
        image = subprocess.check_output(
            [
                "docker",
                "--host",
                self.docker_host,
                "image",
                "inspect",
                self.image_id,
                "--format",
                "{{.Id}}",
            ],
            text=True,
            timeout=15,
        ).strip()
        if image != self.image_id:
            raise ConfigurationError("Simulator image does not match the configured immutable ID")

    def slot_available(self) -> bool:
        occupied = subprocess.check_output(
            [
                "docker",
                "--host",
                self.docker_host,
                "ps",
                "-a",
                "--filter",
                f"name=^/{SLOT}$",
                "--format",
                "{{.ID}}",
            ],
            text=True,
            timeout=15,
        ).strip()
        return not occupied


def validate_dispatch_role(connection: Connection) -> None:
    role = connection.execute("""SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,
        rolbypassrls FROM pg_roles WHERE rolname=current_user""").fetchone()
    grants = connection.execute("""SELECT
        has_table_privilege(current_user,'measurements','INSERT') AS measurements,
        has_table_privilege(current_user,'approvals','INSERT') AS approvals,
        has_schema_privilege(current_user,current_schema(),'CREATE') AS ddl,
        has_column_privilege(current_user,'outbox_events','published_at','UPDATE')
        AS dispatch""").fetchone()
    if (
        role is None
        or any(role.values())
        or grants is None
        or not grants["dispatch"]
        or any(grants[key] for key in ("measurements", "approvals", "ddl"))
    ):
        raise ConfigurationError("Broker requires the restricted dispatch database role")


def process_reconciliation(connection: Connection, root: Path) -> bool:
    with connection.transaction():
        request = connection.execute("""SELECT q.* FROM reconciliation_requests q
            LEFT JOIN reconciliation_results r ON r.request_id=q.id
            WHERE r.request_id IS NULL ORDER BY q.requested_at,q.id
            LIMIT 1""").fetchone()
        if request is None:
            return False
        run = connection.execute(
            "SELECT * FROM experiment_runs WHERE id=%s FOR UPDATE", (request["run_id"],)
        ).fetchone()
        if connection.execute(
            "SELECT 1 FROM reconciliation_results WHERE request_id=%s", (request["id"],)
        ).fetchone():
            return True
        status = "FAILED"
        reason: str | None = "stale_request"
        if (
            run
            and run["status"] == "EXECUTION_UNKNOWN"
            and run["version"] == request["expected_version"]
        ):
            try:
                reconcile(
                    connection,
                    request["run_id"],
                    request["expected_version"],
                    request["actor_id"],
                    str(request["id"]),
                    request["request_id"],
                    request["trace_id"],
                    artifact_root=root,
                )
                status, reason = "SUCCEEDED", None
            except Conflict:
                reason = "receipt_unavailable_or_invalid"
        connection.execute(
            """INSERT INTO reconciliation_results(request_id,status,reason)
            VALUES (%s,%s,%s)""",
            (request["id"], status, reason),
        )
        return True


def dispatch_once(connection: Connection, config: BrokerConfig) -> dict[str, Any] | None:
    """Serialize claims; a fixed engine slot also prevents overlap after DB disconnect."""
    locked = connection.execute("SELECT pg_try_advisory_lock(%s) AS locked", (LOCK_ID,)).fetchone()
    if locked is None or not locked["locked"]:
        return None
    try:
        config.inspect_engine()
        recover_expired(connection)
        if not config.slot_available():
            return None
        process_reconciliation(connection, config.root)
        return execute_next(
            connection,
            config.root,
            simulator=partial(
                simulate_plan,
                image=config.image_id,
                docker_host=config.docker_host,
                container_name=SLOT,
            ),
        )
    finally:
        connection.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if not production_profile():
        raise ConfigurationError("The constrained broker requires the production runtime profile")
    config = BrokerConfig.from_environment()
    config.validate_filesystem()
    with connect() as connection:
        validate_dispatch_role(connection)
        while True:
            result = dispatch_once(connection, config)
            if result is not None:
                print(
                    json.dumps({"run_id": str(result["id"]), "status": result["status"]}),
                    flush=True,
                )
            if args.once:
                return
            time.sleep(1)


if __name__ == "__main__":
    main()
