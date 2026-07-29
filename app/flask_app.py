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
import os
from flask import Flask, jsonify, render_template, request
from google.adk.runners import InMemoryRunner
from google.genai import types

from app.agent import app as adk_app, get_default_inventory

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

flask_app = Flask(
    __name__,
    static_folder=os.path.join(BASE_DIR, "static"),
    template_folder=os.path.join(BASE_DIR, "templates"),
)

# Global in-memory state and runner management
runner = InMemoryRunner(app=adk_app)
current_session_id = None
current_inventory = get_default_inventory()


async def get_or_create_session():
    global current_session_id
    if not current_session_id:
        session = await runner.session_service.create_session(
            app_name="app", user_id="default_user"
        )
        current_session_id = session.id
        session.state["inventory"] = current_inventory
    else:
        session = await runner.session_service.get_session(
            app_name="app", user_id="default_user", session_id=current_session_id
        )
    return session


def sync_inventory_to_session():
    """Sync global inventory state into ADK session state."""
    if current_session_id:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def _sync():
                session = await runner.session_service.get_session(
                    app_name="app", user_id="default_user", session_id=current_session_id
                )
                if session:
                    session.state["inventory"] = current_inventory
            loop.run_until_complete(_sync())
        finally:
            loop.close()


def enrich_item(item: dict) -> dict:
    today = datetime.date.today()
    try:
        exp_date = datetime.date.fromisoformat(item["expiration_date"])
        days_left = (exp_date - today).days
    except (ValueError, KeyError):
        days_left = 999

    status = "fresh"
    if days_left <= 0:
        status = "expired"
    elif days_left <= 7:
        status = "expiring_soon"

    return {
        **item,
        "days_left": days_left,
        "status": status,
    }


@flask_app.route("/")
def index():
    return render_template("index.html")


@flask_app.route("/api/inventory", methods=["GET"])
def get_inventory():
    enriched = [enrich_item(item) for item in current_inventory]
    today = datetime.date.today().isoformat()
    
    stats = {
        "total": len(enriched),
        "fridge": sum(1 for i in enriched if i.get("category") == "fridge"),
        "pantry": sum(1 for i in enriched if i.get("category") == "pantry"),
        "expiring_soon": sum(1 for i in enriched if i.get("status") == "expiring_soon"),
        "expired": sum(1 for i in enriched if i.get("status") == "expired"),
        "today": today,
    }
    return jsonify({"inventory": enriched, "stats": stats})


@flask_app.route("/api/inventory", methods=["POST"])
def add_item():
    global current_inventory
    data = request.json or {}
    name = data.get("name", "").strip()
    quantity = data.get("quantity", "1").strip()
    category = data.get("category", "fridge").lower()
    expiration_date = data.get("expiration_date", "")

    if not name or not expiration_date:
        return jsonify({"error": "Item name and expiration date are required"}), 400

    new_item = {
        "name": name,
        "quantity": quantity,
        "category": category if category in ["fridge", "pantry"] else "fridge",
        "expiration_date": expiration_date,
    }
    
    # Replace if item already exists or append
    existing_idx = next((i for i, item in enumerate(current_inventory) if item["name"].lower() == name.lower()), -1)
    if existing_idx >= 0:
        current_inventory[existing_idx] = new_item
    else:
        current_inventory.append(new_item)

    sync_inventory_to_session()
    return jsonify({"message": f"Added {name} to {category}", "item": enrich_item(new_item)})


@flask_app.route("/api/inventory/<path:item_name>", methods=["DELETE"])
def delete_item(item_name):
    global current_inventory
    initial_len = len(current_inventory)
    current_inventory = [
        item for item in current_inventory if item["name"].lower() != item_name.lower()
    ]
    if len(current_inventory) == initial_len:
        return jsonify({"error": f"Item '{item_name}' not found"}), 404

    sync_inventory_to_session()
    return jsonify({"message": f"Removed '{item_name}' from inventory"})


