# Submission Writeup — Food Nutrition Agent

**Competition Track:** Agents for Good
**Project Name:** food-nutrition-agent
**Built With:** Google ADK 2.0, MCP Server, Multi-Agent Workflow, Agents CLI

---

## Problem Statement

Millions of people struggle with understanding what they eat. Reading nutrition labels is time-consuming, estimating home-cooked meal calories is nearly impossible, and finding personalized dietary guidance usually requires a dietitian. Poor nutrition awareness contributes to rising rates of obesity, diabetes, and lifestyle diseases globally — especially in countries like India where diverse cuisines make tracking difficult.

**This agent democratizes nutrition intelligence** — making it as easy as describing your meal in plain language to get expert-level dietary guidance instantly.

---

## Solution Architecture

```
User Input (meal description/URL)
        │
        ▼
┌───────────────────┐
│ Security          │  PII scrub (email, phone, Aadhar)
│ Checkpoint        │  Injection detection (15 keywords)
│ (function node)   │  Domain filter (food-topic check)
└────────┬──────────┘
    PASS │     SECURITY_EVENT → Blocked
         ▼
┌─────────────────────────────────────┐
│  food_nutrition_orchestrator        │  Root LlmAgent
│  Coordinates the full analysis flow │
└──┬──────────┬──────────┬────────────┘
   │          │          │       │
   ▼          ▼          ▼       ▼
vision_   nutrition_  diet_   nutrition_
analyst   analyst     planner  tracker
   │          │          │       │
   └──────────┴──────────┴───────┘
              MCP Server (stdio)
    get_nutrition_data | log_meal
    get_daily_summary | get_healthier_alternatives
    generate_diet_plan
```

---

## Concepts Used

| Concept | File | Description |
|---------|------|-------------|
| **ADK LlmAgent** | `app/agent.py` | 1 orchestrator + 4 specialized sub-agents |
| **AgentTool** | `app/agent.py` | Orchestrator delegates to sub-agents via AgentTool |
| **output_key / ctx.state** | `app/agent.py` | Sub-agents write to `identified_foods`, `nutrition_analysis`, `diet_plan`, `tracking_summary` |
| **MCP Server** | `app/mcp_server.py` | 5 nutrition tools via stdio transport |
| **MCPToolset** | `app/agent.py` | Wired into nutrition_analyst and tracker_agent |
| **Security Checkpoint** | `app/agent.py` | `security_checkpoint()` function — PII + injection + audit log |
| **Agents CLI** | CLI scaffold | `agents-cli scaffold create` + `GEMINI.md` + Makefile |

---

## Security Design

| Control | Implementation | Why It Matters |
|---------|---------------|----------------|
| **PII Scrubbing** | Regex for email, phone, SSN, credit card, Aadhar number | Users may inadvertently share personal data while describing their health; must be redacted before LLM processing |
| **Prompt Injection Detection** | 15 keyword patterns ("ignore previous", "act as", "jailbreak", etc.) | Prevents adversarial users from hijacking agent behavior through meal descriptions |
| **Domain Filter** | Checks input for food-related terms; warns on off-topic | Prevents agent misuse for non-nutritional queries |
| **Structured Audit Log** | JSON log with timestamp, pii_found, injection_detected, severity (INFO/WARNING/CRITICAL) | Full traceability for compliance and debugging |
| **SECURITY_EVENT route** | Returns blocked verdict, stops pipeline | Ensures injection attempts never reach LLM agents |

---

## MCP Server Design

| Tool | Used By | Purpose |
|------|---------|---------|
| `get_nutrition_data` | nutrition_analyst | Looks up calories, protein, carbs, fat, fiber per 100g for any food |
| `log_meal` | nutrition_tracker | Persists meal entry to in-memory daily log (date-keyed) |
| `get_daily_summary` | nutrition_tracker | Aggregates daily totals and computes remaining budget vs goals |
| `get_healthier_alternatives` | nutrition_analyst | Returns 3 domain-specific healthy swaps for a given food |
| `generate_diet_plan` | diet_planner | Builds remaining-day meal suggestions and 7-day weekly overview |

---

## HITL (Human-in-the-Loop) Flow

The current implementation uses a **soft HITL pattern** — the orchestrator synthesizes all sub-agent outputs into a human-readable summary that the user can act on. The user drives every query, review, and follow-up:

1. **User submits meal** → reviews nutrition analysis
2. **User requests alternatives** → chooses from 3 healthier options
3. **User reviews diet plan** → decides which meals to follow
4. **User checks daily progress** → adjusts remaining meals

A full `RequestInput` hard stop can be added to ask for dietary goals (target calories, dietary restrictions) before generating the plan — this would be the natural next iteration.

---

## Demo Walkthrough

**Test Case 1 — Single meal analysis:**
- Input: `"I just had 2 samosas and a cup of masala chai"`
- Path: security_checkpoint → vision_analyst (identifies 2 samosas + chai) → nutrition_analyst (524 cal, Yellow health rating) → diet_planner (evening meal suggestions) → tracker (logs to daily total)
- Output: Full breakdown + 3 healthier snack alternatives

**Test Case 2 — Remaining day planning:**
- Input: `"I had pizza for lunch (2 slices). What should I eat for the rest of the day to stay under 2000 calories?"`
- Path: nutrition_analyst (532 cal for 2 slices) → diet_planner generates afternoon snack + dinner plan within ~1468 cal remaining
- Output: Specific meal suggestions with portions and prep tips

**Test Case 3 — Daily tracking:**
- Input: `"Show me my nutrition progress for today"`
- Path: tracker_agent retrieves all logged meals → computes cumulative macros → % toward goals
- Output: Progress dashboard with motivational message

---

## Impact / Value Statement

**Who benefits:** Anyone who wants to eat healthier — students, working professionals, families, people managing diabetes or weight conditions, fitness enthusiasts — without needing a dietitian.

**Why it matters:** The global diet-related disease burden costs trillions annually. Early nutrition awareness and simple behavioral nudges (like seeing "Red" for a meal) create lasting habit changes. This agent makes expert nutrition guidance conversational, instant, and free.

**Scale potential:** Deployable as a WhatsApp bot, mobile app backend, or hospital patient portal — one agent, many channels.
