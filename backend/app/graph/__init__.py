"""Graph traversal engine — Phase 6.

Public API::

    from app.graph import TraversalEngine, TraversalResult

    engine = TraversalEngine(adapter, chain)
    result = await engine.traverse(address, hop_depth=3)
"""

from app.graph.engine import LabelHit, LabelLookupFn, TraversalEngine
from app.graph.types import (
    CandidateVasp,
    GraphEdge,
    GraphNode,
    TraversalResult,
)

__all__ = [
    "CandidateVasp",
    "GraphEdge",
    "GraphNode",
    "LabelHit",
    "LabelLookupFn",
    "TraversalEngine",
    "TraversalResult",
]
