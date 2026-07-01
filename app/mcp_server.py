"""
Food Nutrition MCP Server
Provides 5 domain-specific tools for nutrition lookup, meal logging,
diet planning, goal tracking, and food substitution suggestions.
"""

import json
import datetime
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server import Server

app = Server("food-nutrition-mcp")

# ─────────────────────────────────────────────────────────────────────────────
# In-memory daily tracker (keyed by date)
# In production, replace with a persistent DB
# ─────────────────────────────────────────────────────────────────────────────

_daily_log: dict[str, list[dict]] = {}
_daily_goals = {
    "calories": 2000,
    "protein_g": 50,
    "carbs_g": 250,
    "fat_g": 65,
    "fiber_g": 25,
}

# ─────────────────────────────────────────────────────────────────────────────
# Nutrition database (simplified reference data)
# ─────────────────────────────────────────────────────────────────────────────

NUTRITION_DB = {
    "rice": {"calories_per_100g": 130, "protein_g": 2.7, "carbs_g": 28, "fat_g": 0.3, "fiber_g": 0.4},
    "dal": {"calories_per_100g": 116, "protein_g": 9, "carbs_g": 20, "fat_g": 0.4, "fiber_g": 8},
    "roti": {"calories_per_100g": 297, "protein_g": 10, "carbs_g": 60, "fat_g": 3.7, "fiber_g": 2.5},
    "chicken breast": {"calories_per_100g": 165, "protein_g": 31, "carbs_g": 0, "fat_g": 3.6, "fiber_g": 0},
    "salad": {"calories_per_100g": 20, "protein_g": 1.5, "carbs_g": 3.5, "fat_g": 0.2, "fiber_g": 2},
    "pizza": {"calories_per_100g": 266, "protein_g": 11, "carbs_g": 33, "fat_g": 10, "fiber_g": 2},
    "burger": {"calories_per_100g": 295, "protein_g": 17, "carbs_g": 24, "fat_g": 14, "fiber_g": 1},
    "pasta": {"calories_per_100g": 158, "protein_g": 6, "carbs_g": 31, "fat_g": 0.9, "fiber_g": 1.8},
    "egg": {"calories_per_100g": 155, "protein_g": 13, "carbs_g": 1.1, "fat_g": 11, "fiber_g": 0},
    "banana": {"calories_per_100g": 89, "protein_g": 1.1, "carbs_g": 23, "fat_g": 0.3, "fiber_g": 2.6},
    "apple": {"calories_per_100g": 52, "protein_g": 0.3, "carbs_g": 14, "fat_g": 0.2, "fiber_g": 2.4},
    "oats": {"calories_per_100g": 389, "protein_g": 17, "carbs_g": 66, "fat_g": 7, "fiber_g": 10},
    "milk": {"calories_per_100g": 42, "protein_g": 3.4, "carbs_g": 5, "fat_g": 1, "fiber_g": 0},
    "paneer": {"calories_per_100g": 265, "protein_g": 18, "carbs_g": 3.4, "fat_g": 21, "fiber_g": 0},
    "samosa": {"calories_per_100g": 262, "protein_g": 5, "carbs_g": 27, "fat_g": 16, "fiber_g": 2},
}

