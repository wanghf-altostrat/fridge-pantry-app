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

"""Memory storage techniques and asynchronous update pipeline for Fridge & Pantry Agent.

This module provides multi-layered memory architecture:
1. Short-Term Working Memory (Session State via Context/ToolContext)
2. Structured User Profile & Preferences Memory Store (Dietary restrictions, favorites, household size)
3. Episodic Activity & Waste History Logger (Timestamped log of food events and zero-waste stats)
4. Conversational & Event Memory Service (ADK BaseMemoryService integration for semantic/keyword search)
5. Asynchronous Non-Blocking Update Pipeline (Background asyncio queues & tasks for fact extraction)
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from typing import Any

from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class UserProfile(BaseModel):
    """Structured memory store for user preferences and household metadata."""

    user_id: str = "default_user"
    dietary_restrictions: list[str] = Field(default_factory=list)
    favorite_ingredients: list[str] = Field(default_factory=list)
    disliked_ingredients: list[str] = Field(default_factory=list)
    household_size: int = 1
    sustainability_goals: list[str] = Field(
        default_factory=lambda: ["zero-waste", "reduce-food-spoilage"]
    )
    favorite_recipes: list[str] = Field(default_factory=list)
    custom_notes: dict[str, str] = Field(default_factory=dict)


class EpisodicLogEntry(BaseModel):
    """Episodic memory entry capturing timestamped events and sustainability impact."""

    timestamp: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC).isoformat()
    )
    event_type: str  # e.g., "grocery_added", "item_consumed", "expired_discarded", "recipe_cooked"
    details: dict[str, Any] = Field(default_factory=dict)
    impact_summary: str = ""


class StructuredProfileStore:
    """Thread-safe persistent store for user profiles (Structured Memory Technique)."""

    def __init__(self):
        self._profiles: dict[str, UserProfile] = {}
        self._lock = asyncio.Lock()

    def get_profile_sync(self, user_id: str = "default_user") -> UserProfile:
        if user_id not in self._profiles:
            self._profiles[user_id] = UserProfile(user_id=user_id)
        return self._profiles[user_id]

    async def get_profile(self, user_id: str = "default_user") -> UserProfile:
        async with self._lock:
            return self.get_profile_sync(user_id)

    async def update_profile(
        self,
        user_id: str = "default_user",
        dietary_restrictions: list[str] | None = None,
        favorite_ingredients: list[str] | None = None,
        disliked_ingredients: list[str] | None = None,
        household_size: int | None = None,
        favorite_recipes: list[str] | None = None,
        custom_notes: dict[str, str] | None = None,
    ) -> UserProfile:
        """Asynchronously update structured user profile attributes."""
        async with self._lock:
            profile = self.get_profile_sync(user_id)
            if dietary_restrictions is not None:
                for diet in dietary_restrictions:
                    d_clean = diet.strip().lower()
                    if d_clean and d_clean not in [
                        d.lower() for d in profile.dietary_restrictions
                    ]:
                        profile.dietary_restrictions.append(diet.strip())
            if favorite_ingredients is not None:
                for ing in favorite_ingredients:
                    i_clean = ing.strip().title()
                    if i_clean and i_clean not in profile.favorite_ingredients:
                        profile.favorite_ingredients.append(i_clean)
            if disliked_ingredients is not None:
                for ing in disliked_ingredients:
                    i_clean = ing.strip().title()
                    if i_clean and i_clean not in profile.disliked_ingredients:
                        profile.disliked_ingredients.append(i_clean)
            if household_size is not None and household_size > 0:
                profile.household_size = household_size
            if favorite_recipes is not None:
                for rec in favorite_recipes:
                    if rec and rec not in profile.favorite_recipes:
                        profile.favorite_recipes.append(rec)
            if custom_notes is not None:
                profile.custom_notes.update(custom_notes)
            self._profiles[user_id] = profile
            return profile


class EpisodicActivityLogger:
    """Timestamped episodic event memory store for tracking kitchen actions and sustainability metrics."""

    def __init__(self):
        self._logs: dict[str, list[EpisodicLogEntry]] = {}
        self._lock = asyncio.Lock()

    def log_event_sync(
        self,
        user_id: str,
        event_type: str,
        details: dict[str, Any],
        impact_summary: str = "",
    ) -> EpisodicLogEntry:
        entry = EpisodicLogEntry(
            event_type=event_type,
            details=details,
            impact_summary=impact_summary,
        )
        if user_id not in self._logs:
            self._logs[user_id] = []
        self._logs[user_id].append(entry)
        return entry

    async def log_event_async(
        self,
        user_id: str,
        event_type: str,
        details: dict[str, Any],
        impact_summary: str = "",
    ) -> EpisodicLogEntry:
        async with self._lock:
            return self.log_event_sync(user_id, event_type, details, impact_summary)

    async def get_recent_logs(
        self,
        user_id: str = "default_user",
        limit: int = 10,
        event_type: str | None = None,
    ) -> list[EpisodicLogEntry]:
        async with self._lock:
            user_logs = self._logs.get(user_id, [])
            if event_type:
                user_logs = [e for e in user_logs if e.event_type == event_type]
            return sorted(user_logs, key=lambda x: x.timestamp, reverse=True)[:limit]


class AsyncMemoryPipeline:
    """Asynchronous Memory Manager providing non-blocking updates and background task execution."""

    def __init__(self):
        self.profile_store = StructuredProfileStore()
        self.episodic_logger = EpisodicActivityLogger()
        self.adk_memory_service = InMemoryMemoryService()
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._bg_task: asyncio.Task | None = None
        self._bg_tasks: set[asyncio.Task] = set()

    def start_background_worker(self) -> None:
        """Starts the background worker loop if not already running."""
        try:
            loop = asyncio.get_running_loop()
            if self._bg_task is None or self._bg_task.done():
                self._bg_task = loop.create_task(self._process_queue_loop())
        except RuntimeError:
            pass  # No running event loop yet

    async def _process_queue_loop(self) -> None:
        """Background task loop that asynchronously processes memory update jobs."""
        while True:
            try:
                job = await self._queue.get()
                await self._execute_job(job)
                self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in async memory background worker: {e}")

    async def _execute_job(self, job: dict[str, Any]) -> None:
        job_type = job.get("type")
        user_id = job.get("user_id", "default_user")

        if job_type == "log_event":
            await self.episodic_logger.log_event_async(
                user_id=user_id,
                event_type=job.get("event_type", "general"),
                details=job.get("details", {}),
                impact_summary=job.get("impact_summary", ""),
            )
        elif job_type == "extract_facts":
            text = job.get("text", "")
            await self._extract_and_apply_facts_async(user_id, text)
        elif job_type == "ingest_events":
            events = job.get("events", [])
            app_name = job.get("app_name", "app")
            session_id = job.get("session_id")
            if events:
                await self.adk_memory_service.add_events_to_memory(
                    app_name=app_name,
                    user_id=user_id,
                    events=events,
                    session_id=session_id,
                )

    async def _extract_and_apply_facts_async(self, user_id: str, text: str) -> None:
        """Asynchronously extracts structured profile facts from user interaction text."""
        text_lower = text.lower()
        dietary_updates = []
        if "vegetarian" in text_lower or "veggie" in text_lower:
            dietary_updates.append("vegetarian")
        if "vegan" in text_lower:
            dietary_updates.append("vegan")
        if "gluten-free" in text_lower or "gluten free" in text_lower:
            dietary_updates.append("gluten-free")
        if "dairy-free" in text_lower or "lactose" in text_lower:
            dietary_updates.append("lactose-intolerant")
        if "keto" in text_lower:
            dietary_updates.append("keto")

        if dietary_updates:
            await self.profile_store.update_profile(
                user_id=user_id, dietary_restrictions=dietary_updates
            )

    def enqueue_update_async(
        self,
        job_type: str,
        user_id: str = "default_user",
        **kwargs,
    ) -> None:
        """Schedules a non-blocking memory update in the background."""
        job = {"type": job_type, "user_id": user_id, **kwargs}
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._execute_job(job))
            self._bg_tasks.add(task)
            task.add_done_callback(self._bg_tasks.discard)
        except RuntimeError:
            # Fallback if no active loop: log directly synchronously

            if job_type == "log_event":
                self.episodic_logger.log_event_sync(
                    user_id=user_id,
                    event_type=kwargs.get("event_type", "general"),
                    details=kwargs.get("details", {}),
                    impact_summary=kwargs.get("impact_summary", ""),
                )


# Global singleton memory pipeline instance
memory_pipeline = AsyncMemoryPipeline()
