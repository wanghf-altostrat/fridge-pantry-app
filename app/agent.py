# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from google.adk.agents.context import Context
from google.adk.apps import App, ResumabilityConfig
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.workflow import Workflow, START, node
from google.genai import types


class FoodItem(BaseModel):
    name: str
    quantity: str
    category: str  # "fridge" or "pantry"
    expiration_date: str  # YYYY-MM-DD


def get_default_inventory() -> List[Dict[str, Any]]:
    today = datetime.date.today()
    return [
        {
            "name": "Chicken Breast",
            "quantity": "2 lbs",
            "category": "fridge",
            "expiration_date": (today + datetime.timedelta(days=2)).isoformat(),
        },
        {
            "name": "Milk",
            "quantity": "1 carton",
            "category": "fridge",
            "expiration_date": (today + datetime.timedelta(days=3)).isoformat(),
        },
        {
            "name": "Tomatoes",
            "quantity": "4 pcs",
            "category": "fridge",
            "expiration_date": (today + datetime.timedelta(days=4)).isoformat(),
        },
        {
            "name": "Eggs",
            "quantity": "6 pcs",
            "category": "fridge",
            "expiration_date": (today + datetime.timedelta(days=5)).isoformat(),
        },
        {
            "name": "Spinach",
            "quantity": "1 bag",
            "category": "fridge",
            "expiration_date": (today + datetime.timedelta(days=10)).isoformat(),
        },
        {
            "name": "Rice",
            "quantity": "5 lbs",
            "category": "pantry",
            "expiration_date": (today + datetime.timedelta(days=180)).isoformat(),
        },
        {
            "name": "Pasta",
            "quantity": "1 box",
            "category": "pantry",
            "expiration_date": (today + datetime.timedelta(days=200)).isoformat(),
        },
        {
            "name": "Old Cream Cheese",
            "quantity": "1 tub",
            "category": "fridge",
            "expiration_date": (today - datetime.timedelta(days=2)).isoformat(),
        },
    ]


@node(name="inventory_manager")
def inventory_manager(ctx: Context, node_input: Any) -> Event:
    """Node that processes grocery trips, manages inventory, and flags items expiring within 7 days."""
    today = datetime.date.today()
    cutoff_date = today + datetime.timedelta(days=7)

    current_inventory = ctx.state.get("inventory")
    if not current_inventory:
        current_inventory = get_default_inventory()

    # Extract user input text if present
    input_text = ""
    if isinstance(node_input, types.Content):
        for part in node_input.parts:
            if part.text:
                input_text += part.text
    elif isinstance(node_input, str):
        input_text = node_input

    # Process grocery trip additions
    if "bought" in input_text.lower() or "added" in input_text.lower() or "grocery trip" in input_text.lower():
        new_item = {
            "name": "Greek Yogurt",
            "quantity": "1 tub",
            "category": "fridge",
            "expiration_date": (today + datetime.timedelta(days=12)).isoformat(),
        }
        current_inventory.append(new_item)

    ctx.state["inventory"] = current_inventory
    ctx.state["last_user_input"] = input_text

    expiring_soon = []
    all_items_summary = []

    for item in current_inventory:
        exp_date = datetime.date.fromisoformat(item["expiration_date"])
        is_expiring = exp_date <= cutoff_date
        days_left = (exp_date - today).days

        if is_expiring:
            expiring_soon.append(item)
            all_items_summary.append(
                f"⚠️  [EXPIRING SOON] {item['name']} ({item['quantity']}) in {item['category']} - Expires in {days_left} days ({item['expiration_date']})"
            )
        else:
            all_items_summary.append(
                f"✅ {item['name']} ({item['quantity']}) in {item['category']} - Expires in {days_left} days ({item['expiration_date']})"
            )

    summary_text = (
        f"📋 **Fridge & Pantry Inventory Status (As of {today.isoformat()})**\n\n"
        + "\n".join(all_items_summary)
        + f"\n\n🚨 **Items Flagged Expiring Within 7 Days:** {len(expiring_soon)} item(s)"
    )

    return Event(
        output={
            "inventory": current_inventory,
            "expiring_soon": expiring_soon,
            "summary": summary_text,
            "user_input": input_text,
        },
        content=types.Content(
            role="model", parts=[types.Part.from_text(text=summary_text)]
        ),
        state={"inventory": current_inventory},
    )


