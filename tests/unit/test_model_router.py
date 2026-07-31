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

from app.model_router import (
    DEFAULT_FAST_MODEL,
    DEFAULT_REASONING_MODEL,
    ModelRouter,
    ModelTier,
    RoutingDecision,
    get_model_for_task,
)


def test_model_router_simple_inventory_query():
    """Simple inventory checks should route to the fast tier model."""
    prompt = "Check my fridge inventory"
    decision = ModelRouter.route_input(prompt)

    assert isinstance(decision, RoutingDecision)
    assert decision.tier == ModelTier.FAST
    assert decision.selected_model == DEFAULT_FAST_MODEL
    assert decision.complexity_score < 0.45


def test_model_router_simple_add_food():
    """Simple food logging should route to the fast tier model."""
    prompt = "Bought 2 lbs chicken breast and added milk"
    decision = ModelRouter.route_input(prompt)

    assert decision.tier == ModelTier.FAST
    assert decision.selected_model == DEFAULT_FAST_MODEL


def test_model_router_complex_recipe_planning():
    """Complex multi-constraint meal planning should route to the reasoning model."""
    prompt = (
        "Plan a 3-day zero-waste meal plan for 4 people with dietary restrictions "
        "and custom substitutions using my expiring tomatoes, spinach, and chicken."
    )
    decision = ModelRouter.route_input(prompt)

    assert decision.tier == ModelTier.REASONING
    assert decision.selected_model == DEFAULT_REASONING_MODEL
    assert decision.complexity_score >= 0.45


def test_model_router_with_context_dietary_restrictions():
    """Active dietary restrictions in context should increase complexity score."""
    prompt = "Suggest zero-waste recipes"
    context = {"dietary_restrictions": ["gluten-free", "vegan", "keto"]}

    decision_with_context = ModelRouter.route_input(prompt, context_state=context)
    decision_no_context = ModelRouter.route_input(prompt)

    assert decision_with_context.complexity_score > decision_no_context.complexity_score


def test_model_router_explicit_override():
    """Explicit model_override in context state should be respected unconditionally."""
    prompt = "Check inventory"
    context = {"model_override": "gemini-2.5-pro"}

    decision = ModelRouter.route_input(prompt, context_state=context)

    assert decision.selected_model == "gemini-2.5-pro"
    assert decision.tier == ModelTier.REASONING
    assert "override" in decision.reason.lower()


def test_get_model_for_task_helper():
    """Helper function should return the correct model string directly."""
    fast_model = get_model_for_task("Check fridge")
    reasoning_model = get_model_for_task(
        "Generate custom zero-waste meal plan with complex nutritional macros and diet constraints"
    )

    assert fast_model == DEFAULT_FAST_MODEL
    assert reasoning_model == DEFAULT_REASONING_MODEL


def test_model_router_empty_input():
    """Empty or whitespace input should default gracefully to fast tier."""
    decision = ModelRouter.route_input("   ")
    assert decision.tier == ModelTier.FAST
    assert decision.selected_model == DEFAULT_FAST_MODEL
