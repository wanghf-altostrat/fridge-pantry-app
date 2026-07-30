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

import asyncio
import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from google.adk.agents.context import Context
from google.adk.apps import App, ResumabilityConfig
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.workflow import Workflow, START, node
from google.adk.tools import ToolContext
from google.adk.agents import LlmAgent
from google.genai import types

from app.memory import memory_pipeline


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
    if (
        "bought" in input_text.lower()
        or "added" in input_text.lower()
        or "grocery trip" in input_text.lower()
    ):
        new_item = {
            "name": "Greek Yogurt",
            "quantity": "1 tub",
            "category": "fridge",
            "expiration_date": (today + datetime.timedelta(days=12)).isoformat(),
        }
        current_inventory.append(new_item)

    ctx.state["inventory"] = current_inventory
    ctx.state["last_user_input"] = input_text

    # Asynchronous background memory update & fact extraction
    user_id = ctx.user_id or "default_user"
    if input_text:
        memory_pipeline.enqueue_update_async(
            job_type="extract_facts",
            user_id=user_id,
            text=input_text,
        )

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
    )


@node(name="recipe_agent")
async def recipe_agent(ctx: Context, node_input: dict):
    """Recipe recommendation agent node with Human-In-The-Loop pause (RequestInput)."""
    inventory = node_input.get("inventory", ctx.state.get("inventory", []))
    expiring_soon = node_input.get("expiring_soon", [])
    user_input = node_input.get("user_input", ctx.state.get("last_user_input", ""))
    user_id = ctx.user_id or "default_user"

    expiring_names = [item["name"] for item in expiring_soon]

    user_choice = None
    if ctx.resume_inputs and "recipe_approval" in ctx.resume_inputs:
        user_choice = ctx.resume_inputs["recipe_approval"]
    else:
        clean_input = user_input.strip().lower()
        if clean_input in ["1", "2", "3", "recipe 1", "recipe 2", "recipe 3"] or any(
            p in clean_input
            for p in ["i choose", "i'll make", "let's cook", "accept recipe", "cook "]
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
    elif (
        "2" in user_choice
        or "omelette" in user_choice.lower()
        or "egg" in user_choice.lower()
    ):
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

    # Asynchronously record recipe acceptance in episodic activity logger & profile memory
    memory_pipeline.enqueue_update_async(
        job_type="log_event",
        user_id=user_id,
        event_type="recipe_cooked",
        details={"recipe": recipe_name, "consumed": consumed_items},
        impact_summary=f"Cooked zero-waste recipe '{recipe_name}', using {', '.join(consumed_items)}.",
    )

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
    )


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
        "category": category.lower()
        if category.lower() in ["fridge", "pantry"]
        else "fridge",
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

    user_id = tool_context.user_id or "default_user"
    memory_pipeline.enqueue_update_async(
        job_type="log_event",
        user_id=user_id,
        event_type="grocery_added",
        details={
            "name": name,
            "quantity": quantity,
            "category": category,
            "expiration_date": expiration_date,
        },
        impact_summary=f"Added '{name}' ({quantity}) to {category}, expiring on {expiration_date}.",
    )
    memory_pipeline.enqueue_update_async(
        job_type="extract_facts",
        user_id=user_id,
        text=f"Added {name}",
    )

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

    user_id = tool_context.user_id or "default_user"
    if len(updated_inventory) < initial_len:
        memory_pipeline.enqueue_update_async(
            job_type="log_event",
            user_id=user_id,
            event_type="item_consumed",
            details={"name": name},
            impact_summary=f"Consumed '{name}' from inventory.",
        )
        return f"Successfully consumed '{name}' and removed it from inventory."
    return f"Food item '{name}' was not found in inventory."


