"""HTTP application; all scientific mutations remain in domain services."""

from collections.abc import Iterator
from typing import Annotated, Any
from uuid import UUID, uuid4

import psycopg
import uvicorn
from atlas_campaigns.analysis import analyze
from atlas_campaigns.database import Connection, connect
from atlas_campaigns.execution import enqueue_simulation, get_run, reconcile, request_reconciliation
from atlas_campaigns.models import CreateCampaign
from atlas_campaigns.permissions import validate_application_role
from atlas_campaigns.secrets import ConfigurationError, production_profile
from atlas_campaigns.service import (
    Conflict,
    NotFound,
    create_campaign,
    get_campaign,
    list_campaigns,
)
from atlas_campaigns.workflow import (
    DecisionCommand,
    Forbidden,
    ProposeCommand,
    VersionCommand,
    decide_batch,
    get_batch,
    propose_batch,
)
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from atlas_api.auth import Principal, authentication_profile, principal


def database() -> Iterator[Connection]:
    with connect() as connection:
        if production_profile():
            validate_application_role(connection)
        yield connection


Database = Annotated[Connection, Depends(database)]
Identity = Annotated[Principal, Depends(principal)]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]


def envelope(
    request: Request, data: Any = None, errors: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {
        "data": jsonable_encoder(data),
        "meta": {
            "request_id": request.state.request_id,
            "trace_id": request.state.trace_id,
            "schema_version": "1.0",
        },
        "errors": errors or [],
    }


def create_app() -> FastAPI:
    app = FastAPI(title="ATLAS Lab", version="0.1.0")

    @app.middleware("http")
    async def request_context(request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.request_id = str(uuid4())
        request.state.trace_id = uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, error: RequestValidationError) -> JSONResponse:
        issues = [
            {"code": item["type"], "message": item["msg"], "location": list(item["loc"])}
            for item in error.errors()
        ]
        return JSONResponse(envelope(request, errors=issues), status_code=422)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        return JSONResponse(
            envelope(request, errors=[{"code": str(error.status_code), "message": error.detail}]),
            status_code=error.status_code,
            headers=error.headers,
        )

    @app.exception_handler(Forbidden)
    async def forbidden(request: Request, error: Forbidden) -> JSONResponse:
        return JSONResponse(
            envelope(request, errors=[{"code": "forbidden", "message": str(error)}]),
            status_code=403,
        )

    @app.exception_handler(Conflict)
    async def conflict(request: Request, error: Conflict) -> JSONResponse:
        return JSONResponse(
            envelope(request, errors=[{"code": "conflict", "message": str(error)}]), status_code=409
        )

    @app.exception_handler(NotFound)
    async def not_found(request: Request, error: NotFound) -> JSONResponse:
        return JSONResponse(
            envelope(request, errors=[{"code": "not_found", "message": str(error)}]),
            status_code=404,
        )

    @app.exception_handler(ConfigurationError)
    async def configuration_error(request: Request, error: ConfigurationError) -> JSONResponse:
        return JSONResponse(
            envelope(
                request,
                errors=[
                    {
                        "code": "configuration_unavailable",
                        "message": "Service configuration is unavailable",
                    }
                ],
            ),
            status_code=503,
        )

    @app.exception_handler(psycopg.OperationalError)
    async def unavailable(request: Request, error: psycopg.OperationalError) -> JSONResponse:
        return JSONResponse(
            envelope(
                request,
                errors=[{"code": "database_unavailable", "message": "Database unavailable"}],
            ),
            status_code=503,
        )

    @app.get("/health/live")
    def live(request: Request) -> dict[str, Any]:
        return envelope(request, {"status": "ok"})

    @app.get("/health/ready")
    def ready(request: Request, connection: Database) -> dict[str, Any]:
        authentication_profile()
        if production_profile():
            validate_application_role(connection)
        connection.execute("SELECT 1 FROM schema_migrations LIMIT 1")
        return envelope(request, {"status": "ready"})

    @app.get("/v1/system/capabilities")
    def capabilities(request: Request) -> dict[str, Any]:
        return envelope(
            request,
            {
                "execution_mode": "simulation",
                "physical_dispatch": False,
                "campaign_persistence": True,
                "protocol_simulator": "opentrons_10.1.0_worker",
                "oracle_replay": "separate_checksum_verified_worker",
                "nvidia_providers": "not_configured",
                "auth_profile": authentication_profile(),
            },
        )

    @app.post("/v1/campaigns", status_code=201)
    def create(
        request: Request,
        command: CreateCampaign,
        identity: Identity,
        connection: Database,
        idempotency_key: IdempotencyKey,
    ) -> dict[str, Any]:
        if not identity.has_role("scientist"):
            raise HTTPException(403, "Scientist role required")
        result = create_campaign(
            connection,
            command,
            identity.actor,
            idempotency_key,
            UUID(request.state.request_id),
            request.state.trace_id,
        )
        return envelope(request, result)

    @app.get("/v1/campaigns")
    def listing(
        request: Request,
        identity: Identity,
        connection: Database,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, Any]:
        return envelope(request, list_campaigns(connection, identity.actor, limit, offset))

    @app.get("/v1/campaigns/{campaign_id}")
    def retrieve(
        request: Request, campaign_id: UUID, identity: Identity, connection: Database
    ) -> dict[str, Any]:
        return envelope(request, get_campaign(connection, campaign_id, identity.actor))

    @app.get("/v1/campaigns/{campaign_id}/measurements")
    def measurements(
        request: Request, campaign_id: UUID, identity: Identity, connection: Database
    ) -> dict[str, Any]:
        get_campaign(connection, campaign_id, identity.actor)
        return envelope(
            request,
            list(
                connection.execute(
                    "SELECT * FROM measurements WHERE campaign_id=%s "
                    "ORDER BY revealed_at,candidate_id",
                    (campaign_id,),
                )
            ),
        )

    @app.post("/v1/runs/{run_id}/analyze")
    def analyze_run(
        request: Request,
        run_id: UUID,
        command: VersionCommand,
        identity: Identity,
        connection: Database,
        idempotency_key: IdempotencyKey,
    ) -> dict[str, Any]:
        if not identity.has_role("scientist"):
            raise HTTPException(403, "Scientist role required")
        return envelope(
            request,
            analyze(
                connection,
                run_id,
                command.expected_version,
                identity.actor,
                idempotency_key,
                request.state.request_id,
                request.state.trace_id,
            ),
        )

    @app.get("/v1/campaigns/{campaign_id}/analyses")
    def analyses(
        request: Request, campaign_id: UUID, identity: Identity, connection: Database
    ) -> dict[str, Any]:
        get_campaign(connection, campaign_id, identity.actor)
        return envelope(
            request,
            list(
                connection.execute(
                    "SELECT * FROM campaign_analyses WHERE campaign_id=%s ORDER BY created_at,id",
                    (campaign_id,),
                )
            ),
        )

    @app.get("/v1/datasets")
    def datasets(request: Request, identity: Identity, connection: Database) -> dict[str, Any]:
        return envelope(
            request,
            list(
                connection.execute(
                    "SELECT snapshot_id,group_id,eligible_count FROM dataset_groups "
                    "ORDER BY snapshot_id,group_id"
                )
            ),
        )

    @app.post("/v1/campaigns/{campaign_id}/plan", status_code=201)
    def plan(
        request: Request,
        campaign_id: UUID,
        command: ProposeCommand,
        identity: Identity,
        connection: Database,
        idempotency_key: IdempotencyKey,
    ) -> dict[str, Any]:
        if not identity.has_role("scientist"):
            raise HTTPException(403, "Scientist role required")
        return envelope(
            request,
            propose_batch(
                connection,
                campaign_id,
                command,
                identity.actor,
                idempotency_key,
                UUID(request.state.request_id),
                request.state.trace_id,
            ),
        )

    @app.get("/v1/campaigns/{campaign_id}/batches/{batch_id}")
    def batch(
        request: Request,
        campaign_id: UUID,
        batch_id: UUID,
        identity: Identity,
        connection: Database,
    ) -> dict[str, Any]:
        return envelope(
            request, get_batch(connection, campaign_id, batch_id, identity.actor, identity.role)
        )

    @app.post("/v1/campaigns/{campaign_id}/batches/{batch_id}/approve")
    def approve(
        request: Request,
        campaign_id: UUID,
        batch_id: UUID,
        command: DecisionCommand,
        identity: Identity,
        connection: Database,
        idempotency_key: IdempotencyKey,
    ) -> dict[str, Any]:
        return envelope(
            request,
            decide_batch(
                connection,
                campaign_id,
                batch_id,
                command,
                "APPROVE",
                identity.actor,
                identity.role,
                idempotency_key,
                UUID(request.state.request_id),
                request.state.trace_id,
            ),
        )

    @app.post("/v1/campaigns/{campaign_id}/batches/{batch_id}/reject")
    def reject(
        request: Request,
        campaign_id: UUID,
        batch_id: UUID,
        command: DecisionCommand,
        identity: Identity,
        connection: Database,
        idempotency_key: IdempotencyKey,
    ) -> dict[str, Any]:
        return envelope(
            request,
            decide_batch(
                connection,
                campaign_id,
                batch_id,
                command,
                "REJECT",
                identity.actor,
                identity.role,
                idempotency_key,
                UUID(request.state.request_id),
                request.state.trace_id,
            ),
        )

    @app.get("/v1/approvals/pending")
    def pending(request: Request, identity: Identity, connection: Database) -> dict[str, Any]:
        if not identity.has_role("reviewer"):
            raise HTTPException(403, "Reviewer role required")
        return envelope(
            request,
            list(
                connection.execute(
                    "SELECT * FROM experiment_batches WHERE status='AWAITING_APPROVAL' "
                    "ORDER BY created_at,id LIMIT 100"
                )
            ),
        )

    @app.post("/v1/runs/{run_id}/simulate", status_code=202)
    def simulate(
        request: Request,
        run_id: UUID,
        command: VersionCommand,
        identity: Identity,
        connection: Database,
        idempotency_key: IdempotencyKey,
    ) -> dict[str, Any]:
        if not identity.has_role("scientist"):
            raise HTTPException(403, "Scientist role required")
        return envelope(
            request,
            enqueue_simulation(
                connection,
                run_id,
                command.expected_version,
                identity.actor,
                idempotency_key,
                UUID(request.state.request_id),
                request.state.trace_id,
            ),
        )

    @app.get("/v1/runs/{run_id}")
    def run(
        request: Request, run_id: UUID, identity: Identity, connection: Database
    ) -> dict[str, Any]:
        return envelope(request, get_run(connection, run_id, identity.actor, identity.role))

    @app.get("/v1/runs/{run_id}/events")
    def events(
        request: Request, run_id: UUID, identity: Identity, connection: Database
    ) -> dict[str, Any]:
        get_run(connection, run_id, identity.actor, identity.role)
        return envelope(
            request,
            list(
                connection.execute(
                    "SELECT * FROM run_events WHERE run_id=%s ORDER BY sequence", (run_id,)
                )
            ),
        )

    @app.post("/v1/runs/{run_id}/reconcile")
    def reconcile_run(
        request: Request,
        response: Response,
        run_id: UUID,
        command: VersionCommand,
        identity: Identity,
        connection: Database,
        idempotency_key: IdempotencyKey,
    ) -> dict[str, Any]:
        if not identity.has_role("reviewer"):
            raise HTTPException(403, "Reviewer role required")
        if production_profile():
            response.status_code = 202
        return envelope(
            request,
            (request_reconciliation if production_profile() else reconcile)(
                connection,
                run_id,
                command.expected_version,
                identity.actor,
                idempotency_key,
                UUID(request.state.request_id),
                request.state.trace_id,
            ),
        )

    @app.get("/v1/runs/{run_id}/reconciliation-requests")
    def reconciliation_status(
        request: Request,
        run_id: UUID,
        identity: Identity,
        connection: Database,
    ) -> dict[str, Any]:
        if not identity.has_role("reviewer"):
            raise HTTPException(403, "Reviewer role required")
        get_run(connection, run_id, identity.actor, identity.role)
        return envelope(
            request,
            list(
                connection.execute(
                    """SELECT q.id,q.expected_version,q.requested_at,
                    COALESCE(r.status,'PENDING') AS status,r.reason,r.completed_at
            FROM reconciliation_requests q LEFT JOIN reconciliation_results r ON r.request_id=q.id
            WHERE q.run_id=%s ORDER BY q.requested_at,q.id""",
                    (run_id,),
                )
            ),
        )

    return app


app = create_app()


def serve() -> None:
    uvicorn.run("atlas_api.main:app", host="127.0.0.1", port=8000)
