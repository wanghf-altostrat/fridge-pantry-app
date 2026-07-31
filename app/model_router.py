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

"""Strategic Model Routing module for Fridge & Pantry Agent.

This module provides dynamic task complexity classification and model routing to
optimally balance latency, cost, and reasoning depth between fast/lightweight models
(e.g., gemini-2.5-flash) and high-reasoning models (e.g., gemini-2.5-pro).
"""

from __future__ import annotations

from enum import Enum
import logging
import os
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Default model tier constants
DEFAULT_FAST_MODEL = "gemini-2.5-flash"
DEFAULT_REASONING_MODEL = "gemini-2.5-pro"

# Environment variable overrides
FAST_MODEL = os.getenv("FAST_MODEL", DEFAULT_FAST_MODEL)
REASONING_MODEL = os.getenv("REASONING_MODEL", DEFAULT_REASONING_MODEL)


class ModelTier(str, Enum):
    """Execution tiers for strategic model selection."""

    FAST = "fast"
    REASONING = "reasoning"


class RoutingDecision(BaseModel):
    """Data model holding the strategic model routing output and metadata."""

    selected_model: str = Field(
        ..., description="The Gemini model identifier selected for execution."
    )
    tier: ModelTier = Field(
        ..., description="The performance/reasoning tier of the selected model."
    )
    complexity_score: float = Field(
        ..., description="Calculated task complexity score between 0.0 and 1.0."
    )
    reason: str = Field(
        ..., description="Human-readable justification for the routing decision."
    )


class ModelRouter:
    """Strategic Model Router that routes agent operations to appropriate model tiers."""

    FAST_KEYWORDS = {
        "add",
        "added",
        "bought",
        "buy",
        "consume",
        "consumed",
        "eat",
        "eaten",
        "discard",
        "throw",
        "remove",
        "check",
        "inventory",
        "status",
        "list",
        "expired",
        "expiring",
        "storage",
        "store",
        "advice",
        "shelf",
    }

    REASONING_KEYWORDS = {
        "plan",
        "meal plan",
        "recipe",
        "recipes",
        "cook",
        "nutrition",
        "nutritional",
        "macro",
        "macros",
        "diet",
        "dietary",
        "restriction",
        "allergy",
        "substitute",
        "substitution",
        "custom",
        "synthesis",
        "zero-waste",
        "multi-day",
        "weekly",
        "balance",
    }

    @classmethod
    def calculate_complexity(
        cls, input_text: str, context_state: Optional[Dict[str, Any]] = None
    ) -> tuple[float, str]:
        """Calculates task complexity score (0.0 to 1.0) and generates a routing reason."""
        text_lower = input_text.lower().strip()
        if not text_lower:
            return 0.0, "Empty or minimal input defaults to fast tier."

        words = set(text_lower.split())

        fast_matches = words.intersection(cls.FAST_KEYWORDS)
        reasoning_matches = words.intersection(cls.REASONING_KEYWORDS)

        # Base score starts neutral at 0.2
        score = 0.2

        reasons = []

        if reasoning_matches:
            match_list = sorted(list(reasoning_matches))
            score += 0.3 * len(reasoning_matches)
            reasons.append(f"matched reasoning keywords ({', '.join(match_list)})")

        if fast_matches:
            match_list = sorted(list(fast_matches))
            score -= 0.15 * len(fast_matches)
            reasons.append(f"matched fast keywords ({', '.join(match_list)})")

        # Length and multi-sentence heuristic
        if len(input_text) > 120 or len(input_text.split(".")) > 2:
            score += 0.2
            reasons.append("long or multi-clause prompt structure")

        # Context state checks (e.g. dietary restrictions present in profile)
        if context_state:
            dietary = context_state.get("dietary_restrictions") or []
            if dietary:
                score += 0.15
                reasons.append(f"user profile has active dietary constraints ({dietary})")

        # Bound score between 0.0 and 1.0
        clamped_score = max(0.0, min(1.0, round(score, 2)))
        reason_str = "; ".join(reasons) if reasons else "routine input analysis"

        return clamped_score, reason_str

    @classmethod
    def route_input(
        cls,
        input_text: str,
        context_state: Optional[Dict[str, Any]] = None,
        complexity_threshold: float = 0.45,
    ) -> RoutingDecision:
        """Determines optimal model tier and model ID based on input complexity and context."""
        context_state = context_state or {}

        # 1. Check for explicit manual override in context state
        override_model = context_state.get("model_override")
        if override_model:
            tier = (
                ModelTier.REASONING
                if "pro" in override_model.lower()
                else ModelTier.FAST
            )
            decision = RoutingDecision(
                selected_model=override_model,
                tier=tier,
                complexity_score=1.0 if tier == ModelTier.REASONING else 0.0,
                reason=f"Explicit context model override requested: {override_model}",
            )
            logger.info(
                f"STRATEGIC MODEL ROUTE [OVERRIDE]: Selected '{decision.selected_model}' ({decision.tier.value}) - {decision.reason}"
            )
            return decision

        # 2. Compute complexity score
        complexity_score, reason = cls.calculate_complexity(input_text, context_state)

        # 3. Apply threshold routing
        if complexity_score >= complexity_threshold:
            selected_model = REASONING_MODEL
            tier = ModelTier.REASONING
        else:
            selected_model = FAST_MODEL
            tier = ModelTier.FAST

        decision = RoutingDecision(
            selected_model=selected_model,
            tier=tier,
            complexity_score=complexity_score,
            reason=f"Score {complexity_score} (threshold {complexity_threshold}): {reason}",
        )

        logger.info(
            f"STRATEGIC MODEL ROUTE [{tier.value.upper()}]: Selected model '{selected_model}' "
            f"for task score {complexity_score} ({decision.reason})"
        )

        return decision


def get_model_for_task(
    input_text: str, context_state: Optional[Dict[str, Any]] = None
) -> str:
    """Helper function returning the model name string directly for a given input."""
    return ModelRouter.route_input(input_text, context_state).selected_model
