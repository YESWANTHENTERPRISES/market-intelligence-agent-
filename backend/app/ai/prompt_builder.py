import re
from typing import Dict, List, Any, Tuple

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
            levels_str_list.append(
                f"- Zone: {lvl['zone']} | Classification: {lvl['classification']} | Importance: {lvl['importance']} | Confluence Score: {lvl['confluence_score']}/100 | Evidence: {', '.join(lvl['evidence'])}"
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

        # Find numbers in AI response that look like price levels (e.g. 4-digit numbers or decimals near price)
        # For XAUUSD / indices / crypto / forex, extract floating point numbers
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
            # REJECT IT as required by prompt section 32
            return False, f"REJECTED: Gemini generated unauthorized price level(s): {', '.join(unauthorized_prices)}", unauthorized_prices

        return True, ai_response_text, []

ai_prompt_builder = AIPromptBuilderAndValidator()