def parse_shopping_list_line(line: str) -> dict:
    """Parses a raw line from a shopping list into a structured item."""
    today = datetime.date.today()
    line_clean = line.strip().strip("-*•,")
    if not line_clean:
        return None

    # Determine location (fridge vs pantry) based on keywords
    pantry_keywords = [
        "rice", "pasta", "noodle", "canned", "beans", "flour", "sugar",
        "chip", "cracker", "oil", "sauce", "cereal", "oat", "spice", "nut",
        "honey", "coffee", "tea", "bread", "pantry"
    ]
    is_pantry = any(kw in line_clean.lower() for kw in pantry_keywords)
    category = "pantry" if is_pantry else "fridge"

    # Determine default expiration
    if any(kw in line_clean.lower() for kw in ["meat", "chicken", "beef", "pork", "fish", "salmon", "steak"]):
        exp_days = 3
    elif is_pantry:
        exp_days = 120
    else:
        exp_days = 7

    exp_date = (today + datetime.timedelta(days=exp_days)).isoformat()

    # Quantity & name parsing
    parts = line_clean.split()
    quantity = "1"
    name = line_clean

    if len(parts) >= 2 and parts[0].isdigit():
        if len(parts) > 2 and parts[1].lower() in ["lbs", "kg", "pcs", "carton", "box", "bag", "can", "tub", "gal", "pack", "bottle"]:
            quantity = f"{parts[0]} {parts[1]}"
            name = " ".join(parts[2:])
        else:
            quantity = parts[0]
            name = " ".join(parts[1:])

    if not name:
        name = line_clean

    return {
        "name": name.title(),
        "quantity": quantity,
        "category": category,
        "expiration_date": exp_date,
    }


@flask_app.route("/api/inventory/bulk", methods=["POST"])
def bulk_add_inventory():
    global current_inventory
    data = request.json or {}
    raw_list = data.get("shopping_list", "")
    items_array = data.get("items", [])

    added_items = []

    if raw_list:
        lines = [l for l in raw_list.replace(",", "\n").splitlines() if l.strip()]
        for line in lines:
            parsed = parse_shopping_list_line(line)
            if parsed:
                items_array.append(parsed)

    if not items_array:
        return jsonify({"error": "No valid shopping list items provided"}), 400

    for item in items_array:
        name = item.get("name", "").strip()
        if not name:
            continue
        quantity = item.get("quantity", "1")
        category = item.get("category", "fridge")
        expiration_date = item.get("expiration_date") or (
            datetime.date.today() + datetime.timedelta(days=7)
        ).isoformat()

        new_item = {
            "name": name,
            "quantity": quantity,
            "category": category if category in ["fridge", "pantry"] else "fridge",
            "expiration_date": expiration_date,
        }

        existing_idx = next(
            (i for i, existing in enumerate(current_inventory) if existing["name"].lower() == name.lower()),
            -1
        )
        if existing_idx >= 0:
            current_inventory[existing_idx] = new_item
        else:
            current_inventory.append(new_item)
        added_items.append(new_item)

    sync_inventory_to_session()

    enriched = [enrich_item(item) for item in current_inventory]
    return jsonify({
        "message": f"Successfully updated contents with {len(added_items)} item(s) from shopping list!",
        "added_count": len(added_items),
        "added_items": [enrich_item(i) for i in added_items],
        "inventory": enriched,
    })


@flask_app.route("/api/inventory/reset", methods=["POST"])
def reset_inventory():
    global current_inventory
    current_inventory = get_default_inventory()
    sync_inventory_to_session()
    return jsonify({
        "message": "Inventory reset to default sample items",
        "inventory": [enrich_item(item) for item in current_inventory],
    })


@flask_app.route("/api/inventory/consume", methods=["POST"])
def consume_item():
    global current_inventory
    data = request.json or {}
    item_name = data.get("name", "").strip()

    if not item_name:
        return jsonify({"error": "Item name is required"}), 400

    existing_item = next((i for i in current_inventory if i["name"].lower() == item_name.lower()), None)
    if not existing_item:
        return jsonify({"error": f"Item '{item_name}' not found in inventory"}), 404

    current_inventory = [i for i in current_inventory if i["name"].lower() != item_name.lower()]
    sync_inventory_to_session()

    enriched = [enrich_item(item) for item in current_inventory]
    return jsonify({
        "message": f"Consumed '{existing_item['name']}' ({existing_item['quantity']})",
        "consumed_item": existing_item,
        "inventory": enriched,
    })


@flask_app.route("/api/inventory/discard-expired", methods=["POST"])
def discard_expired_items():
    global current_inventory
    today_str = datetime.date.today().isoformat()

    expired_items = [
        item for item in current_inventory
        if item.get("expiration_date", "9999-12-31") <= today_str
    ]

    if not expired_items:
        return jsonify({
            "message": "No expired food items found in inventory!",
            "discarded_count": 0,
            "discarded_items": [],
            "inventory": [enrich_item(i) for i in current_inventory],
        })

    current_inventory = [
        item for item in current_inventory
        if item.get("expiration_date", "9999-12-31") > today_str
    ]

    sync_inventory_to_session()

    enriched = [enrich_item(item) for item in current_inventory]
    return jsonify({
        "message": f"Successfully discarded {len(expired_items)} expired food item(s)!",
        "discarded_count": len(expired_items),
        "discarded_items": [enrich_item(i) for i in expired_items],
        "inventory": enriched,
    })


