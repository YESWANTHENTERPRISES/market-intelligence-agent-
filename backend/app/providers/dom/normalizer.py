import time
from typing import Dict, List, Optional, Tuple
from app.providers.dom.models import SourceSnapshot, SourceStatus, PriceLevel

MAX_BASIS_TIMESTAMP_DELTA_SEC = 60.0
MAX_LIVE_FRESHNESS_SEC = 30.0
MAX_DELAYED_FRESHNESS_SEC = 900.0  # 15 minutes

# Default source weights specified by prompt
DEFAULT_DOM_SOURCE_WEIGHTS = {
    "COMEX": 0.40,
    "OANDA": 0.25,
    "DUKASCOPY": 0.20,
    "FXCM": 0.15,
}

def classify_freshness(snapshot: SourceSnapshot, current_time: Optional[float] = None) -> Tuple[SourceStatus, str]:
    if current_time is None:
        current_time = time.time()

    if snapshot.status in [SourceStatus.DOWN, SourceStatus.UNAVAILABLE]:
        return SourceStatus.UNAVAILABLE, "UNAVAILABLE"

    age = current_time - snapshot.observed_timestamp
    if age < 0:
        age = 0.0

    snapshot.freshness_seconds = round(age, 1)

    if snapshot.status == SourceStatus.DELAYED or age > MAX_DELAYED_FRESHNESS_SEC:
        if age > 3600.0:
            return SourceStatus.STALE, "STALE (>1H)"
        return SourceStatus.DELAYED, "DELAYED 15M"
    elif age > MAX_LIVE_FRESHNESS_SEC:
        return SourceStatus.STALE, f"STALE ({int(age)}s)"
    else:
        return SourceStatus.LIVE, "LIVE"

def calculate_basis(
    futures_mid: Optional[float],
    spot_mid: Optional[float],
    futures_ts: float,
    spot_ts: float,
    max_delta_sec: float = MAX_BASIS_TIMESTAMP_DELTA_SEC
) -> Tuple[Optional[float], str]:
    """
    basis = futures_mid - spot_mid
    Rejects or marks invalid when timestamps diverge > max_delta_sec or prices <= 0.
    """
    if futures_mid is None or spot_mid is None or futures_mid <= 0 or spot_mid <= 0:
        return None, "UNAVAILABLE"

    if abs(futures_ts - spot_ts) > max_delta_sec:
        return None, "UNAVAILABLE"

    raw_basis = round(futures_mid - spot_mid, 4)
    sign = "+" if raw_basis >= 0 else "-"
    formatted = f"{sign}${abs(raw_basis):.2f}"
    return raw_basis, formatted

def normalize_futures_price(futures_price: float, basis: Optional[float]) -> Optional[float]:
    """
    normalized_level = comex_level - basis
    All Important Levels must exist on the XAUUSD spot price axis.
    Returns None if basis is unavailable to prevent un-normalized futures prices from masquerading as spot coordinates.
    """
    if basis is None:
        return None
    return round(futures_price - basis, 4)


def score_relative_depth(levels: List[PriceLevel]) -> List[PriceLevel]:
    """
    Normalizes raw depth numbers into relative 0-100 scores to allow
    cross-market source weighting without direct unit comparison.
    """
    if not levels:
        return []

    max_vol = max((lvl.volume for lvl in levels), default=1.0)
    if max_vol <= 0:
        max_vol = 1.0

    scored = []
    for lvl in levels:
        rel_score = min(100.0, (lvl.volume / max_vol) * 100.0)
        lvl_copy = lvl.model_copy(update={"relative_score": round(rel_score, 1)})
        scored.append(lvl_copy)
    return scored

def renormalize_weights(
    active_source_ids: List[str],
    default_weights: Optional[Dict[str, float]] = None
) -> Dict[str, float]:
    """
    If a source is unavailable:
    remove its weight and redistribute remaining weights proportionally.
    NEVER treat missing DOM as neutral.
    """
    if default_weights is None:
        default_weights = DEFAULT_DOM_SOURCE_WEIGHTS

    eligible = {sid: default_weights.get(sid, 0.0) for sid in active_source_ids if sid in default_weights}
    total_weight = sum(eligible.values())

    if total_weight <= 0:
        if not active_source_ids:
            return {}
        equal_w = 1.0 / len(active_source_ids)
        return {sid: equal_w for sid in active_source_ids}

    return {sid: weight / total_weight for sid, weight in eligible.items()}
