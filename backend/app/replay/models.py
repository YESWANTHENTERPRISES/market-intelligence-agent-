from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from app.replay.data_quality import DataQualityReport


class ReplayCandle(BaseModel):
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    timeframe: str = "5M"


class ReplayConfig(BaseModel):
    symbol: str = "XAUUSD"
    timeframe: str = "5M"
    start_timestamp: Optional[str] = None
    end_timestamp: Optional[str] = None
    initial_balance: float = 10000.0
    risk_per_trade_pct: float = 1.0
    min_rr: float = 1.5
    expiry_candles: int = 48  # Maximum candles to hold before expiring an un-triggered or pending trade
    intrabar_resolution: str = "CONSERVATIVE"  # "CONSERVATIVE" (marks AMBIGUOUS if both SL & TP touched) or "LTF"
    enable_dom: bool = True
    enable_levels: bool = True
    enable_context: bool = True
    is_real_data: bool = False
    dom_available: bool = False


class ScenarioEvent(BaseModel):
    timestamp: str
    symbol: str
    scenario: str
    direction: str
    state: str  # FORMING, CONFIRMATION_REQUIRED, CONFIRMED
    price: float
    score: int
    confidence: int
    trigger_level: Optional[float] = None
    evidence: List[str] = []


class TradePlanEvent(BaseModel):
    trade_id: str
    timestamp: str
    symbol: str
    scenario: str
    direction: str
    state: str  # VALID, INVALID, WAIT
    entry_price: Optional[float] = None
    sl_price: Optional[float] = None
    tp1_price: Optional[float] = None
    tp2_price: Optional[float] = None
    tp3_price: Optional[float] = None
    rr: float = 0.0
    tradeability_score: int = 0
    confidence: int = 0
    reasons: List[str] = []


class TradeOutcome(BaseModel):
    trade_id: str
    timestamp: str
    symbol: str
    scenario: str
    direction: str
    entry_price: float
    sl_price: float
    tp1_price: float
    tp2_price: Optional[float] = None
    tp3_price: Optional[float] = None
    planned_rr: float
    outcome: str  # TP1_HIT, TP2_HIT, TP3_HIT, SL_HIT, INVALIDATED, EXPIRED, AMBIGUOUS
    exit_timestamp: str
    exit_price: float
    duration_candles: int
    duration_minutes: int
    mae: float  # Maximum Adverse Excursion in price points
    mae_r: float  # MAE in Risk units
    mfe: float  # Maximum Favorable Excursion in price points
    mfe_r: float  # MFE in Risk units
    realized_rr: float
    pnl_r: float  # Profit/Loss in R-multiples (-1.0 for SL, +RR for TP)
    pnl_dollars: float = 0.0
    session: str = "UNKNOWN"
    volatility: str = "NORMAL"
    confidence: int = 0


class PerformanceMetrics(BaseModel):
    total_setups: int = 0
    confirmed_setups: int = 0
    valid_trades: int = 0
    invalid_trades: int = 0
    wait_scenarios: int = 0
    wins: int = 0
    losses: int = 0
    breakeven: int = 0
    win_rate: float = 0.0
    loss_rate: float = 0.0
    avg_rr: float = 0.0
    median_rr: float = 0.0
    realized_rr: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    max_drawdown_pct: float = 0.0
    max_drawdown_r: float = 0.0
    max_losing_streak: int = 0
    avg_mae: float = 0.0
    avg_mfe: float = 0.0
    tp1_hit_rate: float = 0.0
    tp2_hit_rate: float = 0.0
    tp3_hit_rate: float = 0.0
    avg_time_to_tp_mins: float = 0.0
    avg_time_to_sl_mins: float = 0.0
    long_performance: Dict[str, Any] = {}
    short_performance: Dict[str, Any] = {}
    session_performance: Dict[str, Any] = {}
    volatility_performance: Dict[str, Any] = {}
    regime_performance: Dict[str, Any] = {}


