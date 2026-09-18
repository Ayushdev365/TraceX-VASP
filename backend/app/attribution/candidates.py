"""Entity aggregation for candidates discovered in a trace."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.graph.types import TraversalResult


@dataclass
class AggregatedCandidate:
    """A VASP entity with all its discovered addresses and paths grouped together."""

    vasp_name: str
    vasp_slug: str
    min_hop_distance: int
    matched_addresses: set[str] = field(default_factory=set)
    paths: list[tuple[str, ...]] = field(default_factory=list)


def aggregate_candidates(result: TraversalResult) -> list[AggregatedCandidate]:
    """Group the individual CandidateVasp nodes from a traversal by their VASP entity.

    A trace may hit multiple deposit addresses belonging to the same exchange. This groups
    those hits into a single candidate entity for scoring.
    """
    groups: dict[str, AggregatedCandidate] = {}

    for c in result.candidates:
        if c.vasp_slug not in groups:
            groups[c.vasp_slug] = AggregatedCandidate(
                vasp_name=c.vasp_name,
                vasp_slug=c.vasp_slug,
                min_hop_distance=c.hop_distance,
            )

        agg = groups[c.vasp_slug]

        # Update minimum hop distance
        if c.hop_distance < agg.min_hop_distance:
            agg.min_hop_distance = c.hop_distance

        agg.matched_addresses.add(c.address)

        # Paths are tuples of addresses
        if c.path not in agg.paths:
            agg.paths.append(c.path)

    # Return sorted by min_hop_distance (closest first), then by name
    return sorted(groups.values(), key=lambda a: (a.min_hop_distance, a.vasp_name))
