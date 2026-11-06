"""A restarted process must join the campaign trace through persisted W3C context."""

import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any
from uuid import uuid4

import pytest
from atlas_campaigns import telemetry
from atlas_campaigns.database import Connection
from atlas_campaigns.models import CreateCampaign
from atlas_campaigns.service import create_campaign
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

CHILD = """
import os
from uuid import UUID,uuid4
from psycopg import sql
from atlas_campaigns.database import connect
from atlas_campaigns.workflow import propose_batch,ProposeCommand
from atlas_campaigns.telemetry import configured_provider
with connect(os.environ["ATLAS_TEST_DATABASE_URL"]) as db:
    db.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(os.environ["TEST_SCHEMA"])))
    propose_batch(db,UUID(os.environ["TEST_CAMPAIGN"]),ProposeCommand(expected_version=0),
                  "scientist","child-plan",uuid4(),"correlation")
configured_provider().force_flush(timeout_millis=5000)
configured_provider().shutdown()
"""


def test_otlp_export_and_cross_process_parentage(
    database: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    received: list[bytes] = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            received.append(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(200)
            self.send_header("Content-Type", "application/x-protobuf")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            pass

    memory = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(memory))
    monkeypatch.setattr(telemetry, "provider", provider)
    campaign = create_campaign(
        database,
        CreateCampaign(
            dataset_snapshot_id="synthetic-snapshot", campaign_group_id="synthetic-group"
        ),
        "scientist",
        "create",
        uuid4(),
        "correlation",
    )
    parent = memory.get_finished_spans()[0]
    assert parent.context is not None
    schema = database.execute("SELECT current_schema() AS name").fetchone()
    assert schema is not None
    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(
            [sys.executable, "-c", CHILD],
            capture_output=True,
            text=True,
            timeout=20,
            env=os.environ
            | {
                "ATLAS_OTEL_EXPORTER": "otlp",
                "OTEL_SERVICE_NAME": "atlas-restarted-worker",
                "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": f"http://127.0.0.1:{server.server_port}/v1/traces",
                "TEST_SCHEMA": schema["name"],
                "TEST_CAMPAIGN": str(campaign.id),
            },
        )
        assert result.returncode == 0, result.stderr
        assert received
        spans: list[Any] = []
        for payload in received:
            request = ExportTraceServiceRequest.FromString(payload)
            spans.extend(
                s
                for resource in request.resource_spans
                for scope in resource.scope_spans
                for s in scope.spans
            )
        proposal = next(s for s in spans if s.name == "batch.propose")
        assert int.from_bytes(proposal.trace_id, "big") == parent.context.trace_id
        assert int.from_bytes(proposal.parent_span_id, "big") == parent.context.span_id
        assert set(a.key for a in proposal.attributes) == {"atlas.campaign_id"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        provider.shutdown()