class ScenarioStats(BaseModel):
    scenario: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    avg_rr: float = 0.0
    realized_rr: float = 0.0
    sample_size: int = 0
    sample_status: str = "OK"  # OK, LOW_SAMPLE (<30), INSUFFICIENT_SAMPLE (<10)


class ConfidenceBin(BaseModel):
    bin_label: str  # e.g. "50-59", "60-69", "70-79", "80-89", "90-100"
    min_conf: int
    max_conf: int
    total_trades: int = 0
    wins: int = 0
    actual_win_rate: float = 0.0
    expectancy: float = 0.0
    is_calibrated: bool = False


class AblationResult(BaseModel):
    test_id: str  # A, B, C, D, E
    test_name: str
    description: str
    total_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    max_drawdown_pct: float = 0.0
    realized_rr: float = 0.0
    status: str = "COMPLETED"  # COMPLETED, DOM_ABLATION_UNAVAILABLE


class WalkForwardPartition(BaseModel):
    partition_name: str  # TRAIN, VALIDATION, OUT_OF_SAMPLE
    start_date: str
    end_date: str
    total_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    max_drawdown_pct: float = 0.0


class WalkForwardResult(BaseModel):
    partitions: List[WalkForwardPartition] = []
    in_sample_expectancy: float = 0.0
    out_of_sample_expectancy: float = 0.0
    stability_index: float = 0.0  # OOS expectancy / IS expectancy ratio


class MonteCarloResult(BaseModel):
    iterations: int = 10000
    expected_drawdown_p50: float = 0.0
    expected_drawdown_p95: float = 0.0
    expected_drawdown_p99: float = 0.0
    median_losing_streak: int = 0
    p95_losing_streak: int = 0
    worst_losing_streak: int = 0
    risk_of_ruin_pct: float = 0.0  # Probability of hitting >= 20% drawdown
    equity_curves_sample: List[List[float]] = []


class TradeFunnelCounts(BaseModel):
    scenario_generated: int = 0
    scenario_confirmation_passed: int = 0
    scenario_confirmation_failed: int = 0
    risk_validation_reached: int = 0
    entry_valid: int = 0
    sl_valid: int = 0
    tp_available: int = 0
    rr_valid: int = 0
    trade_valid: int = 0


class RRDistribution(BaseModel):
    min_rr: float = 0.0
    max_rr: float = 0.0
    mean_rr: float = 0.0
    median_rr: float = 0.0
    p10: float = 0.0
    p25: float = 0.0
    p50: float = 0.0
    p75: float = 0.0
    p90: float = 0.0
    buckets: Dict[str, int] = Field(default_factory=lambda: {
        "< 0.5": 0,
        "0.5-1.0": 0,
        "1.0-1.5": 0,
        "1.5-2.0": 0,
        "2.0-3.0": 0,
        "3.0+": 0
    })


class RiskEngineAudit(BaseModel):
    entry_available: int = 0
    sl_available: int = 0
    tp1_available: int = 0
    tp2_available: int = 0
    tp3_available: int = 0
    invalid_entry_geometry: int = 0
    invalid_sl_geometry: int = 0
    rr_below_1_5: int = 0
    extreme_volatility: int = 0
    canonical_price_failure: int = 0
    missing_confirmation: int = 0


class TargetAvailabilityAudit(BaseModel):
    missing_trigger_level_pct: float = 0.0
    missing_invalidation_level_pct: float = 0.0
    missing_opposing_liquidity_pct: float = 0.0
    missing_tp1_pct: float = 0.0
    missing_tp2_pct: float = 0.0
    missing_tp3_pct: float = 0.0


class DataQualityMatrix(BaseModel):
    canonical_price_exists_pct: float = 100.0
    market_context_exists_pct: float = 100.0
    important_levels_exist_pct: float = 100.0
    atr_exists_pct: float = 100.0
    session_exists_pct: float = 100.0
    volatility_exists_pct: float = 100.0


