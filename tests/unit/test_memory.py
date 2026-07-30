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
from unittest.mock import MagicMock

import pytest

from app.agent import (
    add_food_item,
    get_activity_history,
    get_user_profile,
    query_user_memory,
    update_user_profile,
)
from app.memory import (
    AsyncMemoryPipeline,
    EpisodicActivityLogger,
    StructuredProfileStore,
)


@pytest.mark.asyncio
async def test_structured_profile_store():
    store = StructuredProfileStore()
    profile = await store.get_profile("test_user_1")
    assert profile.user_id == "test_user_1"
    assert profile.household_size == 1

    updated = await store.update_profile(
        user_id="test_user_1",
        dietary_restrictions=["vegetarian", "gluten-free"],
        favorite_ingredients=["spinach"],
        household_size=3,
    )
    assert "vegetarian" in updated.dietary_restrictions
    assert "gluten-free" in updated.dietary_restrictions
    assert "Spinach" in updated.favorite_ingredients
    assert updated.household_size == 3


@pytest.mark.asyncio
async def test_episodic_activity_logger():
    logger = EpisodicActivityLogger()
    await logger.log_event_async(
        user_id="test_user_2",
        event_type="grocery_added",
        details={"name": "Avocado", "quantity": "3 pcs"},
        impact_summary="Added Avocado to fridge",
    )

    logs = await logger.get_recent_logs("test_user_2", limit=5)
    assert len(logs) == 1
    assert logs[0].event_type == "grocery_added"
    assert "Avocado" in logs[0].impact_summary


@pytest.mark.asyncio
async def test_async_memory_pipeline_fact_extraction():
    pipeline = AsyncMemoryPipeline()
    await pipeline._extract_and_apply_facts_async(
        "user_fact_test", "I am a vegetarian and eat gluten-free"
    )

    profile = await pipeline.profile_store.get_profile("user_fact_test")
    assert "vegetarian" in profile.dietary_restrictions
    assert "gluten-free" in profile.dietary_restrictions


@pytest.mark.asyncio
async def test_memory_tools():
    tool_ctx = MagicMock()
    tool_ctx.user_id = "unit_test_user"
    tool_ctx.state = {"inventory": []}

    # Test update_user_profile
    res = await update_user_profile(
        tool_context=tool_ctx,
        dietary_restrictions="keto, dairy-free",
        favorite_ingredients="avocado, salmon",
        household_size=2,
    )
    assert "keto" in res
    assert "Household Size: 2" in res

    # Test get_user_profile
    profile_str = await get_user_profile(tool_context=tool_ctx)
    assert "keto" in profile_str
    assert "Household Size: 2" in profile_str

    # Test add_food_item with async memory logging
    add_res = add_food_item(
        tool_context=tool_ctx,
        name="Greek Yogurt",
        quantity="1 tub",
        category="fridge",
        expiration_date="2026-12-31",
    )
    assert "Successfully added" in add_res
    await asyncio.sleep(0.05)  # Allow async background task to execute on loop

    # Test get_activity_history
    history_str = await get_activity_history(tool_context=tool_ctx)

    assert "Recent Activity History" in history_str
    assert "Added 'Greek Yogurt'" in history_str

    # Test query_user_memory
    mem_res = await query_user_memory(tool_context=tool_ctx, query="Greek Yogurt")
    assert "memory" in mem_res.lower()
