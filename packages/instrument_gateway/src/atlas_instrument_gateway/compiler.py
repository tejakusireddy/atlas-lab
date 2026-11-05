"""Deterministic code generation from a fixed, reviewed simulation template."""

import ast
import hashlib
from dataclasses import dataclass

from atlas_instrument_gateway.spec import RunPlan


@dataclass(frozen=True)
class ProtocolArtifact:
    plan_hash: str
    protocol_hash: str
    source: str


def compile_protocol(plan: RunPlan) -> ProtocolArtifact:
    # Revalidate even if a caller used an unchecked model_copy/model_construct.
    plan = RunPlan.model_validate(plan.model_dump())
    lines = [
        "from opentrons import protocol_api",
        "",
        "metadata = {'protocolName': 'ATLAS water transfer simulation'}",
        "requirements = {'robotType': 'Flex', 'apiLevel': '2.20'}",
        "",
        "def run(ctx: protocol_api.ProtocolContext):",
        f"    source = ctx.load_labware({plan.source_labware!r}, {plan.source_slot!r})",
        f"    destination = ctx.load_labware({plan.destination_labware!r}, "
        f"{plan.destination_slot!r})",
        f"    tips = ctx.load_labware({plan.tiprack!r}, {plan.tiprack_slot!r})",
        f"    ctx.load_trash_bin({plan.trash_slot!r})",
        f"    pipette = ctx.load_instrument({plan.pipette!r}, 'left', tip_racks=[tips])",
        "    water = ctx.define_liquid(name='Water placeholder', "
        "description='Simulation only', display_color='#4C9BE8')",
        f"    source['A1'].load_liquid(water, {plan.source_available_ul!r})",
    ]
    for transfer in plan.transfers:
        lines.extend(
            [
                "    pipette.pick_up_tip()",
                f"    pipette.aspirate({transfer.volume_ul!r}, source['A1'])",
                f"    pipette.dispense({transfer.volume_ul!r}, "
                f"destination[{transfer.destination_well!r}])",
                "    pipette.drop_tip()",
            ]
        )
    source = "\n".join(lines) + "\n"
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            raise ValueError("Unexpected protocol import")
        if isinstance(node, ast.ImportFrom) and (
            node.module != "opentrons" or [alias.name for alias in node.names] != ["protocol_api"]
        ):
            raise ValueError("Unexpected protocol import")
    return ProtocolArtifact(
        plan.plan_hash(), "sha256:" + hashlib.sha256(source.encode()).hexdigest(), source
    )