def discard_expired_items(
    tool_context: ToolContext,
) -> str:
    """Discards all expired food items (items where expiration_date <= today) from inventory."""
    today_str = datetime.date.today().isoformat()
    inventory = tool_context.state.get("inventory", [])
    expired = [
        item
        for item in inventory
        if item.get("expiration_date", "9999-12-31") <= today_str
    ]
    remaining = [
        item
        for item in inventory
        if item.get("expiration_date", "9999-12-31") > today_str
    ]
    tool_context.state["inventory"] = remaining

    user_id = tool_context.user_id or "default_user"
    if expired:
        names = ", ".join([i["name"] for i in expired])
        memory_pipeline.enqueue_update_async(
            job_type="log_event",
            user_id=user_id,
            event_type="expired_discarded",
            details={"discarded": [i["name"] for i in expired]},
            impact_summary=f"Safely discarded {len(expired)} expired item(s): {names}.",
        )
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
    """Generates zero-waste recipe recommendations prioritizing expiring ingredients and accounting for user profile preferences."""
    today = datetime.date.today()
    cutoff_date = today + datetime.timedelta(days=7)
    inventory = tool_context.state.get("inventory", [])
    expiring = [
        item
        for item in inventory
        if datetime.date.fromisoformat(item["expiration_date"]) <= cutoff_date
    ]
    expiring_names = [i["name"] for i in expiring]

    user_id = tool_context.user_id or "default_user"
    profile = memory_pipeline.profile_store.get_profile_sync(user_id)
    diet_suffix = (
        f" (Tailored for {', '.join(profile.dietary_restrictions)})"
        if profile.dietary_restrictions
        else ""
    )

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
            "saves_expiring": [n for n in expiring_names if n in ["Eggs", "Milk"]],
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

    lines = [f"🍳 Zero-Waste Recipe Options{diet_suffix}:"]
    for r in recipes:
        saves_val = r["saves_expiring"]
        ing_val = r["ingredients"]
        saves_list = [str(x) for x in saves_val] if isinstance(saves_val, list) else []
        ing_list = [str(x) for x in ing_val] if isinstance(ing_val, list) else []
        saved_str = ", ".join(saves_list) if saves_list else "Pantry/Fridge staples"
        lines.append(
            f"{r['id']}. {r['name']} - Ingredients: {', '.join(ing_list)} (Saves expiring: {saved_str})"
        )

    return "\n".join(lines)


def get_storage_advice(
    tool_context: ToolContext,
    item_name: str,
) -> str:
    """Provides food storage, preservation, and shelf-life extension advice for an ingredient.

    Args:
        item_name: Name of the food item (e.g. 'Avocado', 'Spinach', 'Berries', 'Milk').
    """
    item_lower = item_name.lower()
    advice_db = {
        "avocado": "Store unripe avocados on the counter. Once ripe, refrigerate for up to 5 days. To freeze, mash with lemon juice.",
        "spinach": "Store in fridge wrapped in paper towels to absorb moisture. Freeze cooked or blanched spinach in airtight bags.",
        "berries": "Wash in diluted vinegar water before storing in paper-towel-lined containers in fridge. Do not seal tightly.",
        "bread": "Keep room-temp for 3-4 days. Freeze sliced bread for up to 3 months rather than refrigerating (which dries it out).",
        "milk": "Store on interior fridge shelves rather than door door racks to maintain cool temp.",
        "tomatoes": "Store on counter stem-side down at room temp. Refrigerate only when fully ripe or cut.",
    }
    for key, advice in advice_db.items():
        if key in item_lower:
            return f"Storage Advice for {item_name.title()}: {advice}"
    return (
        f"Storage Advice for {item_name.title()}: Store in a cool, dry place if shelf-stable, "
        f"or refrigerate at <= 40°F (4°C) in an airtight container. Freeze if planning to store long-term."
    )


def estimate_expiration(
    tool_context: ToolContext,
    item_name: str,
    category: str = "fridge",
) -> str:
    """Estimates standard shelf-life and recommended expiration date for unpackaged fresh food.

    Args:
        item_name: Name of the fresh food or leftover (e.g. 'Cooked Chicken', 'Fresh Salmon').
        category: Storage location, either 'fridge' or 'pantry'.
    """
    today = datetime.date.today()
    item_lower = item_name.lower()

    if "cooked" in item_lower or "leftover" in item_lower:
        days = 4
    elif "fish" in item_lower or "seafood" in item_lower or "salmon" in item_lower:
        days = 2
    elif (
        "raw" in item_lower
        or "poultry" in item_lower
        or "chicken" in item_lower
        or "beef" in item_lower
    ):
        days = 3
    elif "berry" in item_lower or "berries" in item_lower or "herbs" in item_lower:
        days = 5
    elif category.lower() == "pantry":
        days = 90
    else:
        days = 7

    est_date = (today + datetime.timedelta(days=days)).isoformat()
    return f"Estimated expiration date for '{item_name}' stored in {category}: {est_date} ({days} days from today)."


