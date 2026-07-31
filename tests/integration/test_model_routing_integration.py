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
from google.adk.runners import InMemoryRunner
from google.genai import types

from app.agent import app
from app.model_router import DEFAULT_FAST_MODEL, DEFAULT_REASONING_MODEL


@pytest.mark.asyncio
async def test_workflow_strategic_model_routing():
    """Verify that running the workflow classifies user inputs and records strategic model routing metadata in state."""
    runner = InMemoryRunner(app=app)
    session = await runner.session_service.create_session(
        app_name="app", user_id="test_routing_user"
    )

    # 1. Simple inventory query -> should route to fast tier
    user_msg_fast = types.Content(
        role="user",
        parts=[types.Part.from_text(text="Check my fridge inventory and flag expired food.")],
    )

    events = []
    async for event in runner.run_async(
        user_id="test_routing_user",
        session_id=session.id,
        new_message=user_msg_fast,
    ):
        events.append(event)

    session_updated = await runner.session_service.get_session(
        app_name="app", user_id="test_routing_user", session_id=session.id
    )

    routing_state = session_updated.state.get("model_routing")
    assert routing_state is not None
    assert routing_state["selected_model"] == DEFAULT_FAST_MODEL
    assert routing_state["tier"] == "fast"

    # 2. Complex multi-constraint meal planning -> should route to reasoning tier
    user_msg_reasoning = types.Content(
        role="user",
        parts=[
            types.Part.from_text(
                text="Plan a 3-day zero-waste meal plan with custom recipes for 4 people with dietary restrictions, macros, and ingredient substitutions."
            )
        ],
    )

    async for event in runner.run_async(
        user_id="test_routing_user",
        session_id=session.id,
        new_message=user_msg_reasoning,
    ):
        events.append(event)

    session_updated2 = await runner.session_service.get_session(
        app_name="app", user_id="test_routing_user", session_id=session.id
    )

    recipe_routing = session_updated2.state.get("recipe_model_routing")
    assert recipe_routing is not None
    assert recipe_routing["selected_model"] == DEFAULT_REASONING_MODEL
    assert recipe_routing["tier"] == "reasoning"
