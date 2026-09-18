"""Configuration for the attribution scoring engine."""

SCORING_CONFIG_VERSION = "1.0.0"

# Minimum score to be considered a primary attribution
MIN_ATTRIBUTION_SCORE = 35

# Maximum possible score
MAX_SCORE = 100

# Base score to start from before applying factors and penalties
BASE_SCORE = 100

# Weights for different factors (must sum to 1.0)
# Note: since the prompt asks for configurable weights, we expose them here.
WEIGHTS = {
    "hop_distance": 0.50,
    "tx_count": 0.30,
    "volume": 0.20,
}

# Hop penalty multiplier: multiplier applied based on the shortest path distance.
# 1 hop = 1.0 (no penalty)
# 2 hops = 0.8
# 3 hops = 0.5
# 4 hops = 0.3
# 5 hops = 0.1
# 6 hops = 0.05
HOP_MULTIPLIERS = {
    0: 1.0,
    1: 1.0,
    2: 0.8,
    3: 0.5,
    4: 0.3,
    5: 0.1,
    6: 0.05,
}


def get_score_band(score: int) -> str:
    """Map a numeric score to a confidence band."""
    if score >= 85:
        return "very_strong"
    if score >= 70:
        return "strong"
    if score >= 55:
        return "moderate"
    if score >= 35:
        return "low"
    return "insufficient"