def generate_custom_recipe(
    tool_context: ToolContext,
    dietary_preference: str = "",
    target_ingredients: str = "",
) -> str:
    """Generates custom zero-waste recipes using ingredients available in inventory and matching user memory preferences.

    Args:
        dietary_preference: Optional diet filter (e.g. 'vegetarian', 'gluten-free', 'keto').
        target_ingredients: Specific ingredients the user wants to prioritize using.
    """
    inventory = tool_context.state.get("inventory", [])
    if not inventory:
        inventory = get_default_inventory()

    user_id = tool_context.user_id or "default_user"
    profile = memory_pipeline.profile_store.get_profile_sync(user_id)
    combined_diets = list(
        set([d for d in [dietary_preference] + profile.dietary_restrictions if d])
    )

    item_names = [i["name"] for i in inventory]
    pref_str = f" ({', '.join(combined_diets)})" if combined_diets else ""
    target_str = f" prioritizing {target_ingredients}" if target_ingredients else ""

    return (
        f"🍳 Custom Zero-Waste Recipe{pref_str}{target_str}:\n"
        f"- Main Dish: Pantry & Fridge Fusion Bowl\n"
        f"- Ingredients Used: {', '.join(item_names[:4])}\n"
        f"- Instructions: Sauté available proteins and veggies, combine with grains, and season to taste."
    )


async def query_user_memory(
    tool_context: ToolContext,
    query: str,
) -> str:
    """Asynchronously searches past conversational memory and food notes for relevant entries.

    Args:
        query: The search query or keyword (e.g. 'chicken', 'favorite', 'allergy', 'shopping').
    """
    user_id = tool_context.user_id or "default_user"
    response = await memory_pipeline.adk_memory_service.search_memory(
        app_name="app",
        user_id=user_id,
        query=query,
    )
    if not response.memories:
        return f"No prior memory entries found matching '{query}'."
    mem_summaries = []
    for mem in response.memories[:5]:
        parts = mem.content.parts if (mem.content and mem.content.parts) else []
        text = " ".join([p.text for p in parts if p.text])
        mem_summaries.append(f"- [{mem.timestamp}] ({mem.author}): {text}")

    return f"Found {len(mem_summaries)} memory match(es) for '{query}':\n" + "\n".join(
        mem_summaries
    )


async def update_user_profile(
    tool_context: ToolContext,
    dietary_restrictions: str = "",
    favorite_ingredients: str = "",
    disliked_ingredients: str = "",
    household_size: int = 0,
    favorite_recipes: str = "",
) -> str:
    """Asynchronously updates the user's persistent structured profile and dietary preferences.

    Args:
        dietary_restrictions: Comma-separated dietary restrictions (e.g. 'vegetarian, gluten-free').
        favorite_ingredients: Comma-separated favorite ingredients (e.g. 'spinach, garlic').
        disliked_ingredients: Comma-separated disliked/allergic ingredients (e.g. 'peanuts').
        household_size: Number of people in the household (e.g. 2 or 4).
        favorite_recipes: Comma-separated favorite recipe names.
    """
    user_id = tool_context.user_id or "default_user"
    diet_list = (
        [d.strip() for d in dietary_restrictions.split(",") if d.strip()]
        if dietary_restrictions
        else None
    )
    fav_ing_list = (
        [i.strip() for i in favorite_ingredients.split(",") if i.strip()]
        if favorite_ingredients
        else None
    )
    dis_ing_list = (
        [i.strip() for i in disliked_ingredients.split(",") if i.strip()]
        if disliked_ingredients
        else None
    )
    fav_rec_list = (
        [r.strip() for r in favorite_recipes.split(",") if r.strip()]
        if favorite_recipes
        else None
    )

    updated_profile = await memory_pipeline.profile_store.update_profile(
        user_id=user_id,
        dietary_restrictions=diet_list,
        favorite_ingredients=fav_ing_list,
        disliked_ingredients=dis_ing_list,
        household_size=household_size if household_size > 0 else None,
        favorite_recipes=fav_rec_list,
    )

    memory_pipeline.enqueue_update_async(
        job_type="log_event",
        user_id=user_id,
        event_type="user_profile_updated",
        details={
            "dietary": updated_profile.dietary_restrictions,
            "favorites": updated_profile.favorite_ingredients,
        },
        impact_summary=f"Profile updated: Household size {updated_profile.household_size}, Diets: {', '.join(updated_profile.dietary_restrictions) or 'None'}.",
    )

    return (
        f"User profile asynchronously updated:\n"
        f"- Household Size: {updated_profile.household_size}\n"
        f"- Dietary Restrictions: {', '.join(updated_profile.dietary_restrictions) or 'None'}\n"
        f"- Favorite Ingredients: {', '.join(updated_profile.favorite_ingredients) or 'None'}\n"
        f"- Disliked Ingredients: {', '.join(updated_profile.disliked_ingredients) or 'None'}\n"
        f"- Favorite Recipes: {', '.join(updated_profile.favorite_recipes) or 'None'}"
    )


