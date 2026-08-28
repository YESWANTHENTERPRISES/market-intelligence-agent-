import hashlib
import json
from datetime import datetime, timezone
from typing import List, Dict, Any
from app.replay.models import ReplayConfig


def compute_dataset_hash(candles: List[Dict[str, Any]]) -> str:
    """
    Computes a SHA256 hash across candle timestamps and OHLC values to guarantee reproducibility.
    """
    hasher = hashlib.sha256()
    for c in candles:
        line = f"{c.get('timestamp')}:{c.get('open')}:{c.get('high')}:{c.get('low')}:{c.get('close')}:{c.get('volume', 0)}"
        hasher.update(line.encode("utf-8"))
    return hasher.hexdigest()[:16]


def compute_config_hash(config: ReplayConfig) -> str:
    """
    Computes SHA256 hash of configuration parameters.
    """
    hasher = hashlib.sha256()
    cfg_json = json.dumps(config.model_dump(), sort_keys=True)
    hasher.update(cfg_json.encode("utf-8"))
    return hasher.hexdigest()[:16]


def get_reproducibility_metadata(candles: List[Dict[str, Any]], config: ReplayConfig) -> Dict[str, Any]:
    """
    Returns exact reproducibility metadata for historical replay report.
    """
    return {
        "dataset_hash": compute_dataset_hash(candles),
        "config_hash": compute_config_hash(config),
        "code_version": "v1.0.0-step7.5",
        "engine_version": "7.5.0-baseline",
        "baseline_version": "7.5-frozen-baseline",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "timezone": "UTC",
        "symbol": config.symbol,
        "timeframe": config.timeframe
    }
