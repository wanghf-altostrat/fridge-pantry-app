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

This module provides multi-layered database-backed persistent memory architecture:
1. Short-Term Working Memory (Session State via Context/ToolContext)
2. Structured User Profile & Preferences Memory Store (SQLite user_profiles table)
3. Episodic Activity & Waste History Logger (SQLite episodic_logs table)
4. Conversational & Event Memory Service (ADK BaseMemoryService SQLite database implementation)
5. Asynchronous Non-Blocking Update Pipeline (Background asyncio queues & tasks for fact extraction)
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import sqlite3
from typing import Any

from google.adk.memory.base_memory_service import BaseMemoryService, SearchMemoryResponse
from google.adk.memory.memory_entry import MemoryEntry
from google.genai import types
from pydantic import BaseModel, Field

from app.privacy import sanitize_dict, sanitize_text
from app.schemas import EpisodicLogSchema, UserProfileSchema

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "memory.db"
)


class UserProfile(UserProfileSchema):
    """Structured memory store for user preferences and household metadata."""

    pass


class EpisodicLogEntry(EpisodicLogSchema):
    """Episodic memory entry capturing timestamped events and sustainability impact."""

    timestamp: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC).isoformat()
    )
    event_type: str  # e.g., "grocery_added", "item_consumed", "expired_discarded", "recipe_cooked"
    details: dict[str, Any] = Field(default_factory=dict)
    impact_summary: str = ""


class DatabaseManager:
    """SQLite Database Manager for persisting user profiles, episodic activity logs, and conversational memory."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id TEXT PRIMARY KEY,
                    dietary_restrictions TEXT,
                    favorite_ingredients TEXT,
                    disliked_ingredients TEXT,
                    household_size INTEGER,
                    sustainability_goals TEXT,
                    favorite_recipes TEXT,
                    custom_notes TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS episodic_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    timestamp TEXT,
                    event_type TEXT,
                    details TEXT,
                    impact_summary TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversation_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    app_name TEXT,
                    user_id TEXT,
                    session_id TEXT,
                    timestamp TEXT,
                    author TEXT,
                    content_text TEXT,
                    custom_metadata TEXT
                )
            """)
            conn.commit()


class StructuredProfileStore:
    """Thread-safe database-backed persistent store for user profiles."""

    def __init__(self, db_manager: DatabaseManager | None = None):
        self.db_manager = db_manager or DatabaseManager()
        self._lock = asyncio.Lock()

    def get_profile_sync(self, user_id: str = "default_user") -> UserProfile:
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)
            )
            row = cursor.fetchone()
            if row:
                return UserProfile(
                    user_id=row["user_id"],
                    dietary_restrictions=json.loads(row["dietary_restrictions"] or "[]"),
                    favorite_ingredients=json.loads(row["favorite_ingredients"] or "[]"),
                    disliked_ingredients=json.loads(row["disliked_ingredients"] or "[]"),
                    household_size=row["household_size"] or 1,
                    sustainability_goals=json.loads(
                        row["sustainability_goals"] or '["zero-waste", "reduce-food-spoilage"]'
                    ),
                    favorite_recipes=json.loads(row["favorite_recipes"] or "[]"),
                    custom_notes=json.loads(row["custom_notes"] or "{}"),
                )
            else:
                profile = UserProfile(user_id=user_id)
                self._save_profile_sync(conn, profile)
                return profile

    def _save_profile_sync(self, conn: sqlite3.Connection, profile: UserProfile) -> None:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO user_profiles (
                user_id, dietary_restrictions, favorite_ingredients, disliked_ingredients,
                household_size, sustainability_goals, favorite_recipes, custom_notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile.user_id,
                json.dumps(profile.dietary_restrictions),
                json.dumps(profile.favorite_ingredients),
                json.dumps(profile.disliked_ingredients),
                profile.household_size,
                json.dumps(profile.sustainability_goals),
                json.dumps(profile.favorite_recipes),
                json.dumps(profile.custom_notes),
            ),
        )
        conn.commit()

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
        """Asynchronously update structured user profile attributes in SQLite database."""
        async with self._lock:
            profile = self.get_profile_sync(user_id)
            if dietary_restrictions is not None:
                existing = {d.lower(): d for d in profile.dietary_restrictions}
                for diet in dietary_restrictions:
                    d_clean = diet.strip()
                    if d_clean and d_clean.lower() not in existing:
                        existing[d_clean.lower()] = d_clean
                profile.dietary_restrictions = sorted(
                    list(existing.values()), key=lambda x: x.lower()
                )
            if favorite_ingredients is not None:
                existing = {i.lower(): i for i in profile.favorite_ingredients}
                for ing in favorite_ingredients:
                    i_clean = ing.strip().title()
                    if i_clean and i_clean.lower() not in existing:
                        existing[i_clean.lower()] = i_clean
                profile.favorite_ingredients = sorted(
                    list(existing.values()), key=lambda x: x.lower()
                )
            if disliked_ingredients is not None:
                existing = {i.lower(): i for i in profile.disliked_ingredients}
                for ing in disliked_ingredients:
                    i_clean = ing.strip().title()
                    if i_clean and i_clean.lower() not in existing:
                        existing[i_clean.lower()] = i_clean
                profile.disliked_ingredients = sorted(
                    list(existing.values()), key=lambda x: x.lower()
                )
            if household_size is not None and household_size > 0:
                profile.household_size = household_size
            if favorite_recipes is not None:
                existing = {r.lower(): r for r in profile.favorite_recipes}
                for rec in favorite_recipes:
                    r_clean = rec.strip()
                    if r_clean and r_clean.lower() not in existing:
                        existing[r_clean.lower()] = r_clean
                profile.favorite_recipes = sorted(
                    list(existing.values()), key=lambda x: x.lower()
                )
            if custom_notes is not None:
                sanitized_notes = {
                    sanitize_text(k): sanitize_text(v)
                    for k, v in custom_notes.items()
                }
                profile.custom_notes.update(sanitized_notes)

            with self.db_manager.get_connection() as conn:
                self._save_profile_sync(conn, profile)
            return profile


