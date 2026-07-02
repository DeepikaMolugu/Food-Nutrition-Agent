# ruff: noqa
# Food Nutrition Agent — Multi-Agent Workflow (ADK 2.2)
# Track: Agents for Good

import json
import re
import datetime
import asyncio
import logging
from typing import Any, AsyncGenerator, ClassVar

from google.adk.agents import LlmAgent
from google.adk.tools import AgentTool
from google.adk.tools.mcp_tool import MCPToolset, StdioConnectionParams
from google.adk.workflow import BaseNode
from google.adk.agents.context import Context
from google.adk.events import Event
from google.genai.errors import ServerError
from mcp.client.stdio import StdioServerParameters

from app.config import config

logger = logging.getLogger(__name__)

from app.config import config

# ─────────────────────────────────────────────────────────────────────────────
# Security Checkpoint Tool (registered as a callable tool for the orchestrator)
# ─────────────────────────────────────────────────────────────────────────────

INJECTION_KEYWORDS = [
    "ignore previous", "ignore all", "disregard", "forget instructions",
    "you are now", "act as", "jailbreak", "system prompt", "override",
    "ignore your", "new instructions", "pretend you are",
]

PII_PATTERNS = {
    "email": r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    "phone": r"\b(\+\d{1,3}[\s\-]?)?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{4}\b",
    "ssn": r"\b\d{3}[\-\s]?\d{2}[\-\s]?\d{4}\b",
    "credit_card": r"\b(?:\d{4}[\s\-]?){3}\d{4}\b",
    "aadhar": r"\b\d{4}\s?\d{4}\s?\d{4}\b",
}


def run_security_check(user_input: str) -> str:
    """Scrubs PII, detects prompt injection, and writes a structured audit log.

    Always call this first before processing any user meal description.

    Args:
        user_input: The raw user message to check and sanitize.

    Returns:
        A JSON string with 'verdict' (PASS or BLOCKED), 'sanitized_input', and 'audit_log'.
    """
    audit_log = {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "original_length": len(user_input),
        "pii_found": [],
        "injection_detected": False,
        "severity": "INFO",
        "action": "PASS",
    }

    sanitized = user_input

    # --- PII Scrubbing ---
    for pii_type, pattern in PII_PATTERNS.items():
        matches = re.findall(pattern, sanitized)
        if matches:
            audit_log["pii_found"].append(pii_type)
            sanitized = re.sub(pattern, f"[REDACTED_{pii_type.upper()}]", sanitized)
            audit_log["severity"] = "WARNING"

    # --- Prompt Injection Detection ---
    lower_input = user_input.lower()
    for keyword in INJECTION_KEYWORDS:
        if keyword in lower_input:
            audit_log["injection_detected"] = True
            audit_log["severity"] = "CRITICAL"
            audit_log["action"] = "BLOCKED"
            print(f"[SECURITY_EVENT] {json.dumps(audit_log)}")
            return json.dumps({
                "verdict": "BLOCKED",
                "sanitized_input": None,
                "audit_log": audit_log,
                "message": "Potential prompt injection detected. Please describe your meal normally.",
            })

    print(f"[AUDIT_LOG] {json.dumps(audit_log)}")
    return json.dumps({
        "verdict": "PASS",
        "sanitized_input": sanitized,
        "audit_log": audit_log,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Sub-Agent 1: Vision Analyst
# ─────────────────────────────────────────────────────────────────────────────

vision_agent = LlmAgent(
    name="vision_analyst",
    model=config.model,
    instruction="""You are an expert food recognition specialist.

Given a meal description, identify:
1. All food items present in the meal
2. Estimated portion sizes (e.g., "1 cup", "2 pieces", "150g")
3. Cooking method (fried, boiled, grilled, raw, baked, etc.)
4. Cuisine type (Indian, Italian, American, Chinese, etc.)
5. Meal type (breakfast / lunch / dinner / snack)

Respond with a clear structured list. Be specific about quantities.
Example: "2 samosas (fried, ~100g each), 1 cup masala chai (250ml), Indian snack"

Always respond with the food identification even if approximate.""",
    output_key="identified_foods",
)

# ─────────────────────────────────────────────────────────────────────────────
# Sub-Agent 2: Nutrition Analyst (uses MCP tools)
# ─────────────────────────────────────────────────────────────────────────────

nutrition_agent = LlmAgent(
    name="nutrition_analyst",
    model=config.model,
    instruction="""You are a certified nutritionist and dietitian.

You will receive the identified food items from the context. Your job:
1. Use get_nutrition_data tool to look up each food item's nutritional values
2. Use get_healthier_alternatives tool to find better options for high-calorie items
3. Calculate total meal calories, protein, carbs, fat, fiber
4. Assign a health rating: 🟢 Green (balanced), 🟡 Yellow (moderate), 🔴 Red (high calorie/fat)

Provide a clear summary:
- Total calories and macros for the meal
- Health rating with brief reason
- 3 healthier alternatives (from tool results)

Be specific and encouraging.""",
    tools=[
        MCPToolset(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(
                    command="python",
                    args=["app/mcp_server.py"],
                )
            )
        )
    ],
    output_key="nutrition_analysis",
)

# ─────────────────────────────────────────────────────────────────────────────
# Sub-Agent 3: Diet Planner (uses MCP tools)
# ─────────────────────────────────────────────────────────────────────────────

diet_planner_agent = LlmAgent(
    name="diet_planner",
    model=config.model,
    instruction="""You are a personalized diet planning expert.

You will receive nutrition analysis from context. Your job:
1. Use get_daily_summary tool to check today's remaining calorie budget
2. Use generate_diet_plan tool to create meal suggestions for remaining budget
3. Suggest specific, practical meals for the rest of the day
4. Give 3 meal prep tips based on the user's eating pattern

Provide:
- Today's remaining calorie budget
- Specific meal suggestions with portions for remaining meals
- One practical tip for the user's health goals

Be practical and specific — name actual dishes, not vague categories.""",
    tools=[
        MCPToolset(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(
                    command="python",
                    args=["app/mcp_server.py"],
                )
            )
        )
    ],
    output_key="diet_plan",
)

