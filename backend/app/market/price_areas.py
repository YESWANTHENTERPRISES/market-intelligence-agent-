import time
from typing import Dict, List, Any

class PriceAreaClusterer:
    def __init__(self, atr_multiplier: float = 0.15):
        self.atr_multiplier = atr_multiplier

    def cluster_candidates(
        self,
        raw_candidates: List[Dict[str, Any]],
        current_price: float,
        atr: float,
        decimal_places: int = 2
    ) -> List[Dict[str, Any]]:
        """
        Clusters raw level candidates into unified price zones using ATR-relative distance.
        cluster_distance = ATR(14) * 0.15
        A zone contains zone_low, zone_high, and midpoint.
        """
        if not raw_candidates:
            return []

        cluster_distance = atr * self.atr_multiplier
        if cluster_distance <= 0:
            cluster_distance = current_price * 0.0010

        # Sort candidates by price ascending
        sorted_candidates = sorted(raw_candidates, key=lambda x: x["price"])

        clusters: List[List[Dict[str, Any]]] = []
        current_cluster: List[Dict[str, Any]] = []

        for cand in sorted_candidates:
            if not current_cluster:
                current_cluster.append(cand)
            else:
                cluster_avg = sum(c["price"] for c in current_cluster) / len(current_cluster)
                if abs(cand["price"] - cluster_avg) <= cluster_distance:
                    current_cluster.append(cand)
                else:
                    clusters.append(current_cluster)
                    current_cluster = [cand]

        if current_cluster:
            clusters.append(current_cluster)

        zones = []
        fmt = f"{{:.{decimal_places}f}}"

        for cl in clusters:
            prices = [c["price"] for c in cl]
            min_p = min(prices)
            max_p = max(prices)

            # Enforce minimum zone width equal to ATR * 0.05 so single exact levels have a clear range
            min_width = atr * 0.05
            if (max_p - min_p) < min_width:
                half_w = min_width / 2.0
                min_p = min_p - half_w
                max_p = max_p + half_w

            zone_low = round(min_p, decimal_places)
            zone_high = round(max_p, decimal_places)
            midpoint = round((zone_low + zone_high) / 2.0, decimal_places)

            # Combine evidence, timeframes, and sources
            evidence_set = []
            timeframes_set = []
            sources_set = []
            cand_types = []

            for c in cl:
                tf = c.get("timeframe")
                if tf and tf not in timeframes_set:
                    timeframes_set.append(tf)

                src = c.get("source")
                if src and src not in sources_set:
                    sources_set.append(src)

                c_type = c.get("type", "LEVEL")
                if c_type not in cand_types:
                    cand_types.append(c_type)

                for ev in c.get("evidence", []):
                    if ev not in evidence_set:
                        evidence_set.append(ev)

            # Determine initial classification
            classification = self._classify_initial_zone(
                midpoint=midpoint,
                current_price=current_price,
                cand_types=cand_types,
                evidence=evidence_set
            )

            zone_str = f"{fmt.format(zone_low)}–{fmt.format(zone_high)}"

            zones.append({
                "zone": zone_str,
                "zone_low": zone_low,
                "zone_high": zone_high,
                "midpoint": midpoint,
                "classification": classification,
                "timeframes": timeframes_set,
                "sources": sources_set,
                "types": cand_types,
                "raw_candidates": cl,
                "evidence": evidence_set,
                "status": "ACTIVE",
                "last_confirmed_at": time.time()
            })

        return zones

    def _classify_initial_zone(
        self,
        midpoint: float,
        current_price: float,
        cand_types: List[str],
        evidence: List[str]
    ) -> str:
        """
        Classifies a zone based on candidate types, breakout states, and price location.
        """
        if "BROKEN_RESISTANCE" in cand_types:
            return "BROKEN_RESISTANCE"
        if "BROKEN_SUPPORT" in cand_types:
            return "BROKEN_SUPPORT"

        if midpoint >= current_price:
            return "RESISTANCE"
        else:
            return "SUPPORT"

    def evaluate_level_transitions(
        self,
        zone: Dict[str, Any],
        current_price: float,
        atr: float,
        confirmed_retest: bool = False
    ) -> Dict[str, Any]:
        """
        Handles transition of broken levels.
        Resistance breakout -> WEAKENING -> BROKEN
        If BROKEN_RESISTANCE receives confirmed retest defense -> transition to SUPPORT.
        Support breakdown -> WEAKENING -> BROKEN
        If BROKEN_SUPPORT receives confirmed retest defense -> transition to RESISTANCE.
        """
        classification = zone.get("classification", "")
        status = zone.get("status", "ACTIVE")

        # Decisive break threshold
        break_threshold = atr * 0.50

        if classification == "RESISTANCE" and status == "ACTIVE":
            if current_price > (zone["zone_high"] + break_threshold):
                zone["status"] = "BROKEN"
                zone["classification"] = "BROKEN_RESISTANCE"
                zone["evidence"].append("Decisive upside breakout confirmed")

        elif classification == "SUPPORT" and status == "ACTIVE":
            if current_price < (zone["zone_low"] - break_threshold):
                zone["status"] = "BROKEN"
                zone["classification"] = "BROKEN_SUPPORT"
                zone["evidence"].append("Decisive downside breakdown confirmed")

        elif classification == "BROKEN_RESISTANCE" and status == "BROKEN" and confirmed_retest:
            if current_price >= zone["zone_low"]:
                zone["classification"] = "SUPPORT"
                zone["status"] = "ACTIVE"
                zone["evidence"].append("Broken resistance confirmed converted to Support")

        elif classification == "BROKEN_SUPPORT" and status == "BROKEN" and confirmed_retest:
            if current_price <= zone["zone_high"]:
                zone["classification"] = "RESISTANCE"
                zone["status"] = "ACTIVE"
                zone["evidence"].append("Broken support confirmed converted to Resistance")

        return zone

price_area_clusterer = PriceAreaClusterer()
