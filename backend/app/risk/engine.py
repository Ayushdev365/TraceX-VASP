"""Deterministic risk-indicator engine for traversal results."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from itertools import pairwise

from app.graph.types import GraphEdge, TraversalResult
from app.risk.config import (
    HIGH_FAN_IN_THRESHOLD,
    HIGH_FAN_OUT_THRESHOLD,
    RAPID_MOVEMENT_SECONDS,
    RISK_PENALTIES,
    UNIFORM_SPLIT_MIN_EDGES,
    UNIFORM_SPLIT_TOLERANCE,
)
from app.risk.types import DetectionBasis, RiskIndicator, RiskIndicatorKind
from app.schemas.common import RiskEntityKind, Severity


def detect_risk_indicators(result: TraversalResult) -> list[RiskIndicator]:
    """Return stable, evidence-backed indicators for a completed traversal."""
    indicators: list[RiskIndicator] = []
    indicators.extend(_labelled_entity_indicators(result))
    indicators.extend(_fan_indicators(result))
    indicators.extend(_rapid_movement_indicators(result))
    indicators.extend(_unusual_pattern_indicators(result))
    return sorted(
        indicators,
        key=lambda item: (
            item.kind.value,
            item.evidence_addresses,
            item.evidence_tx_hashes,
            item.summary,
        ),
    )


def risk_penalty_for_path(
    indicators: list[RiskIndicator],
    path: tuple[str, ...],
    *,
    cap: float,
) -> tuple[float, list[RiskIndicator]]:
    """Return capped penalty and matching indicators for a candidate evidence path."""
    path_addresses = set(path)
    matched = [
        indicator
        for indicator in indicators
        if path_addresses.intersection(indicator.evidence_addresses)
    ]
    penalty = min(cap, sum(indicator.penalty for indicator in matched))
    return penalty, matched


def _labelled_entity_indicators(result: TraversalResult) -> list[RiskIndicator]:
    indicators: list[RiskIndicator] = []
    for address, node in sorted(result.nodes.items()):
        if not node.matched_risk_entity_kind:
            continue
        entity_kind = node.matched_risk_entity_kind
        if entity_kind == RiskEntityKind.MIXER.value:
            kind = RiskIndicatorKind.MIXER_INTERACTION
            severity = Severity.HIGH
            summary = "Path touches an address labelled as a mixer service."
        elif entity_kind == RiskEntityKind.BRIDGE.value:
            kind = RiskIndicatorKind.BRIDGE_INTERACTION
            severity = Severity.MEDIUM
            summary = "Path touches an address labelled as a bridge service."
        else:
            kind = RiskIndicatorKind.SANCTIONED_OR_RISK_ENTITY_INTERACTION
            severity = (
                Severity.HIGH if entity_kind == RiskEntityKind.SANCTIONED.value else Severity.MEDIUM
            )
            summary = f"Path touches an address labelled as {entity_kind.replace('_', ' ')}."

        indicators.append(
            RiskIndicator(
                kind=kind,
                severity=severity,
                detection_basis=DetectionBasis.LABELLED_ADDRESS,
                summary=summary,
                evidence_addresses=(address,),
                evidence_tx_hashes=_tx_hashes_touching(result.edges, address),
                penalty=RISK_PENALTIES[kind],
                details={"entity_kind": entity_kind},
            )
        )
    return indicators


def _fan_indicators(result: TraversalResult) -> list[RiskIndicator]:
    in_counts: Counter[str] = Counter()
    out_counts: Counter[str] = Counter()
    in_hashes: dict[str, list[str]] = defaultdict(list)
    out_hashes: dict[str, list[str]] = defaultdict(list)

    for edge in result.edges:
        out_counts[edge.from_address] += 1
        in_counts[edge.to_address] += 1
        out_hashes[edge.from_address].append(edge.tx_hash)
        in_hashes[edge.to_address].append(edge.tx_hash)

    indicators: list[RiskIndicator] = []
    for address, count in sorted(in_counts.items()):
        if count >= HIGH_FAN_IN_THRESHOLD:
            indicators.append(
                RiskIndicator(
                    kind=RiskIndicatorKind.HIGH_FAN_IN,
                    severity=Severity.MEDIUM,
                    detection_basis=DetectionBasis.HEURISTIC,
                    summary="Address receives funds from many observed counterparties.",
                    evidence_addresses=(address,),
                    evidence_tx_hashes=tuple(sorted(set(in_hashes[address]))),
                    penalty=RISK_PENALTIES[RiskIndicatorKind.HIGH_FAN_IN],
                    details={"incoming_edges": count},
                )
            )

    for address, count in sorted(out_counts.items()):
        node = result.nodes.get(address)
        terminal_reason = node.not_expanded_reason if node else None
        if count >= HIGH_FAN_OUT_THRESHOLD or (terminal_reason and "fanout" in terminal_reason):
            indicators.append(
                RiskIndicator(
                    kind=RiskIndicatorKind.HIGH_FAN_OUT,
                    severity=Severity.MEDIUM,
                    detection_basis=DetectionBasis.HEURISTIC,
                    summary="Address sends funds to many observed counterparties.",
                    evidence_addresses=(address,),
                    evidence_tx_hashes=tuple(sorted(set(out_hashes[address]))),
                    penalty=RISK_PENALTIES[RiskIndicatorKind.HIGH_FAN_OUT],
                    details={"outgoing_edges": count},
                )
            )
    return indicators


def _rapid_movement_indicators(result: TraversalResult) -> list[RiskIndicator]:
    by_pair: dict[tuple[str, str], list[GraphEdge]] = defaultdict(list)
    for edge in result.edges:
        by_pair[(edge.from_address, edge.to_address)].append(edge)

    indicators: list[RiskIndicator] = []
    seen_paths: set[tuple[str, ...]] = set()
    for path in sorted(result.paths.values()):
        if len(path) < 3 or path in seen_paths:
            continue
        seen_paths.add(path)
        path_edges: list[GraphEdge] = []
        for left, right in pairwise(path):
            edges = by_pair.get((left, right), [])
            if not edges:
                path_edges = []
                break
            path_edges.append(min(edges, key=lambda edge: (edge.block_timestamp, edge.tx_hash)))
        if len(path_edges) < 2:
            continue
        timestamps = [edge.block_timestamp for edge in path_edges]
        if _is_rapid_sequence(timestamps):
            indicators.append(
                RiskIndicator(
                    kind=RiskIndicatorKind.RAPID_MOVEMENT,
                    severity=Severity.LOW,
                    detection_basis=DetectionBasis.HEURISTIC,
                    summary="Funds move across multiple hops in a short time window.",
                    evidence_addresses=path,
                    evidence_tx_hashes=tuple(edge.tx_hash for edge in path_edges),
                    penalty=RISK_PENALTIES[RiskIndicatorKind.RAPID_MOVEMENT],
                    details={"max_interhop_seconds": _max_gap_seconds(timestamps)},
                )
            )
    return _dedupe_by_kind_and_hashes(indicators)


def _unusual_pattern_indicators(result: TraversalResult) -> list[RiskIndicator]:
    outgoing: dict[str, list[GraphEdge]] = defaultdict(list)
    for edge in result.edges:
        outgoing[edge.from_address].append(edge)

    indicators: list[RiskIndicator] = []
    for address, edges in sorted(outgoing.items()):
        if len(edges) < UNIFORM_SPLIT_MIN_EDGES:
            continue
        amounts = [edge.amount for edge in edges]
        if _amounts_are_uniform(amounts):
            counterparties = tuple(sorted({edge.to_address for edge in edges}))
            indicators.append(
                RiskIndicator(
                    kind=RiskIndicatorKind.UNUSUAL_TRANSACTION_PATTERN,
                    severity=Severity.LOW,
                    detection_basis=DetectionBasis.HEURISTIC,
                    summary="Address sends similarly sized transfers to multiple counterparties.",
                    evidence_addresses=(address, *counterparties),
                    evidence_tx_hashes=tuple(sorted({edge.tx_hash for edge in edges})),
                    penalty=RISK_PENALTIES[RiskIndicatorKind.UNUSUAL_TRANSACTION_PATTERN],
                    details={"outgoing_edges": len(edges)},
                )
            )
    return indicators


def _tx_hashes_touching(edges: list[GraphEdge], address: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                edge.tx_hash
                for edge in edges
                if edge.from_address == address or edge.to_address == address
            }
        )
    )


def _is_rapid_sequence(timestamps: list[datetime]) -> bool:
    if timestamps != sorted(timestamps):
        return False
    return _max_gap_seconds(timestamps) <= RAPID_MOVEMENT_SECONDS


def _max_gap_seconds(timestamps: list[datetime]) -> int:
    gaps = [int((right - left).total_seconds()) for left, right in pairwise(timestamps)]
    return max(gaps, default=0)


def _amounts_are_uniform(amounts: list[Decimal]) -> bool:
    if not amounts:
        return False
    first = amounts[0]
    if first == 0:
        return all(amount == 0 for amount in amounts)
    tolerance = abs(first) * Decimal(str(UNIFORM_SPLIT_TOLERANCE))
    return all(abs(amount - first) <= tolerance for amount in amounts[1:])


def _dedupe_by_kind_and_hashes(indicators: list[RiskIndicator]) -> list[RiskIndicator]:
    deduped: dict[tuple[RiskIndicatorKind, tuple[str, ...]], RiskIndicator] = {}
    for indicator in indicators:
        key = (indicator.kind, indicator.evidence_tx_hashes)
        deduped.setdefault(key, indicator)
    return list(deduped.values())
