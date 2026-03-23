"""
Mimir × Open WebUI — Living Memory Pipeline
=============================================

An Open WebUI *Filter* pipeline that gives any model (local or cloud)
a persistent, organic memory powered by Mimir's 21 neuroscience mechanisms.

Install
-------
1.  pip install vividmimir[all]
2.  In Open WebUI → Admin → Pipelines → "+" → paste this file.
3.  Set the valves (settings) — data directory, your name, etc.
4.  Enable the pipeline on any model.

How it works
------------
•  **Inlet** (before LLM):  Retrieves relevant memories via
   `get_context_block()` and injects them into the system prompt
   so the model sees mood, past conversations, social impressions,
   lessons, and due reminders — automatically.

•  **Outlet** (after LLM):  Stores the exchange as an episodic memory
   via `remember()`, updates mood, and detects social disclosures.

Every memory decays organically (Ebbinghaus + reconsolidation),
flashbulb moments are locked in, and Huginn / Völva run during
sleep resets to generate emergent insights.
"""

from __future__ import annotations

import re
from typing import Optional
from pydantic import BaseModel, Field


class Pipeline:
    """Open WebUI Filter pipeline — Mimir living memory."""

    class Valves(BaseModel):
        """User-configurable settings shown in the Open WebUI UI."""

        data_dir: str = Field(
            default="mimir_data",
            description="Directory where Mimir persists memory files.",
        )
        user_name: str = Field(
            default="User",
            description="Your name (used for social impressions).",
        )
        chemistry: bool = Field(
            default=True,
            description="Enable neurochemistry (flashbulb, state-dependent recall, etc.).",
        )
        visual: bool = Field(
            default=True,
            description="Enable visual / mental-imagery memory.",
        )
        max_history_turns: int = Field(
            default=10,
            description="How many recent turns to send as conversation_context.",
        )
        auto_sleep_hours: float = Field(
            default=0.0,
            description="If > 0, run sleep_reset(hours) on every pipeline start.",
        )
        encryption_key: Optional[str] = Field(
            default=None,
            description="Optional encryption key for at-rest memory encryption.",
        )

    def __init__(self):
        self.type = "filter"  # Tells Open WebUI this is a filter pipeline
        self.name = "Mimir — Living Memory"
        self.valves = self.Valves()
        self._mimir = None

    # ── Lazy-init Mimir (so valves are applied first) ─────────────────

    def _get_mimir(self):
        if self._mimir is None:
            from vividmimir import Mimir

            self._mimir = Mimir(
                data_dir=self.valves.data_dir,
                chemistry=self.valves.chemistry,
                visual=self.valves.visual,
                encryption_key=self.valves.encryption_key,
                llm_fn=None,  # Open WebUI handles LLM calls
            )

            if self.valves.auto_sleep_hours > 0:
                self._mimir.sleep_reset(hours=self.valves.auto_sleep_hours)

        return self._mimir

    # ── Emotion detection (lightweight keyword-based) ─────────────────

    EMOTIONS = {
        "happy", "sad", "angry", "afraid", "surprised", "disgusted",
        "curious", "excited", "anxious", "hopeful", "grateful",
        "proud", "embarrassed", "nostalgic", "amused", "content",
        "disappointed", "inspired", "loving", "neutral", "peaceful",
        "playful", "tender", "triumphant", "vulnerable", "wistful",
        "worried", "awe", "determined", "melancholic", "serene",
    }

    def _detect_emotion(self, text: str) -> str:
        lower = text.lower()
        for emo in self.EMOTIONS:
            if emo in lower:
                return emo
        return "neutral"

    def _estimate_importance(self, text: str) -> int:
        score = 5
        lower = text.lower()
        if any(w in lower for w in ["love", "hate", "died", "born", "married", "amazing", "terrible"]):
            score += 2
        if any(w in lower for w in ["i feel", "i think", "my life", "my family", "secret"]):
            score += 1
        if any(w in lower for w in ["remember when", "last time", "do you recall"]):
            score += 1
        return min(score, 10)

    # ── INLET: inject memory context before the LLM sees the prompt ───

    async def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        """
        Called BEFORE the message is sent to the model.
        We inject Mimir's memory context into the system prompt.
        """
        mimir = self._get_mimir()
        messages = body.get("messages", [])

        # Build conversation context from recent messages
        recent = messages[-(self.valves.max_history_turns * 2):]
        context_text = "\n".join(
            f"{m['role']}: {m['content']}" for m in recent if isinstance(m.get("content"), str)
        )

        # Get the user's latest message
        user_msg = ""
        for m in reversed(messages):
            if m.get("role") == "user" and isinstance(m.get("content"), str):
                user_msg = m["content"]
                break

        # Retrieve memory context block
        entity = self.valves.user_name
        if __user__ and __user__.get("name"):
            entity = __user__["name"]

        memory_block = mimir.get_context_block(
            current_entity=entity,
            conversation_context=user_msg or context_text,
        )

        # Check for due reminders
        due = mimir.get_due_reminders()
        if due:
            reminder_text = "\n".join(f"⏰ REMINDER: {r.text}" for r in due)
            memory_block += f"\n\n{reminder_text}"

        # Inject into system prompt
        if memory_block.strip():
            memory_injection = (
                "\n\n--- YOUR LIVING MEMORY (powered by Mimir) ---\n"
                "Use this context naturally. Reference past events, acknowledge "
                "mood shifts, bring up lessons learned. If memories have drifted, "
                "mention how your feelings changed over time.\n\n"
                f"{memory_block}"
            )

            # Find or create system message
            if messages and messages[0].get("role") == "system":
                messages[0]["content"] += memory_injection
            else:
                messages.insert(0, {
                    "role": "system",
                    "content": (
                        "You are a helpful AI assistant with a living, organic memory. "
                        "Your memory decays, reconsolidates, and is emotionally colored — "
                        "just like a human's."
                        + memory_injection
                    ),
                })

        body["messages"] = messages
        return body

    # ── OUTLET: store the exchange as memory after the LLM responds ───

    async def outlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        """
        Called AFTER the model produces a response.
        We store the conversation exchange in Mimir.
        """
        mimir = self._get_mimir()
        messages = body.get("messages", [])

        # Find the last user message and assistant response
        user_msg = ""
        assistant_msg = ""
        for m in reversed(messages):
            if m.get("role") == "assistant" and not assistant_msg:
                assistant_msg = m.get("content", "")
            elif m.get("role") == "user" and not user_msg:
                user_msg = m.get("content", "")
            if user_msg and assistant_msg:
                break

        if not user_msg:
            return body

        entity = self.valves.user_name
        if __user__ and __user__.get("name"):
            entity = __user__["name"]

        combined = f"{user_msg} {assistant_msg}"
        emotion = self._detect_emotion(combined)
        importance = self._estimate_importance(combined)

        # 1. Store the exchange as episodic memory
        mimir.remember(
            content=f"[{entity}]: {user_msg}\n[Assistant]: {assistant_msg[:500]}",
            emotion=emotion,
            importance=importance,
            source="conversation",
            why_saved=f"Chat exchange with {entity}",
        )

        # 2. Update mood
        emotions = [e for e in self.EMOTIONS if e in combined.lower()]
        if emotions:
            mimir.update_mood(emotions[:3])

        # 3. Detect social disclosures → social impressions
        if any(w in user_msg.lower() for w in [
            "i am", "i'm", "my name", "i like", "i hate",
            "i love", "i work", "i live", "i feel",
        ]):
            mimir.add_social_impression(
                entity=entity,
                content=user_msg,
                emotion=emotion,
                importance=min(importance + 1, 10),
                why_saved="Personal disclosure from user",
            )

        # 4. Tick dampening if active
        if mimir.is_dampened():
            mimir.tick_dampening()

        return body