# ─────────────────────────────────────────────────────────────────────────────
# Sub-Agent 4: Nutrition Tracker (uses MCP tools)
# ─────────────────────────────────────────────────────────────────────────────

tracker_agent = LlmAgent(
    name="nutrition_tracker",
    model=config.model,
    instruction="""You are a nutrition tracking specialist.

You will receive nutrition analysis from context. Your job:
1. Use log_meal tool to log the current meal (calories, protein, carbs, fat, fiber)
2. Use get_daily_summary tool to retrieve today's full nutrition summary
3. Show progress toward daily goals (2000 cal, 50g protein, 250g carbs, 65g fat, 25g fiber)
4. Give a motivational message and one actionable suggestion

Report:
- ✅ Logged: [meal name] — [calories] cal
- 📊 Today's totals: [calories] / 2000 cal ([X]%)
- 💪 [Motivational message + next step]

Be encouraging and specific.""",
    tools=[
        MCPToolset(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(
                    command="python",
                    args=["app/mcp_server.py"],
                )
            )
        )
    ],
    output_key="tracking_summary",
)

# ─────────────────────────────────────────────────────────────────────────────
# Root Orchestrator Agent
# ─────────────────────────────────────────────────────────────────────────────

_root_orchestrator = LlmAgent(
    name="food_nutrition_orchestrator",
    model=config.model,
    instruction="""You are the Food Nutrition AI Orchestrator — a friendly, expert nutrition assistant.

When a user sends a message, follow these steps in order:

STEP 1 — SECURITY: Call run_security_check with the user's message. 
  - If verdict is "BLOCKED": Apologize politely and ask them to describe their meal normally. Stop here.
  - If verdict is "PASS": Continue with the sanitized input.

STEP 2 — IDENTIFY FOOD: Call vision_analyst with the user's meal description to identify all food items and portions.

STEP 3 — ANALYZE NUTRITION: Call nutrition_analyst to get calorie counts, macros, health rating, and alternatives.

STEP 4 — PLAN DIET: Call diet_planner to get remaining-day meal suggestions and tips.

STEP 5 — TRACK & LOG: Call nutrition_tracker to log the meal and show daily progress.

STEP 6 — SUMMARIZE: Present a complete, friendly response with:
  🍽️ **Meal Identified**: [what was detected]
  📊 **Nutrition Breakdown**: [calories, protein, carbs, fat]  
  💚 **Health Rating**: [Green/Yellow/Red + reason]
  🥗 **Healthier Alternatives**: [3 specific options]
  📅 **Rest of Today**: [meal suggestions for remaining calories]
  📈 **Daily Progress**: [running totals + % of goals]

Special cases:
- If user asks "show my progress" or "what did I eat today" — skip steps 2-4, just call nutrition_tracker.
- If user asks for a diet plan — skip steps 2, call diet_planner after nutrition check.
- Always be warm, encouraging, and educational.""",
    tools=[
        run_security_check,
        AgentTool(agent=vision_agent),
        AgentTool(agent=nutrition_agent),
        AgentTool(agent=diet_planner_agent),
        AgentTool(agent=tracker_agent),
    ],
)

