import re
import logging
from typing import Dict, List, Any, Tuple, Optional
import httpx
from app.core.config import settings

logger = logging.getLogger("ai_prompt_builder")

class AIPromptBuilderAndValidator:
    def build_prompt_with_levels(
        self,
        symbol: str,
        current_price: float,
        important_levels_response: Dict[str, Any],
        overall_bias: str
    ) -> str:
        """
        Constructs a strict prompt for Gemini incorporating pre-calculated Important Levels.
        Injects explicit constraints preventing Gemini from inventing or altering price levels.
        """
        levels = important_levels_response.get("levels", [])
        
        levels_str_list = []
        for lvl in levels:
            zone = lvl.get('zone', 'N/A')
            classification = lvl.get('classification', 'N/A')
            importance = lvl.get('importance', 'N/A')
            score = lvl.get('confluence_score', 0)
            evidence = ', '.join(lvl.get('evidence', []))
            levels_str_list.append(
                f"- Zone: {zone} | Classification: {classification} | Importance: {importance} | Confluence Score: {score}/100 | Evidence: {evidence}"
            )

        formatted_levels = "\n".join(levels_str_list) if levels_str_list else "No validated levels available."

        prompt = f"""
YOU ARE AN AI MARKET REASONING ASSISTANT FOR REAL-TIME TRADING.

CURRENT MARKET DATA:
- Symbol: {symbol}
- Current Market Price: {current_price}
- Overall Bias: {overall_bias}

PRE-CALCULATED VALIDATED IMPORTANT LEVELS (DETERMINISTICALLY DERIVED):
{formatted_levels}

STRICT GEMINI RESTRICTIONS & RULES:
1. YOU ARE ONLY DOWNSTREAM OF THE DETERMINISTIC CALCULATIONS.
2. YOU MAY ONLY EXPLAIN AND INTERPRET THE VALIDATED PRICE LEVELS LISTED ABOVE.
3. YOU MAY NOT CREATE NEW PRICE LEVELS, MODIFY PRICES, MODIFY CONFLUENCE SCORES, OR INVENT SUPPORT/RESISTANCE/LIQUIDITY.
4. YOU MAY NOT CLAIM CERTAINTY (e.g. DO NOT SAY "Gold will definitely reach 4450" or "4438 will reject price").
5. USE CONDITIONAL SCENARIO LANGUAGE (e.g. "A sustained break above 4440 would weaken the resistance zone").
6. ANY PRICE LEVEL MENTIONED IN YOUR REASONING MUST MATCH AN EXACT VALIDATED ZONE OR MIDPOINT FROM THE INPUT LIST ABOVE.

TASK:
Provide exactly 2 to 3 concise bullet points for SUPPORTING EVIDENCE aligned with {overall_bias} bias,
and 1 to 2 concise bullet points for CONFLICTING EVIDENCE / RISKS.
Format:
SUPPORTING:
- ...
- ...
CONFLICTING:
- ...
"""
        return prompt

    def validate_ai_output(
        self,
        ai_response_text: str,
        validated_levels: List[Dict[str, Any]],
        current_price: float
    ) -> Tuple[bool, str, List[str]]:
        """
        Validates AI output against pre-calculated price levels.
        If Gemini returns a price level not present in the Important Levels input, REJECT IT.
        """
        if not ai_response_text:
            return True, "", []

        # Extract all valid numbers / zone ranges from validated levels
        valid_price_tokens = set()
        valid_ranges = []

        for lvl in validated_levels:
            zone_str = lvl.get("zone", "")
            mid = lvl.get("midpoint")

            if mid:
                valid_price_tokens.add(f"{mid:.2f}")
                valid_price_tokens.add(f"{mid:.1f}")
                valid_price_tokens.add(f"{mid:.0f}")

            if "–" in zone_str or "-" in zone_str:
                parts = re.split(r'[–-]', zone_str)
                if len(parts) == 2:
                    try:
                        p1 = float(parts[0])
                        p2 = float(parts[1])
                        valid_ranges.append((min(p1, p2), max(p1, p2)))
                        valid_price_tokens.add(parts[0].strip())
                        valid_price_tokens.add(parts[1].strip())
                    except ValueError:
                        pass

        # Also allow current price
        valid_price_tokens.add(f"{current_price:.2f}")

        # Find numbers in AI response that look like price levels
        potential_prices = re.findall(r'\b\d{1,6}(?:\.\d{1,4})?\b', ai_response_text)

        unauthorized_prices = []
        for p_str in potential_prices:
            try:
                p_val = float(p_str)
            except ValueError:
                continue

            # Ignore non-price numbers like scores (0-100), percentages, or timestamps
            if p_val <= 100.0 and current_price > 500.0:
                continue

            # Check if p_val matches current_price or falls within any validated zone range (with small 0.5% tolerance)
            matched = False
            if abs(p_val - current_price) / max(1.0, current_price) < 0.005:
                matched = True

            for r_low, r_high in valid_ranges:
                if (r_low - 1.0) <= p_val <= (r_high + 1.0):
                    matched = True
                    break

            if not matched:
                unauthorized_prices.append(p_str)

        if unauthorized_prices:
            return False, f"REJECTED: Gemini generated unauthorized price level(s): {', '.join(unauthorized_prices)}", unauthorized_prices

        return True, ai_response_text, []

    async def generate_ai_market_view(
        self,
        symbol: str,
        current_price: float,
        important_levels_response: Dict[str, Any],
        overall_bias: str,
        client: Optional[httpx.AsyncClient] = None
    ) -> Tuple[List[str], List[str]]:
        """
        Generates AI market view supporting and conflicting evidence using Gemini API if configured,
        or deterministically derives evidence from validated levels when API key is not present or on error.
        """
        validated_levels = important_levels_response.get("levels", [])

        # If Gemini API Key is configured and not placeholder, call Gemini API
        if settings.GEMINI_API_KEY and "your_" not in settings.GEMINI_API_KEY and len(settings.GEMINI_API_KEY) > 10:
            prompt = self.build_prompt_with_levels(symbol, current_price, important_levels_response, overall_bias)
            try:
                async_client = client or httpx.AsyncClient(timeout=8.0)
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={settings.GEMINI_API_KEY}"
                payload = {
                    "contents": [{
                        "parts": [{"text": prompt}]
                    }],
                    "generationConfig": {
                        "temperature": 0.2,
                        "maxOutputTokens": 300
                    }
                }
                res = await async_client.post(url, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        is_valid, validated_text, unauthorized = self.validate_ai_output(text, validated_levels, current_price)
                        if is_valid and validated_text:
                            # Parse SUPPORTING and CONFLICTING bullets
                            supporting = []
                            conflicting = []
                            target = None
                            for line in validated_text.splitlines():
                                line_clean = line.strip()
                                if "SUPPORTING" in line_clean.upper():
                                    target = supporting
                                elif "CONFLICTING" in line_clean.upper() or "RISK" in line_clean.upper():
                                    target = conflicting
                                elif line_clean.startswith(("-", "*", "•")) and target is not None:
                                    bullet = line_clean.lstrip("-*• ").strip()
                                    if bullet:
                                        target.append(bullet)
                            if supporting or conflicting:
                                return (
                                    supporting[:3] if supporting else [f"{overall_bias} structural alignment at {current_price}"],
                                    conflicting[:2] if conflicting else ["Monitor reaction at nearest zone"]
                                )
                        else:
                            logger.warning(f"[AI] Gemini output failed validation: {unauthorized}")
            except Exception as e:
                logger.warning(f"[AI] Gemini API execution failed: {e}")

        # Deterministic derivation from validated technical levels
        supporting_ev = []
        conflicting_ev = []

        if overall_bias == "BUY":
            support_lvls = [lvl for lvl in validated_levels if lvl.get("classification") in ["SUPPORT", "BROKEN_RESISTANCE"]]
            if support_lvls:
                top_s = support_lvls[0]
                supporting_ev.append(f"Holding above {top_s.get('zone', 'key support')} ({top_s.get('confluence_score', 65)}% confluence)")
            else:
                supporting_ev.append("Bullish momentum structure holding")
            
            resistance_lvls = [lvl for lvl in validated_levels if lvl.get("classification") in ["RESISTANCE", "BROKEN_SUPPORT"]]
            if resistance_lvls:
                top_r = resistance_lvls[0]
                conflicting_ev.append(f"Overhead resistance near {top_r.get('zone', 'supply zone')}")
            else:
                conflicting_ev.append("Check higher timeframe momentum decay")

        elif overall_bias == "SELL":
            resistance_lvls = [lvl for lvl in validated_levels if lvl.get("classification") in ["RESISTANCE", "BROKEN_SUPPORT"]]
            if resistance_lvls:
                top_r = resistance_lvls[0]
                supporting_ev.append(f"Capped below {top_r.get('zone', 'key resistance')} ({top_r.get('confluence_score', 65)}% confluence)")
            else:
                supporting_ev.append("Bearish momentum structure holding")

            support_lvls = [lvl for lvl in validated_levels if lvl.get("classification") in ["SUPPORT", "BROKEN_RESISTANCE"]]
            if support_lvls:
                top_s = support_lvls[0]
                conflicting_ev.append(f"Demand zone support near {top_s.get('zone', 'demand zone')}")
            else:
                conflicting_ev.append("Watch for potential bounce near support")
        else:
            supporting_ev.append(f"Price rotating within range around {current_price:.2f}")
            conflicting_ev.append("No directional breakout confirmed")

        return supporting_ev, conflicting_ev

ai_prompt_builder = AIPromptBuilderAndValidator()