class EpisodicActivityLogger:
    """Database-backed episodic event memory store for tracking kitchen actions and sustainability metrics."""

    def __init__(self, db_manager: DatabaseManager | None = None):
        self.db_manager = db_manager or DatabaseManager()
        self._lock = asyncio.Lock()

    def log_event_sync(
        self,
        user_id: str,
        event_type: str,
        details: dict[str, Any],
        impact_summary: str = "",
    ) -> EpisodicLogEntry:
        sanitized_details = sanitize_dict(details or {})
        sanitized_summary = sanitize_text(impact_summary or "")

        entry = EpisodicLogEntry(
            event_type=event_type,
            details=sanitized_details,
            impact_summary=sanitized_summary,
        )
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO episodic_logs (user_id, timestamp, event_type, details, impact_summary)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    entry.timestamp,
                    entry.event_type,
                    json.dumps(entry.details),
                    entry.impact_summary,
                ),
            )
            conn.commit()
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
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                if event_type:
                    cursor.execute(
                        """
                        SELECT timestamp, event_type, details, impact_summary
                        FROM episodic_logs
                        WHERE user_id = ? AND event_type = ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                        """,
                        (user_id, event_type, limit),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT timestamp, event_type, details, impact_summary
                        FROM episodic_logs
                        WHERE user_id = ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                        """,
                        (user_id, limit),
                    )
                rows = cursor.fetchall()
                return [
                    EpisodicLogEntry(
                        timestamp=row["timestamp"],
                        event_type=row["event_type"],
                        details=json.loads(row["details"] or "{}"),
                        impact_summary=row["impact_summary"],
                    )
                    for row in rows
                ]


class DatabaseMemoryService(BaseMemoryService):
    """Database-backed ADK BaseMemoryService implementation using SQLite."""

    def __init__(self, db_manager: DatabaseManager | None = None):
        self.db_manager = db_manager or DatabaseManager()

    async def add_session_to_memory(self, session: Any) -> None:
        """Adds all events in an ADK Session to persistent SQLite memory database."""
        app_name = getattr(session, "app_name", "app")
        user_id = getattr(session, "user_id", "default_user")
        events = getattr(session, "events", [])
        session_id = getattr(session, "id", None)
        await self.add_events_to_memory(
            app_name=app_name,
            user_id=user_id,
            events=events,
            session_id=session_id,
        )

    async def add_events_to_memory(
        self,
        *,
        app_name: str,
        user_id: str,
        events: list[Any],
        session_id: str | None = None,
        custom_metadata: dict[str, Any] | None = None,
    ) -> None:
        """Persists conversational events into SQLite conversation_memories table."""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            for event in events:
                timestamp = (
                    getattr(event, "timestamp", None)
                    or datetime.datetime.now(datetime.UTC).isoformat()
                )
                if isinstance(timestamp, (datetime.datetime, datetime.date)):
                    timestamp = timestamp.isoformat()
                else:
                    timestamp = str(timestamp)
                author = getattr(event, "author", "user") or "user"
                content_text = ""
                if hasattr(event, "content") and event.content:
                    if hasattr(event.content, "parts") and event.content.parts:
                        content_text = " ".join(
                            [
                                p.text
                                for p in event.content.parts
                                if getattr(p, "text", None)
                            ]
                        )
                elif isinstance(event, str):
                    content_text = event

                if content_text:
                    sanitized_content = sanitize_text(content_text)
                    cursor.execute(
                        """
                        INSERT INTO conversation_memories (
                            app_name, user_id, session_id, timestamp, author, content_text, custom_metadata
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            app_name,
                            user_id,
                            session_id or "",
                            timestamp,
                            str(author),
                            sanitized_content,
                            json.dumps(sanitize_dict(custom_metadata or {})),
                        ),
                    )
            conn.commit()

    async def search_memory(
        self,
        *,
        app_name: str,
        user_id: str,
        query: str,
    ) -> SearchMemoryResponse:
        """Searches persistent SQLite conversation memories for matching text entries."""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, timestamp, author, content_text, custom_metadata
                FROM conversation_memories
                WHERE user_id = ? AND content_text LIKE ?
                ORDER BY timestamp DESC
                LIMIT 10
                """,
                (user_id, f"%{query}%"),
            )
            rows = cursor.fetchall()
            memories = []
            for row in rows:
                content = types.Content(
                    role=row["author"] or "user",
                    parts=[types.Part.from_text(text=row["content_text"])],
                )
                memories.append(
                    MemoryEntry(
                        id=str(row["id"]),
                        timestamp=row["timestamp"],
                        author=row["author"],
                        content=content,
                        custom_metadata=json.loads(row["custom_metadata"] or "{}"),
                    )
                )
            return SearchMemoryResponse(memories=memories)


class AsyncMemoryPipeline:
    """Asynchronous Memory Manager providing database-backed persistent updates and background task execution."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_manager = DatabaseManager(db_path=db_path)
        self.profile_store = StructuredProfileStore(db_manager=self.db_manager)
        self.episodic_logger = EpisodicActivityLogger(db_manager=self.db_manager)
        self.adk_memory_service = DatabaseMemoryService(db_manager=self.db_manager)
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