async def get_user_profile(
    tool_context: ToolContext,
) -> str:
    """Retrieves the user's persistent structured profile, preferences, and dietary restrictions.

    Args:
        tool_context: ADK Tool Context.
    """
    user_id = tool_context.user_id or "default_user"
    profile = await memory_pipeline.profile_store.get_profile(user_id)
    return (
        f"📋 User Preference Profile ({profile.user_id}):\n"
        f"- Household Size: {profile.household_size}\n"
        f"- Dietary Restrictions: {', '.join(profile.dietary_restrictions) or 'None'}\n"
        f"- Favorite Ingredients: {', '.join(profile.favorite_ingredients) or 'None'}\n"
        f"- Disliked Ingredients: {', '.join(profile.disliked_ingredients) or 'None'}\n"
        f"- Favorite Recipes: {', '.join(profile.favorite_recipes) or 'None'}\n"
        f"- Sustainability Goals: {', '.join(profile.sustainability_goals)}"
    )


async def get_activity_history(
    tool_context: ToolContext,
    event_type: str = "",
) -> str:
    """Retrieves recent timestamped episodic memory logs of inventory changes, consumed food, and cooked meals.

    Args:
        event_type: Optional filter (e.g. 'grocery_added', 'item_consumed', 'expired_discarded', 'recipe_cooked').
    """
    user_id = tool_context.user_id or "default_user"
    logs = await memory_pipeline.episodic_logger.get_recent_logs(
        user_id=user_id, limit=10, event_type=event_type if event_type else None
    )
    if not logs:
        return "No recent activity log entries found."
    log_lines = [
        f"- [{entry.timestamp[:19]}] [{entry.event_type.upper()}] {entry.impact_summary or entry.details}"
        for entry in logs
    ]
    return f"Recent Activity History ({len(logs)} entries):\n" + "\n".join(log_lines)


pantry_llm_agent = LlmAgent(
    name="pantry_llm_agent",
    description="LLM Agent equipped with tools for inventory management, food tracking, storage advice, user preference profile tracking, activity logs, and custom recipe creation.",
    model="gemini-2.5-flash",
    instruction="""You are an intelligent Fridge & Pantry Assistant.
    You have tools to check inventory status, add food items, consume used ingredients, discard expired items, suggest zero-waste recipes, provide food storage advice, estimate expiration dates, generate custom recipes, update user profiles & dietary preferences, retrieve user profiles, query past conversation memory, and check activity history.
    When asked about inventory, logging groceries, consuming food, throwing out expired items, storage tips, dietary preferences, past activities, or recipe ideas, invoke the appropriate tool.""",
    tools=[
        add_food_item,
        consume_food_item,
        discard_expired_items,
        check_inventory,
        suggest_zero_waste_recipes,
        get_storage_advice,
        estimate_expiration,
        generate_custom_recipe,
        query_user_memory,
        update_user_profile,
        get_user_profile,
        get_activity_history,
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