@node(name="recipe_agent")
async def recipe_agent(ctx: Context, node_input: dict):
    """Recipe recommendation agent node with Human-In-The-Loop pause (RequestInput)."""
    inventory = node_input.get("inventory", ctx.state.get("inventory", []))
    expiring_soon = node_input.get("expiring_soon", [])
    user_input = node_input.get("user_input", ctx.state.get("last_user_input", ""))

    expiring_names = [item["name"] for item in expiring_soon]

    user_choice = None
    if ctx.resume_inputs and "recipe_approval" in ctx.resume_inputs:
        user_choice = ctx.resume_inputs["recipe_approval"]
    else:
        clean_input = user_input.strip().lower()
        if clean_input in ["1", "2", "3", "recipe 1", "recipe 2", "recipe 3"] or any(
            p in clean_input for p in ["i choose", "i'll make", "let's cook", "accept recipe", "cook "]
        ):
            user_choice = user_input

    # Step 1: Trigger HITL pause if user choice is not present
    if not user_choice:
        recipe_options = (
            "🍳 **Recommended Recipes (Using Expiring Ingredients First):**\n\n"
            f"1. **Chicken & Tomato Skillet**\n"
            f"   - Ingredients used: Chicken Breast (2 lbs), Tomatoes (2 pcs)\n"
            f"   - Expiring items saved: {', '.join([n for n in expiring_names if n in ['Chicken Breast', 'Tomatoes']]) or 'Chicken Breast, Tomatoes'}\n\n"
            f"2. **Cheesy Omelette Delight**\n"
            f"   - Ingredients used: Eggs (4 pcs), Milk (1/2 carton)\n"
            f"   - Expiring items saved: {', '.join([n for n in expiring_names if n in ['Eggs', 'Milk']]) or 'Eggs, Milk'}\n\n"
            f"3. **Vegetable Pasta Stir-Fry**\n"
            f"   - Ingredients used: Spinach (1 bag), Tomatoes (2 pcs), Pasta (1 box)\n"
            f"   - Expiring items saved: {', '.join([n for n in expiring_names if n in ['Tomatoes', 'Spinach']]) or 'Tomatoes'}\n\n"
            "Please select a recipe by entering its number (1, 2, or 3) or name to accept and proceed with cooking:"
        )

        yield RequestInput(interrupt_id="recipe_approval", message=recipe_options)
        return

    # Step 2: Process recipe acceptance & deduct consumed ingredients
    updated_inventory = list(inventory)
    consumed_items = []

    if "1" in user_choice or "chicken" in user_choice.lower():
        recipe_name = "Chicken & Tomato Skillet"
        consumed_items = ["Chicken Breast", "Tomatoes"]
    elif "2" in user_choice or "omelette" in user_choice.lower() or "egg" in user_choice.lower():
        recipe_name = "Cheesy Omelette Delight"
        consumed_items = ["Eggs", "Milk"]
    elif "3" in user_choice or "pasta" in user_choice.lower():
        recipe_name = "Vegetable Pasta Stir-Fry"
        consumed_items = ["Tomatoes", "Spinach"]
    else:
        recipe_name = f"Selected Recipe ({user_choice})"
        consumed_items = ["Chicken Breast"]

    # Deduct consumed items from inventory
    remaining_inventory = [
        item for item in updated_inventory if item["name"] not in consumed_items
    ]
    ctx.state["inventory"] = remaining_inventory

    result_text = (
        f"👨‍🍳 **Recipe Accepted:** {recipe_name}\n\n"
        f"✅ Used & Deducted Ingredients: {', '.join(consumed_items)}\n\n"
        f"📉 **Updated Inventory Contents ({len(remaining_inventory)} items remaining):**\n"
        + "\n".join(
            [
                f"- {item['name']} ({item['quantity']}) - exp {item['expiration_date']}"
                for item in remaining_inventory
            ]
        )
    )

    yield Event(
        output={
            "status": "accepted",
            "recipe": recipe_name,
            "consumed": consumed_items,
            "remaining_inventory": remaining_inventory,
        },
        content=types.Content(
            role="model", parts=[types.Part.from_text(text=result_text)]
        ),
        state={"inventory": remaining_inventory},
    )


from google.adk.tools import ToolContext
from google.adk.agents import LlmAgent


def add_food_item(
    tool_context: ToolContext,
    name: str,
    quantity: str,
    category: str,
    expiration_date: str,
) -> str:
    """Adds or updates a food item in the fridge or pantry inventory.

    Args:
        name: Name of the food item (e.g. 'Salmon', 'Greek Yogurt').
        quantity: Quantity string (e.g. '2 lbs', '1 carton').
        category: Storage location, either 'fridge' or 'pantry'.
        expiration_date: Date formatted as YYYY-MM-DD.
    """
    inventory = tool_context.state.get("inventory", [])
    if not inventory:
        inventory = get_default_inventory()

    new_item = {
        "name": name.title(),
        "quantity": quantity,
        "category": category.lower() if category.lower() in ["fridge", "pantry"] else "fridge",
        "expiration_date": expiration_date,
    }
    existing_idx = next(
        (i for i, item in enumerate(inventory) if item["name"].lower() == name.lower()),
        -1,
    )
    if existing_idx >= 0:
        inventory[existing_idx] = new_item
    else:
        inventory.append(new_item)
    tool_context.state["inventory"] = inventory
    return f"Successfully added '{name}' ({quantity}) to {category} expiring on {expiration_date}."


def consume_food_item(
    tool_context: ToolContext,
    name: str,
) -> str:
    """Consumes or marks a food item as eaten/used from inventory.

    Args:
        name: Name of the food item to consume (e.g. 'Milk', 'Chicken Breast').
    """
    inventory = tool_context.state.get("inventory", [])
    initial_len = len(inventory)
    updated_inventory = [
        item for item in inventory if item["name"].lower() != name.lower()
    ]
    tool_context.state["inventory"] = updated_inventory
    if len(updated_inventory) < initial_len:
        return f"Successfully consumed '{name}' and removed it from inventory."
    return f"Food item '{name}' was not found in inventory."