class DOMDependencyReport(BaseModel):
    dom_available: bool = False
    dom_independent_rejections: int = 0
    dom_dependent_rejections: int = 0
    dom_blocking_trades_pct: float = 0.0
    status: str = "DOM_DEPENDENCY_BLOCKING_TRADES"


class TimeDistribution(BaseModel):
    by_session: Dict[str, int] = Field(default_factory=lambda: {
        "Asia": 0,
        "London": 0,
        "London/New York overlap": 0,
        "New York": 0
    })
    by_date: Dict[str, int] = Field(default_factory=dict)


class ScenarioRejectionAudit(BaseModel):
    scenario_name: str
    total_generated: int = 0
    confirmed: int = 0
    rejected: int = 0
    rejection_reasons: Dict[str, int] = Field(default_factory=dict)
    rejection_percentages: Dict[str, float] = Field(default_factory=dict)


class BottleneckAuditReport(BaseModel):
    funnel: TradeFunnelCounts = Field(default_factory=TradeFunnelCounts)
    top_rejection_reasons: List[Dict[str, Any]] = []
    short_pullback_audit: ScenarioRejectionAudit = Field(default_factory=lambda: ScenarioRejectionAudit(scenario_name="SHORT_PULLBACK"))
    long_pullback_audit: ScenarioRejectionAudit = Field(default_factory=lambda: ScenarioRejectionAudit(scenario_name="LONG_PULLBACK"))
    risk_engine_audit: RiskEngineAudit = Field(default_factory=RiskEngineAudit)
    rr_distribution: RRDistribution = Field(default_factory=RRDistribution)
    confirmation_latency: Dict[str, Any] = Field(default_factory=lambda: {"status": "NO_CONFIRMED_SCENARIOS", "confirmed_scenarios": []})
    target_availability: TargetAvailabilityAudit = Field(default_factory=TargetAvailabilityAudit)
    data_quality_matrix: DataQualityMatrix = Field(default_factory=DataQualityMatrix)
    dom_dependency: DOMDependencyReport = Field(default_factory=DOMDependencyReport)
    time_distribution: TimeDistribution = Field(default_factory=TimeDistribution)
    classification: Dict[str, Any] = Field(default_factory=lambda: {
        "expected_strategy_filtering": 0,
        "data_availability_limitation": 0,
        "overly_restrictive_rule": 0,
        "implementation_bug": 0
    })
    conclusions: Dict[str, Any] = Field(default_factory=lambda: {
        "primary_bottleneck": "NO_CONFIRMED_SCENARIOS",
        "secondary_bottleneck": "RR_BELOW_MINIMUM",
        "strategy_logic_bug": "NO",
        "parameter_optimization_justified": "YES"
    })


class ReplayReport(BaseModel):
    symbol: str = "XAUUSD"
    timeframe: str = "5M"
    start_timestamp: str = ""
    end_timestamp: str = ""
    total_candles_processed: int = 0
    dataset_hash: str = ""
    config_hash: str = ""
    code_version: str = "v1.0.0-step7.5"
    engine_version: str = "7.5.0-baseline"
    baseline_status: str = "UNPROVEN"  # PROFITABLE, UNPROVEN, NEGATIVE
    dom_status: str = "UNAVAILABLE"  # AVAILABLE, UNAVAILABLE
    data_quality_report: Optional[DataQualityReport] = None
    metrics: PerformanceMetrics = Field(default_factory=PerformanceMetrics)
    scenario_statistics: List[ScenarioStats] = []
    confidence_calibration: List[ConfidenceBin] = []
    scenario_events: List[ScenarioEvent] = []
    trade_plans: List[TradePlanEvent] = []
    trade_outcomes: List[TradeOutcome] = []
    ablation_results: List[AblationResult] = []
    walk_forward_results: Optional[WalkForwardResult] = None
    monte_carlo_results: Optional[MonteCarloResult] = None
    bottleneck_audit_report: Optional[BottleneckAuditReport] = None


