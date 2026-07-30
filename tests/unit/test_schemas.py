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

import pytest

from app.flask_app import flask_app
from app.schemas import (
    FoodItemSchema,
    RecipeSchema,
    UserProfileSchema,
    get_all_app_schemas,
)


def test_pydantic_model_json_schemas():
    food_schema = FoodItemSchema.model_json_schema()
    assert food_schema["title"] == "FoodItemSchema"
    assert "name" in food_schema["properties"]
    assert "expiration_date" in food_schema["properties"]

    recipe_schema = RecipeSchema.model_json_schema()
    assert recipe_schema["title"] == "RecipeSchema"
    assert "ingredients" in recipe_schema["properties"]

    user_profile_schema = UserProfileSchema.model_json_schema()
    assert "dietary_restrictions" in user_profile_schema["properties"]


def test_get_all_app_schemas():
    all_schemas = get_all_app_schemas()
    assert "FoodItem" in all_schemas
    assert "Recipe" in all_schemas
    assert "UserProfile" in all_schemas
    assert "EpisodicLog" in all_schemas
    assert "AgentChatRequest" in all_schemas
    assert "AgentChatResponse" in all_schemas


def test_schemas_api_endpoint():
    client = flask_app.test_client()
    res = client.get("/api/schemas")
    assert res.status_code == 200
    data = res.get_json()
    assert "FoodItem" in data
    assert "BulkInventoryImport" in data
    assert "CookRecipeRequest" in data
