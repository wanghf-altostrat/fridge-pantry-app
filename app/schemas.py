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

"""JSON Schema specifications and Pydantic models for Fridge & Pantry Agent payloads."""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class FoodItemSchema(BaseModel):
    """JSON Schema for a fridge or pantry food item."""

    name: str = Field(description="Name of the food item (e.g. 'Chicken Breast', 'Milk')")
    quantity: str = Field(default="1", description="Quantity string with units (e.g. '2 lbs', '1 carton')")
    category: Literal["fridge", "pantry"] = Field(
        default="fridge", description="Storage location category"
    )
    expiration_date: str = Field(
        description="Expiration date formatted as YYYY-MM-DD"
    )
    days_left: Optional[int] = Field(
        default=None, description="Computed days remaining until expiration"
    )
    status: Optional[Literal["fresh", "expiring_soon", "expired"]] = Field(
        default=None, description="Computed freshness status"
    )


class BulkInventoryImportSchema(BaseModel):
    """JSON Schema for bulk shopping list or receipt import."""

    shopping_list: str = Field(
        default="", description="Raw receipt or shopping list text to parse"
    )
    items: List[FoodItemSchema] = Field(
        default_factory=list, description="Array of structured food item objects"
    )


class ConsumeItemSchema(BaseModel):
    """JSON Schema for requesting item consumption."""

    name: str = Field(description="Name of the food item to mark as consumed")


class CookRecipeRequestSchema(BaseModel):
    """JSON Schema for cooking a recommended recipe."""

    recipe: str = Field(
        default="1", description="Recipe ID or name to cook and deduct ingredients for"
    )


class RecipeSchema(BaseModel):
    """JSON Schema for a zero-waste recipe recommendation."""

    id: str = Field(description="Unique recipe identifier")
    name: str = Field(description="Recipe title")
    ingredients: List[str] = Field(description="List of required ingredients")
    category: str = Field(default="General", description="Recipe dietary category")
    cook_time: str = Field(default="15 mins", description="Estimated preparation time")
    expiring_used: List[str] = Field(
        default_factory=list, description="Expiring inventory items saved by recipe"
    )
    saves_expiring: List[str] = Field(
        default_factory=list, description="Alias list of expiring items saved"
    )


class UserProfileSchema(BaseModel):
    """JSON Schema for persistent user dietary preferences and household metadata."""

    user_id: str = Field(default="default_user", description="Unique user identifier")
    dietary_restrictions: List[str] = Field(
        default_factory=list, description="Dietary restriction tags (e.g. 'vegetarian', 'gluten-free')"
    )
    favorite_ingredients: List[str] = Field(
        default_factory=list, description="User favorite ingredients"
    )
    disliked_ingredients: List[str] = Field(
        default_factory=list, description="Disliked or allergic ingredients"
    )
    household_size: int = Field(default=1, description="Number of household members")
    sustainability_goals: List[str] = Field(
        default_factory=lambda: ["zero-waste", "reduce-food-spoilage"],
        description="Zero-waste and sustainability targets",
    )
    favorite_recipes: List[str] = Field(
        default_factory=list, description="Favorite recipe names"
    )
    custom_notes: Dict[str, str] = Field(
        default_factory=dict, description="Additional key-value notes"
    )


class EpisodicLogSchema(BaseModel):
    """JSON Schema for timestamped episodic activity history entries."""

    timestamp: str = Field(description="ISO-8601 UTC timestamp of event")
    event_type: str = Field(
        description="Type of kitchen action (e.g., 'grocery_added', 'item_consumed', 'expired_discarded', 'recipe_cooked')"
    )
    details: Dict[str, Any] = Field(
        default_factory=dict, description="Structured event payload data"
    )
    impact_summary: str = Field(
        default="", description="Human-readable impact or sustainability summary"
    )


class AgentChatRequestSchema(BaseModel):
    """JSON Schema for user chat interaction requests."""

    message: str = Field(description="User chat prompt or query string")


class AgentChatResponseSchema(BaseModel):
    """JSON Schema for agent chat interaction responses."""

    messages: List[str] = Field(description="List of agent turn response strings")
    hitl: Optional[Dict[str, Any]] = Field(
        default=None, description="Human-in-the-loop interruption request payload"
    )
    inventory: List[FoodItemSchema] = Field(
        default_factory=list, description="Updated list of enriched inventory items"
    )


def get_all_app_schemas() -> Dict[str, Any]:
    """Generates standard JSON Schema specifications for all application data models."""
    return {
        "FoodItem": FoodItemSchema.model_json_schema(),
        "BulkInventoryImport": BulkInventoryImportSchema.model_json_schema(),
        "ConsumeItem": ConsumeItemSchema.model_json_schema(),
        "CookRecipeRequest": CookRecipeRequestSchema.model_json_schema(),
        "Recipe": RecipeSchema.model_json_schema(),
        "UserProfile": UserProfileSchema.model_json_schema(),
        "EpisodicLog": EpisodicLogSchema.model_json_schema(),
        "AgentChatRequest": AgentChatRequestSchema.model_json_schema(),
        "AgentChatResponse": AgentChatResponseSchema.model_json_schema(),
    }
