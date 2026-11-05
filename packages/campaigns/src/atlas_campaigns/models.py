"""Public campaign commands and durable record views."""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Objective(Contract):
    metric: Literal["observed_yield_pct"] = "observed_yield_pct"
    direction: Literal["maximize"] = "maximize"


class Budget(Contract):
    max_unique_experiments: int = Field(default=48, ge=1, le=48, strict=True)
    batch_size: int = Field(default=8, ge=1, le=8, strict=True)

    @model_validator(mode="after")
    def valid_batch_size(self) -> Self:
        if self.batch_size > self.max_unique_experiments:
            raise ValueError("Batch size exceeds campaign budget")
        return self


class CreateCampaign(Contract):
    dataset_snapshot_id: str = Field(min_length=1, max_length=200)
    campaign_group_id: str = Field(min_length=1, max_length=200)
    objective: Objective = Field(default_factory=Objective)
    budget: Budget = Field(default_factory=Budget)
    seed: int = Field(default=42, ge=0, le=2147483647, strict=True)
    mode: Literal["historical_replay_with_robot_simulation"] = (
        "historical_replay_with_robot_simulation"
    )


class Campaign(Contract):
    id: UUID
    owner_id: str
    snapshot_id: str
    group_id: str
    budget_max: int
    batch_size: int
    budget_used: int
    seed: int
    status: str
    version: int
    created_at: datetime
