from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field, ConfigDict

class TimeframePressure(BaseModel):
    buyers: int = Field(..., description="Buyer strength score 0-100")
    sellers: int = Field(..., description="Seller strength score 0-100")
    confidence: float = Field(..., description="Confidence score 0.0-1.0")

class DirectionalPressure(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    tf_4h: TimeframePressure = Field(..., alias="4H")
    tf_1h: TimeframePressure = Field(..., alias="1H")
    tf_30m: TimeframePressure = Field(..., alias="30M")
    tf_15m: TimeframePressure = Field(..., alias="15M")
    tf_5m: TimeframePressure = Field(..., alias="5M")

class Fundamentals(BaseModel):
    status: str = Field("AVAILABLE", description="AVAILABLE | DELAYED | UNAVAILABLE")
    bias: str = Field("BULLISH", description="BULLISH | BEARISH | NEUTRAL")
    confidence: int = Field(78, description="Percentage confidence 0-100")
    drivers: List[str] = Field(default_factory=list, description="Main market drivers")

class NewsItem(BaseModel):
    title: str
    impact: str = Field("HIGH IMPACT", description="HIGH IMPACT | MEDIUM IMPACT | LOW IMPACT")
    time_gmt: str
    minutes_until: Optional[int] = None

class SessionInfo(BaseModel):
    name: str = Field("London", description="Active market session")
    volatility: str = Field("HIGH", description="HIGH | MODERATE | LOW")
    relevance: str = Field("HIGH", description="Session relevance")

class CorrelationItem(BaseModel):
    symbol: str
    direction: str = Field("BEARISH", description="BEARISH | BULLISH | NEUTRAL")
    arrow: str = Field("↓", description="↓ or ↑")
    status: str = Field("LIVE", description="LIVE | DELAYED | UNAVAILABLE")

class Correlations(BaseModel):
    dxy: CorrelationItem
    us10y: CorrelationItem

class LargeActivity(BaseModel):
    status: str = Field("AVAILABLE", description="AVAILABLE | UNAVAILABLE")
    direction: str = Field("SELLING", description="SELLING | BUYING | NEUTRAL")
    zone: str = Field("4435.9–4438.6", description="Price zone")

class OrderFlow(BaseModel):
    status: str = Field("TICK_PROXY_ONLY", description="TICK_PROXY_ONLY | REAL_VOLUME | UNAVAILABLE")
    buying_pressure: str = Field("MODERATE", description="HIGH | MODERATE | LOW")
    delta: int = Field(12242, description="Cumulative volume/tick delta")
    proxy_label: str = Field("Tick Proxy", description="Explicit labeling")

class SourceDetail(BaseModel):
    name: str
    status: str
    freshness: str
    included_in_aggregation: bool

class LiquidityZone(BaseModel):
    price_range: str
    side: str
    impact: str
    score: float = 0.0

class DOMIntelligence(BaseModel):
    coverage: str = Field("MULTI-SOURCE (3/4)", description="Overall source coverage")
    sources: List[SourceDetail] = Field(default_factory=lambda: [
        SourceDetail(name="COMEX", status="DELAYED 15M", freshness="DELAYED 15M", included_in_aggregation=True),
        SourceDetail(name="OANDA", status="LIVE", freshness="LIVE", included_in_aggregation=True),
        SourceDetail(name="DUKASCOPY", status="LIVE", freshness="LIVE", included_in_aggregation=True)
    ])
    current_price: float = Field(4431.00)
    liquidity: List[LiquidityZone] = Field(default_factory=lambda: [
        LiquidityZone(price_range="4438–4440", side="ASK LIQUIDITY", impact="HIGH", score=65.0),
        LiquidityZone(price_range="4434–4436", side="BID LIQUIDITY", impact="MODERATE", score=45.0)
    ])
    liquidity_status: str = Field("VERIFIED", description="VERIFIED | DATA NOT VERIFIED")
    retail_positioning: str = Field("LONG", description="LONG | SHORT | NEUTRAL | UNAVAILABLE")
    futures_liquidity: str = Field("HIGH", description="HIGH | MODERATE | LOW | UNAVAILABLE")
    futures_sell_wall: str = Field("HIGH", description="HIGH | MODERATE | LOW | UNAVAILABLE")
    divergence: str = Field("HIGH", description="HIGH | MODERATE | LOW | NONE | UNAVAILABLE")
    basis: str = Field("+$1.80", description="Basis string or UNAVAILABLE")
    basis_value: Optional[float] = Field(1.80)
    data_quality: str = Field("MODERATE", description="HIGH | MODERATE | LOW | UNAVAILABLE")
    update_timestamp: str = Field("")
    
    # Backward compatibility aliases
    status: str = Field("PARTIAL", description="LIVE | PARTIAL | UNAVAILABLE")
    source: str = Field("MULTI-SOURCE (3/4)", description="Source description")
    bid_depth: int = Field(1240)
    ask_depth: int = Field(980)
    imbalance_pct: float = Field(26.5)
    imbalance_side: str = Field("Bid", description="Bid | Ask")

class CurrencyItem(BaseModel):
    currency: str
    score: int = Field(..., description="0 to 100 strength score")

class COTData(BaseModel):
    status: str = Field("WEEKLY", description="WEEKLY | UNAVAILABLE")
    commercial_bias: str = Field("SHORT", description="SHORT | LONG | NEUTRAL")
    non_commercial_bias: str = Field("LONG", description="SHORT | LONG | NEUTRAL")
    percentile_52w: int = Field(87)

class FedProbabilities(BaseModel):
    status: str = Field("15MIN DELAYED", description="15MIN DELAYED | LIVE | UNAVAILABLE")
    no_change_pct: int = Field(23)
    cut_25bps_pct: int = Field(61)
    cut_50bps_pct: int = Field(16)

class MarketRegime(BaseModel):
    regime: str = Field("TRENDING", description="TRENDING | RANGING | BREAKOUT | HIGH_VOLATILITY")
    adx: float = Field(34.2)
    atr_status: str = Field("ABOVE AVERAGE")
    implication: str = Field("Run winners, avoid counter-trend scalps")

class SeasonalityData(BaseModel):
    month: str = Field("August")
    avg_return_pct: float = Field(1.2)
    win_rate_pct: int = Field(65)
    disclaimer: str = Field("Historical seasonality — not a forward guarantee")

class LiquidityPools(BaseModel):
    buy_side_range: str = Field("4438–4442")
    buy_side_impact: str = Field("HIGH")
    sell_side_range: str = Field("4418–4422")
    sell_side_impact: str = Field("MODERATE")

class LiquidityDetail(BaseModel):
    type: str = Field("BUY_SIDE", description="BUY_SIDE | SELL_SIDE | NONE")
    strength: str = Field("HIGH", description="HIGH | MODERATE | LOW")

class DOMDetail(BaseModel):
    confluence: str = Field("HIGH", description="HIGH | MODERATE | LOW")
    sources: List[str] = Field(default_factory=list)

class LevelDetail(BaseModel):
    zone: str = Field("4438–4440")
    midpoint: float = Field(4439.0)
    classification: str = Field("RESISTANCE", description="RESISTANCE | SUPPORT | BUY_SIDE_LIQUIDITY | SELL_SIDE_LIQUIDITY | BROKEN_RESISTANCE | BROKEN_SUPPORT")
    importance: str = Field("VERY_HIGH", description="VERY_HIGH | HIGH | MODERATE | LOW | DO_NOT_DISPLAY")
    confluence_score: int = Field(87, description="0-100 score")
    distance: float = Field(8.0)
    distance_atr: float = Field(1.15)
    timeframes: List[str] = Field(default_factory=lambda: ["1H", "30M"])
    evidence: List[str] = Field(default_factory=list)
    liquidity: LiquidityDetail = Field(default_factory=LiquidityDetail)
    dom: DOMDetail = Field(default_factory=DOMDetail)
    status: str = Field("ACTIVE", description="ACTIVE | WEAKENING | BROKEN | INVALIDATED")

class DataQualityDetail(BaseModel):
    level: str = Field("MODERATE", description="HIGH | MODERATE | LOW | INSUFFICIENT")
    active_sources: int = Field(3)
    total_sources: int = Field(4)
    reason: str = Field("COMEX, OANDA, Dukascopy available")

class ImportantLevels(BaseModel):
    status: str = Field("AVAILABLE", description="AVAILABLE | INSUFFICIENT_DATA")
    support: List[Union[str, LevelDetail]] = Field(default_factory=list)
    resistance: List[Union[str, LevelDetail]] = Field(default_factory=list)
    liquidity: List[Union[str, LevelDetail]] = Field(default_factory=list)
    levels: List[LevelDetail] = Field(default_factory=list)
    data_quality: Optional[DataQualityDetail] = None

class AIMarketView(BaseModel):
    current: str = Field("Bullish while 4420 remains defended")
    continuation: str = Field("4442")
    retracement: str = Field("4420–4424")
    invalidation: str = Field("4417")
    supporting_evidence: List[str] = Field(default_factory=lambda: [
        "4H structure bullish",
        "DXY bearish",
        "Positive tick delta"
    ])
    conflicting_evidence: List[str] = Field(default_factory=lambda: [
        "5M bearish momentum",
        "Resistance nearby",
        "Elevated speculative longs"
    ])

class PreNewsLockout(BaseModel):
    active: bool = Field(False)
    event_title: Optional[str] = None
    time_remaining_str: Optional[str] = None
    forecast: Optional[str] = None
    previous: Optional[str] = None

class DataStatus(BaseModel):
    market: str = "LIVE"
    news: str = "LIVE"
    fundamentals: str = "DELAYED"
    dom: str = "PARTIAL"
    order_flow: str = "TICK PROXY"
    dxy: str = "DELAYED"
    us10y: str = "DELAYED"
    cot: str = "WEEKLY"
    fed: str = "DELAYED"
    currency: str = "LIVE"

class MarketIntelligenceResponse(BaseModel):
    symbol: str = Field("XAUUSD")
    timeframe: str = Field("5M")
    current_price: float = Field(4431.00)
    
    overall_bias: str = Field("SELL", description="BUY | SELL | NEUTRAL")
    overall_confidence: int = Field(45, description="0-100%")
    
    directional_pressure: DirectionalPressure
    fundamentals: Fundamentals
    news: List[NewsItem] = Field(default_factory=list)
    session: SessionInfo
    correlations: Correlations
    large_activity: LargeActivity
    orderflow: OrderFlow
    dom: DOMIntelligence
    currency_strength: List[CurrencyItem] = Field(default_factory=list)
    cot: COTData
    fed_probabilities: FedProbabilities
    market_regime: MarketRegime
    seasonality: SeasonalityData
    liquidity: LiquidityPools
    important_levels: ImportantLevels
    ai_market_view: AIMarketView
    pre_news_lockout: PreNewsLockout
    data_status: DataStatus
    data_quality: str = Field("MODERATE", description="HIGH | MODERATE | LOW")
