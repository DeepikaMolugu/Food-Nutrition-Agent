# ruff: noqa
# Food Nutrition Agent — Multi-Agent Workflow (ADK 2.2)
# Track: Agents for Good

import json
import re
import datetime
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.tools import AgentTool
from google.adk.tools.mcp_tool import MCPToolset, StdioConnectionParams
from mcp.client.stdio import StdioServerParameters

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
                    command="uv",
                    args=["run", "python", "app/mcp_server.py"],
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
                    command="uv",
                    args=["run", "python", "app/mcp_server.py"],
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
                    command="uv",
                    args=["run", "python", "app/mcp_server.py"],
                )
            )
        )
    ],
    output_key="tracking_summary",
)

# ─────────────────────────────────────────────────────────────────────────────
# Root Orchestrator Agent
# ─────────────────────────────────────────────────────────────────────────────

root_agent = LlmAgent(
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