class RetryWrapperNode(BaseNode):
    target_node: BaseNode
    _cache: ClassVar[dict[str, list[Any]]] = {}
    _locks: ClassVar[dict[str, asyncio.Event]] = {}

    def __init__(self, target_node: BaseNode):
        super().__init__(
            name=f"{target_node.name}_retry_wrapper",
            target_node=target_node
        )

    def _get_cache_key(self, node_input: Any) -> str:
        try:
            if hasattr(node_input, "parts") and node_input.parts:
                parts_text = []
                for p in node_input.parts:
                    if hasattr(p, "text") and p.text:
                        parts_text.append(p.text)
                    elif isinstance(p, dict) and "text" in p:
                        parts_text.append(p["text"])
                return " ".join(parts_text).strip().lower()
            elif isinstance(node_input, dict):
                return json.dumps(node_input, sort_keys=True).lower()
            return str(node_input).strip().lower()
        except Exception:
            return str(node_input).strip().lower()

    async def _run_impl(
        self,
        *,
        ctx: Context,
        node_input: Any,
    ) -> AsyncGenerator[Any, None]:
        key = self._get_cache_key(node_input)

        # Concurrency / Debounce Lock Check
        if key in self._locks:
            logger.info(f"Duplicate concurrent request for key: '{key}'. Waiting.")
            await self._locks[key].wait()
            if key in self._cache:
                for event in self._cache[key]:
                    yield event
                return

        # Cache Hit Check
        if key in self._cache:
            logger.info(f"Cache hit for key: '{key}'")
            for event in self._cache[key]:
                yield event
            return

        # Setup Concurrency Lock
        self._locks[key] = asyncio.Event()
        events_to_cache = []

        max_attempts = 5
        delays = [2, 4, 8, 16]

        try:
            for attempt in range(max_attempts):
                try:
                    if hasattr(ctx, "_output_value"):
                        ctx._output_value = None
                    async for event in self.target_node.run(ctx=ctx, node_input=node_input):
                        events_to_cache.append(event)
                        yield event
                    
                    # Store successfully completed runs in cache
                    self._cache[key] = events_to_cache
                    return
                except Exception as e:
                    events_to_cache.clear()
                    error_msg = str(e)
                    is_429 = "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg
                    is_503 = "503" in error_msg or (isinstance(e, ServerError) and e.code == 503)

                    if is_429:
                        is_daily = "PerDay" in error_msg or "limit: 20" in error_msg or "limit: 0" in error_msg or "current quota" in error_msg
                        if is_daily:
                            logger.error(f"Daily quota exhausted: {e}")
                            msg = "Your daily API quota has been exhausted. Please try again tomorrow or upgrade your plan."
                            yield msg
                            self._cache[key] = [msg]
                            return
                        else:
                            # Transient rate limit (RPM)
                            if attempt < max_attempts - 1:
                                yield f"Rate limit reached. Retrying in {delays[attempt]}s... (Attempt {attempt + 1}/{max_attempts})"
                                await asyncio.sleep(delays[attempt])
                            else:
                                logger.error(f"Failed after rate limit retries: {e}")
                                yield "Rate limit exceeded. Please try again in a few moments."
                                return
                    elif is_503:
                        if attempt < max_attempts - 1:
                            yield f"The AI model is busy. Retrying... (Attempt {attempt + 1}/{max_attempts})"
                            await asyncio.sleep(delays[attempt])
                        else:
                            logger.error(f"Failed after 503 retries: {e}")
                            yield "The AI service is currently experiencing high demand. Please try again in a few moments."
                            return
                    else:
                        raise
        finally:
            event_lock = self._locks.pop(key, None)
            if event_lock:
                event_lock.set()


root_agent = RetryWrapperNode(_root_orchestrator)
