"""Immutable, simulation-only work order for the first supported Flex profile."""

from typing import Literal, Self
from uuid import UUID

from atlas_domain.hashing import content_hash
from pydantic import BaseModel, ConfigDict, Field, model_validator

Slot = Literal["A1", "A2", "B1", "B2", "B3", "C1", "C2", "C3", "D1", "D2", "D3"]


class Transfer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    candidate_id: str = Field(min_length=1, max_length=200)
    operation: Literal["transfer"] = "transfer"
    source_well: Literal["A1"] = "A1"
    destination_well: str = Field(pattern=r"^[A-H](?:[1-9]|1[0-2])$")
    volume_ul: float = Field(default=50, ge=5, le=200, allow_inf_nan=False, strict=True)


class RunPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0"] = "1.0"
    campaign_id: UUID
    batch_id: UUID
    run_id: UUID
    source_dataset_snapshot: str = Field(min_length=1, max_length=200)
    created_by: str = Field(min_length=1, max_length=200)
    policy_version: Literal["flex-water-v1"] = "flex-water-v1"
    execution_mode: Literal["simulation"] = "simulation"
    instrument_profile: Literal["opentrons-flex-sim"] = "opentrons-flex-sim"
    liquid: Literal["water_placeholder"] = "water_placeholder"
    api_level: Literal["2.20"] = "2.20"
    pipette: Literal["flex_1channel_1000"] = "flex_1channel_1000"
    source_labware: Literal["nest_12_reservoir_15ml"] = "nest_12_reservoir_15ml"
    destination_labware: Literal["corning_96_wellplate_360ul_flat"] = (
        "corning_96_wellplate_360ul_flat"
    )
    tiprack: Literal["opentrons_flex_96_tiprack_1000ul"] = "opentrons_flex_96_tiprack_1000ul"
    source_slot: Slot = "D1"
    destination_slot: Slot = "D2"
    tiprack_slot: Slot = "C1"
    trash_slot: Literal["A3"] = "A3"
    source_available_ul: float = Field(
        default=10000, ge=500, le=12000, allow_inf_nan=False, strict=True
    )
    candidate_ids: tuple[str, ...] = Field(min_length=1, max_length=96)
    transfers: tuple[Transfer, ...] = Field(min_length=1, max_length=96)

    @model_validator(mode="after")
    def semantics(self) -> Self:
        if len({self.source_slot, self.destination_slot, self.tiprack_slot}) != 3:
            raise ValueError("Deck slots collide")
        if len(set(self.candidate_ids)) != len(self.candidate_ids):
            raise ValueError("Duplicate candidates")
        if tuple(t.candidate_id for t in self.transfers) != self.candidate_ids:
            raise ValueError("Exactly one ordered transfer per candidate is required")
        if len({t.destination_well for t in self.transfers}) != len(self.transfers):
            raise ValueError("Destination wells must be unique")
        if sum(t.volume_ul for t in self.transfers) > self.source_available_ul - 500:
            raise ValueError("Insufficient source liquid after 500 uL reserve")
        return self

    def plan_hash(self) -> str:
        return content_hash(self.model_dump(mode="json"))
