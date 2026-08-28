from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field

class SourceStatus(str, Enum):
    LIVE = "LIVE"
    DELAYED = "DELAYED"
    STALE = "STALE"
    DOWN = "DOWN"
    UNAVAILABLE = "UNAVAILABLE"

class PriceLevel(BaseModel):
    price: float
    volume: float
    normalized_price: Optional[float] = None
    relative_score: Optional[float] = None

class SourceSnapshot(BaseModel):
    source_id: str
    source_name: str
    status: SourceStatus
    observed_timestamp: float
    freshness_seconds: float = 0.0
    freshness_label: str = "LIVE"
    bids: List[PriceLevel] = Field(default_factory=list)
    asks: List[PriceLevel] = Field(default_factory=list)
    retail_long_pct: Optional[float] = None
    retail_short_pct: Optional[float] = None
    raw_contract_unit: str = "lots"
    raw_futures_price: Optional[float] = None
    raw_spot_price: Optional[float] = None
    included_in_aggregation: bool = False

class LiquidityZone(BaseModel):
    price_range: str
    side: str  # "ASK LIQUIDITY" | "BID LIQUIDITY"
    impact: str  # "HIGH" | "MODERATE" | "LOW"
    score: float = 0.0
    observed: bool = True
    source: str = "OBSERVED"


class SourceDetail(BaseModel):
    name: str
    status: str  # e.g. "LIVE", "DELAYED 15M", "STALE", "UNAVAILABLE"
    freshness: str
    included_in_aggregation: bool

class DOMIntelligenceData(BaseModel):
    coverage: str = Field("MULTI-SOURCE (3/4)", description="Overall source coverage")
    sources: List[SourceDetail] = Field(default_factory=list)
    current_price: float = Field(4431.00)
    liquidity: List[LiquidityZone] = Field(default_factory=list)
    liquidity_status: str = Field("VERIFIED", description="VERIFIED | DATA NOT VERIFIED")
    retail_positioning: str = Field("LONG", description="LONG | SHORT | NEUTRAL | UNAVAILABLE")
    futures_liquidity: str = Field("HIGH", description="HIGH | MODERATE | LOW | UNAVAILABLE")
    futures_sell_wall: str = Field("HIGH", description="HIGH | MODERATE | LOW | UNAVAILABLE")
    divergence: str = Field("HIGH", description="HIGH | MODERATE | LOW | NONE | UNAVAILABLE")
    basis: str = Field("+$1.80", description="Basis string or UNAVAILABLE")
    basis_value: Optional[float] = Field(1.80)
    data_quality: str = Field("MODERATE", description="HIGH | MODERATE | LOW | UNAVAILABLE")
    update_timestamp: str = Field("")