@flask_app.route("/api/agent/chat", methods=["POST"])
def agent_chat():
    global current_inventory
    data = request.json or {}
    user_text = data.get("message", "").strip()

    if not user_text:
        return jsonify({"error": "Message is required"}), 400

    async def run_turn():
        global current_inventory
        session = await get_or_create_session()
        session.state["inventory"] = current_inventory

        user_msg = types.Content(
            role="user",
            parts=[types.Part.from_text(text=user_text)],
        )

        agent_messages = []
        hitl_request = None

        async for event in runner.run_async(
            user_id="default_user",
            session_id=session.id,
            new_message=user_msg,
        ):
            if hasattr(event, "content") and event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        agent_messages.append(part.text)
                    elif part.function_call:
                        hitl_request = {
                            "name": part.function_call.name,
                            "message": part.function_call.args.get("message"),
                        }

        # Update local inventory state from session state
        if "inventory" in session.state:
            current_inventory = session.state["inventory"]

        return agent_messages, hitl_request

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        messages, hitl = loop.run_until_complete(run_turn())
    finally:
        loop.close()

    enriched = [enrich_item(item) for item in current_inventory]
    return jsonify({
        "messages": messages,
        "hitl": hitl,
        "inventory": enriched,
    })


@flask_app.route("/api/agent/cook", methods=["POST"])
def cook_recipe():
    global current_inventory
    data = request.json or {}
    recipe_choice = data.get("recipe", "1").strip()

    consumed = []
    recipe_name = ""

    if "1" in recipe_choice or "skillet" in recipe_choice.lower() or "chicken" in recipe_choice.lower():
        recipe_name = "Chicken & Tomato Skillet"
        consumed = ["Chicken Breast", "Tomatoes"]
    elif "2" in recipe_choice or "omelette" in recipe_choice.lower() or "egg" in recipe_choice.lower():
        recipe_name = "Cheesy Omelette Delight"
        consumed = ["Eggs", "Milk"]
    elif "3" in recipe_choice or "pasta" in recipe_choice.lower():
        recipe_name = "Vegetable Pasta Stir-Fry"
        consumed = ["Tomatoes", "Spinach"]
    else:
        recipe_name = f"Custom Recipe ({recipe_choice})"
        consumed = ["Chicken Breast"]

    # Deduct consumed items
    current_inventory = [
        item for item in current_inventory if item["name"] not in consumed
    ]

    sync_inventory_to_session()

    enriched = [enrich_item(item) for item in current_inventory]
    return jsonify({
        "message": f"Successfully cooked {recipe_name}! Deducted: {', '.join(consumed)}",
        "recipe_name": recipe_name,
        "consumed": consumed,
        "inventory": enriched,
    })


@flask_app.route("/api/recipes", methods=["GET"])
def get_recipes():
    today = datetime.date.today()
    cutoff_date = today + datetime.timedelta(days=7)

    expiring_items = [
        item["name"]
        for item in current_inventory
        if datetime.date.fromisoformat(item["expiration_date"]) <= cutoff_date
    ]

    recipes = [
        {
            "id": "1",
            "name": "Chicken & Tomato Skillet",
            "ingredients": ["Chicken Breast", "Tomatoes"],
            "category": "High Protein",
            "cook_time": "20 mins",
            "expiring_used": [i for i in expiring_items if i in ["Chicken Breast", "Tomatoes"]],
        },
        {
            "id": "2",
            "name": "Cheesy Omelette Delight",
            "ingredients": ["Eggs", "Milk"],
            "category": "Breakfast / Quick",
            "cook_time": "10 mins",
            "expiring_used": [i for i in expiring_items if i in ["Eggs", "Milk"]],
        },
        {
            "id": "3",
            "name": "Vegetable Pasta Stir-Fry",
            "ingredients": ["Spinach", "Tomatoes", "Pasta"],
            "category": "Vegetarian",
            "cook_time": "15 mins",
            "expiring_used": [i for i in expiring_items if i in ["Tomatoes", "Spinach"]],
        },
    ]

    return jsonify({"recipes": recipes, "expiring_count": len(expiring_items)})


if __name__ == "__main__":
    flask_app.run(host="0.0.0.0", port=5000, debug=True)