HEALTHIER_ALTERNATIVES = {
    "rice": ["Quinoa (higher protein, same satiety)", "Cauliflower rice (75% fewer calories)", "Brown rice (more fiber)"],
    "pizza": ["Whole wheat thin crust pizza with veggies", "Cauliflower crust pizza", "Pita bread with hummus and veggies"],
    "burger": ["Grilled chicken lettuce wrap", "Black bean veggie burger", "Turkey burger on whole grain bun"],
    "samosa": ["Baked vegetable cutlet", "Steamed momos", "Roasted chickpeas snack"],
    "pasta": ["Zucchini noodles with marinara", "Lentil pasta (higher protein)", "Whole wheat pasta"],
}


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="get_nutrition_data",
            description="Look up nutritional information (calories, protein, carbs, fat, fiber) for a specific food item and portion size.",
            inputSchema={
                "type": "object",
                "properties": {
                    "food_name": {"type": "string", "description": "Name of the food item"},
                    "portion_grams": {"type": "number", "description": "Portion size in grams (default 100)"},
                },
                "required": ["food_name"],
            },
        ),
        types.Tool(
            name="log_meal",
            description="Log a meal to the daily nutrition tracker. Records calories and macros for the current date.",
            inputSchema={
                "type": "object",
                "properties": {
                    "meal_name": {"type": "string", "description": "Name or description of the meal"},
                    "calories": {"type": "number", "description": "Total calories in the meal"},
                    "protein_g": {"type": "number", "description": "Protein in grams"},
                    "carbs_g": {"type": "number", "description": "Carbohydrates in grams"},
                    "fat_g": {"type": "number", "description": "Fat in grams"},
                    "fiber_g": {"type": "number", "description": "Fiber in grams"},
                    "meal_type": {"type": "string", "description": "breakfast/lunch/dinner/snack"},
                },
                "required": ["meal_name", "calories"],
            },
        ),
        types.Tool(
            name="get_daily_summary",
            description="Get today's nutrition summary including total intake and remaining budget against daily goals.",
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date in YYYY-MM-DD format (defaults to today)"},
                },
            },
        ),
        types.Tool(
            name="get_healthier_alternatives",
            description="Get 3 healthier food alternatives for a given food item, with estimated calorie comparison.",
            inputSchema={
                "type": "object",
                "properties": {
                    "food_name": {"type": "string", "description": "Food item to find alternatives for"},
                    "dietary_preference": {"type": "string", "description": "vegetarian/vegan/non-veg (default: any)"},
                },
                "required": ["food_name"],
            },
        ),
        types.Tool(
            name="generate_diet_plan",
            description="Generate a personalized daily or weekly diet plan based on remaining calorie budget and dietary goals.",
            inputSchema={
                "type": "object",
                "properties": {
                    "remaining_calories": {"type": "number", "description": "Remaining calories budget for the day"},
                    "dietary_preference": {"type": "string", "description": "vegetarian/vegan/non-veg"},
                    "plan_type": {"type": "string", "description": "daily or weekly"},
                    "cuisine_preference": {"type": "string", "description": "Indian/Mediterranean/American/any"},
                },
                "required": ["remaining_calories"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:

    if name == "get_nutrition_data":
        food = arguments.get("food_name", "").lower()
        portion = float(arguments.get("portion_grams", 100))
        data = NUTRITION_DB.get(food)
        if data:
            factor = portion / 100
            result = {
                "food": food,
                "portion_g": portion,
                "calories": round(data["calories_per_100g"] * factor, 1),
                "protein_g": round(data["protein_g"] * factor, 1),
                "carbs_g": round(data["carbs_g"] * factor, 1),
                "fat_g": round(data["fat_g"] * factor, 1),
                "fiber_g": round(data["fiber_g"] * factor, 1),
            }
        else:
            # Provide a reasonable estimate for unknown foods
            result = {
                "food": food,
                "portion_g": portion,
                "calories": round(150 * portion / 100, 1),
                "protein_g": round(8 * portion / 100, 1),
                "carbs_g": round(20 * portion / 100, 1),
                "fat_g": round(5 * portion / 100, 1),
                "fiber_g": round(2 * portion / 100, 1),
                "note": "Estimated values — not in database",
            }
        return [types.TextContent(type="text", text=json.dumps(result))]

    elif name == "log_meal":
        date_key = datetime.date.today().isoformat()
        if date_key not in _daily_log:
            _daily_log[date_key] = []
        entry = {
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "meal_name": arguments.get("meal_name"),
            "meal_type": arguments.get("meal_type", "unspecified"),
            "calories": float(arguments.get("calories", 0)),
            "protein_g": float(arguments.get("protein_g", 0)),
            "carbs_g": float(arguments.get("carbs_g", 0)),
            "fat_g": float(arguments.get("fat_g", 0)),
            "fiber_g": float(arguments.get("fiber_g", 0)),
        }
        _daily_log[date_key].append(entry)
        return [types.TextContent(type="text", text=json.dumps({"status": "logged", "entry": entry}))]

    elif name == "get_daily_summary":
        date_key = arguments.get("date", datetime.date.today().isoformat())
        meals = _daily_log.get(date_key, [])
        totals = {
            "calories": sum(m["calories"] for m in meals),
            "protein_g": sum(m.get("protein_g", 0) for m in meals),
            "carbs_g": sum(m.get("carbs_g", 0) for m in meals),
            "fat_g": sum(m.get("fat_g", 0) for m in meals),
            "fiber_g": sum(m.get("fiber_g", 0) for m in meals),
        }
        remaining = {k: round(_daily_goals.get(k, 0) - totals.get(k, 0), 1) for k in _daily_goals}
        progress_pct = {k: round((totals.get(k, 0) / _daily_goals.get(k, 1)) * 100, 1) for k in _daily_goals}
        result = {
            "date": date_key,
            "meals_logged": len(meals),
            "totals": totals,
            "goals": _daily_goals,
            "remaining": remaining,
            "progress_percent": progress_pct,
        }
        return [types.TextContent(type="text", text=json.dumps(result))]

    elif name == "get_healthier_alternatives":
        food = arguments.get("food_name", "").lower()
        pref = arguments.get("dietary_preference", "any")
        alts = HEALTHIER_ALTERNATIVES.get(food, [
            f"Grilled version of {food} (saves ~30% calories)",
            f"Baked {food} instead of fried",
            f"Half portion of {food} with a large salad",
        ])
        result = {"food": food, "dietary_preference": pref, "alternatives": alts}
        return [types.TextContent(type="text", text=json.dumps(result))]

    elif name == "generate_diet_plan":
        remaining_cal = float(arguments.get("remaining_calories", 1000))
        pref = arguments.get("dietary_preference", "any")
        plan_type = arguments.get("plan_type", "daily")
        cuisine = arguments.get("cuisine_preference", "any")

        if remaining_cal > 800:
            meals = ["Grilled chicken salad (400 cal)", "Fruit bowl with yogurt (200 cal)", "Vegetable soup with roti (300 cal)"]
        elif remaining_cal > 400:
            meals = ["Dal with 1 roti (350 cal)", "Green tea with 2 biscuits (80 cal)"]
        else:
            meals = ["Light vegetable soup (150 cal)", "Chamomile tea"]

        weekly_overview = {
            "Monday": "High protein day — eggs, chicken, legumes",
            "Tuesday": "Mediterranean — fish, olive oil, greens",
            "Wednesday": "Indian vegetarian — dal, sabzi, roti",
            "Thursday": "High fiber day — oats, fruits, salads",
            "Friday": "Balanced — mix of proteins and complex carbs",
            "Saturday": "Moderate treat day — one indulgence, balanced rest",
            "Sunday": "Meal prep day — light and clean eating",
        }

        result = {
            "remaining_calories": remaining_cal,
            "dietary_preference": pref,
            "cuisine": cuisine,
            "remaining_meals_today": meals,
            "weekly_plan": weekly_overview if plan_type == "weekly" else None,
            "tip": "Drink 8 glasses of water and eat every 3-4 hours for best results.",
        }
        return [types.TextContent(type="text", text=json.dumps(result))]

    return [types.TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]


async def main():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
