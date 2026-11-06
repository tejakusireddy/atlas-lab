"""Opt-in OpenTelemetry with durable W3C context and ID-only span attributes."""

import inspect
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from threading import Lock
from typing import Any, ParamSpec, TypeVar

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.trace import Span, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from psycopg.types.json import Jsonb

from atlas_campaigns.database import Connection

P = ParamSpec("P")
R = TypeVar("R")
provider: TracerProvider | None = None
lock = Lock()
propagator = TraceContextTextMapPropagator()


def configured_provider() -> TracerProvider | None:
    global provider
    mode = os.environ.get("ATLAS_OTEL_EXPORTER", "disabled")
    if provider is None and mode in ("console", "otlp"):
        with lock:
            if provider is None:
                selected = TracerProvider(
                    resource=Resource.create(
                        {"service.name": os.environ.get("OTEL_SERVICE_NAME", "atlas")}
                    )
                )
                if mode == "console":
                    selected.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
                else:
                    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                        OTLPSpanExporter,
                    )

                    selected.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
                provider = selected
    return provider


@contextmanager
def local_span(
    name: str, carrier: dict[str, str] | None = None, campaign_id: str | None = None
) -> Iterator[Span]:
    active = configured_provider()
    tracer = (
        active.get_tracer("atlas.campaigns", "1.0")
        if active
        else trace.get_tracer("atlas.disabled")
    )
    context = propagator.extract(carrier) if carrier else None
    with tracer.start_as_current_span(
        name, context=context, record_exception=False, set_status_on_exception=False
    ) as span:
        if campaign_id:
            span.set_attribute("atlas.campaign_id", campaign_id)
        try:
            yield span
        except BaseException as error:
            span.set_status(Status(StatusCode.ERROR, type(error).__name__))
            span.add_event("operation.failed", {"error.type": type(error).__name__})
            raise


def campaign_for_run(connection: Connection, run_id: Any) -> Any:
    row = connection.execute(
        "SELECT b.campaign_id FROM experiment_runs r "
        "JOIN experiment_batches b ON b.id=r.batch_id WHERE r.id=%s",
        (run_id,),
    ).fetchone()
    return row["campaign_id"] if row else None


@contextmanager
def resource_span(
    connection: Connection, name: str, campaign_id: Any = None, run_id: Any = None
) -> Iterator[Span]:
    if configured_provider() is not None:
        campaign_id = campaign_id or (campaign_for_run(connection, run_id) if run_id else None)
        row = (
            connection.execute(
                "SELECT carrier FROM campaign_trace_contexts WHERE campaign_id=%s", (campaign_id,)
            ).fetchone()
            if campaign_id
            else None
        )
        carrier = row["carrier"] if row else None
    else:
        carrier = None
    with local_span(name, carrier, str(campaign_id) if campaign_id else None) as span:
        if run_id:
            span.set_attribute("atlas.run_id", str(run_id))
        yield span


def operation(name: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorate(function: Callable[P, R]) -> Callable[P, R]:
        signature = inspect.signature(function)

        @wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            arguments = signature.bind(*args, **kwargs).arguments
            connection = arguments["connection"]
            with resource_span(
                connection, name, arguments.get("campaign_id"), arguments.get("run_id")
            ):
                return function(*args, **kwargs)

        return wrapped

    return decorate


def remember_campaign(connection: Connection, campaign_id: Any) -> None:
    """Persist the creation span carrier in the campaign creation transaction."""
    if configured_provider() is None:
        return
    trace.get_current_span().set_attribute("atlas.campaign_id", str(campaign_id))
    carrier: dict[str, str] = {}
    propagator.inject(carrier)
    connection.execute(
        "INSERT INTO campaign_trace_contexts(campaign_id,carrier) VALUES (%s,%s) "
        "ON CONFLICT DO NOTHING",
        (campaign_id, Jsonb(carrier)),
    )