def discard_expired_items(
    tool_context: ToolContext,
) -> str:
    """Discards all expired food items (items where expiration_date <= today) from inventory."""
    today_str = datetime.date.today().isoformat()
    inventory = tool_context.state.get("inventory", [])
    expired = [
        item for item in inventory if item.get("expiration_date", "9999-12-31") <= today_str
    ]
    remaining = [
        item for item in inventory if item.get("expiration_date", "9999-12-31") > today_str
    ]
    tool_context.state["inventory"] = remaining
    if expired:
        names = ", ".join([i["name"] for i in expired])
        return f"Safely discarded {len(expired)} expired item(s): {names}."
    return "No expired food items were found in inventory."


def check_inventory(
    tool_context: ToolContext,
) -> str:
    """Checks the current fridge and pantry inventory status and flags items expiring within 7 days."""
    today = datetime.date.today()
    cutoff_date = today + datetime.timedelta(days=7)
    inventory = tool_context.state.get("inventory", [])
    if not inventory:
        inventory = get_default_inventory()
        tool_context.state["inventory"] = inventory

    items_status = []
    for item in inventory:
        exp_date = datetime.date.fromisoformat(item["expiration_date"])
        days_left = (exp_date - today).days
        if days_left < 0:
            items_status.append(
                f"🔴 [EXPIRED] {item['name']} ({item['quantity']}) in {item['category']} - Expired {abs(days_left)} days ago ({item['expiration_date']})"
            )
        elif days_left <= 7:
            items_status.append(
                f"⚠️ [EXPIRING SOON] {item['name']} ({item['quantity']}) in {item['category']} - Expires in {days_left} days ({item['expiration_date']})"
            )
        else:
            items_status.append(
                f"✅ {item['name']} ({item['quantity']}) in {item['category']} - Expires in {days_left} days ({item['expiration_date']})"
            )

    return f"Inventory Status (as of {today.isoformat()}):\n" + "\n".join(items_status)


def suggest_zero_waste_recipes(
    tool_context: ToolContext,
) -> str:
    """Generates zero-waste recipe recommendations prioritizing expiring ingredients."""
    today = datetime.date.today()
    cutoff_date = today + datetime.timedelta(days=7)
    inventory = tool_context.state.get("inventory", [])
    expiring = [
        item
        for item in inventory
        if datetime.date.fromisoformat(item["expiration_date"]) <= cutoff_date
    ]
    expiring_names = [i["name"] for i in expiring]

    recipes = [
        {
            "id": 1,
            "name": "Chicken & Tomato Skillet",
            "ingredients": ["Chicken Breast (2 lbs)", "Tomatoes (2 pcs)"],
            "saves_expiring": [
                n for n in expiring_names if n in ["Chicken Breast", "Tomatoes"]
            ],
        },
        {
            "id": 2,
            "name": "Cheesy Omelette Delight",
            "ingredients": ["Eggs (4 pcs)", "Milk (1/2 carton)"],
            "saves_expiring": [
                n for n in expiring_names if n in ["Eggs", "Milk"]
            ],
        },
        {
            "id": 3,
            "name": "Vegetable Pasta Stir-Fry",
            "ingredients": ["Spinach (1 bag)", "Tomatoes (2 pcs)", "Pasta (1 box)"],
            "saves_expiring": [
                n for n in expiring_names if n in ["Tomatoes", "Spinach"]
            ],
        },
    ]

    lines = ["🍳 Zero-Waste Recipe Options:"]
    for r in recipes:
        saved_str = (
            ", ".join(r["saves_expiring"]) if r["saves_expiring"] else "Pantry/Fridge staples"
        )
        lines.append(
            f"{r['id']}. {r['name']} - Ingredients: {', '.join(r['ingredients'])} (Saves expiring: {saved_str})"
        )

    return "\n".join(lines)


pantry_llm_agent = LlmAgent(
    name="pantry_llm_agent",
    description="LLM Agent equipped with tools for inventory management, food tracking, and recipe creation.",
    model="gemini-2.5-flash",
    instruction="""You are an intelligent Fridge & Pantry Assistant.
    You have tools to check inventory status, add food items, consume used ingredients, discard expired items, and suggest zero-waste recipes.
    When asked about inventory, logging groceries, consuming food, throwing out expired items, or recipe ideas, invoke the appropriate tool.""",
    tools=[
        add_food_item,
        consume_food_item,
        discard_expired_items,
        check_inventory,
        suggest_zero_waste_recipes,
    ],
)


root_agent = Workflow(
    name="fridge_pantry_agent",
    description="ADK 2.0 Fridge and Pantry Agent with LLM Tool calling for food tracking and recipe recommendations.",
    edges=[
        (START, inventory_manager),
        (inventory_manager, recipe_agent),
    ],
)

app = App(
    root_agent=root_agent,
    name="app",
    resumability_config=ResumabilityConfig(is_resumable=True),
)
