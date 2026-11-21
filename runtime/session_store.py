#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""最小 Session Store（内存 / 可选 file-backed）。

MVP 允许 memory/file-backed；不引入 PostgreSQL/Redis。
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from typing import Dict, List, Optional


class Session:
    def __init__(self, *, session_id: Optional[str] = None, persona_id: str = "default"):
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.persona_id = persona_id
        self.started_at = datetime.now().isoformat(timespec="seconds")
        self.turn_count = 0
        self.history: List[dict] = []          # {role, content, ts}
        self.last_topics: List[str] = []
        self.pending_confirmations: List[dict] = []
        self.corrections_made: List[dict] = []
        # Stage 5.9-B (F5): session-level correction overlay（只存在于当前 session，不写长期 persona_memory）。
        # 元素: {target_domain, target_kind, target_id, old_value, corrected_value, new_claim_id, source_turn, at}
        self.persona_overlay: List[dict] = []

    def add_turn(self, role: str, content: str):
        self.history.append({"role": role, "content": content,
                             "ts": datetime.now().isoformat(timespec="seconds")})
        # turn_count = 完成对话轮数（每轮 user+assistant 两条 → /2）
        self.turn_count = len(self.history) // 2

    def recent(self, n: int = 8) -> List[dict]:
        return self.history[-n:]

    def to_dict(self) -> dict:
        return {"session_id": self.session_id, "persona_id": self.persona_id,
                "started_at": self.started_at, "turn_count": self.turn_count,
                "history": self.history, "last_topics": self.last_topics,
                "pending_confirmations": self.pending_confirmations,
                "corrections_made": self.corrections_made,
                "persona_overlay": self.persona_overlay}

    @classmethod
    def from_dict(cls, d: dict) -> "Session":
        s = cls(session_id=d.get("session_id"), persona_id=d.get("persona_id", "default"))
        s.started_at = d.get("started_at", s.started_at)
        s.turn_count = d.get("turn_count", 0)
        s.history = d.get("history", [])
        s.last_topics = d.get("last_topics", [])
        s.pending_confirmations = d.get("pending_confirmations", [])
        s.corrections_made = d.get("corrections_made", [])
        s.persona_overlay = d.get("persona_overlay", [])
        return s


class SessionStore:
    """内存 store；可选 dir 做 file-backed 持久。"""

    def __init__(self, dir: Optional[str] = None):
        self._sessions: Dict[str, Session] = {}
        self.dir = dir
        if dir:
            os.makedirs(dir, exist_ok=True)
            self._load_all()

    def create(self, *, persona_id: str = "default", session_id: Optional[str] = None) -> Session:
        s = Session(session_id=session_id, persona_id=persona_id)
        self._sessions[s.session_id] = s
        self._persist(s)
        return s

    def get(self, session_id: str) -> Optional[Session]:
        return self._sessions.get(session_id)

    def get_or_create(self, session_id: Optional[str], *, persona_id: str = "default") -> Session:
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]
        return self.create(persona_id=persona_id, session_id=session_id)

    def save(self, s: Session):
        self._persist(s)

    def _persist(self, s: Session):
        if self.dir:
            p = os.path.join(self.dir, f"{s.session_id}.json")
            json.dump(s.to_dict(), open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    def _load_all(self):
        if not self.dir:
            return
        for fn in os.listdir(self.dir):
            if fn.endswith(".json"):
                try:
                    d = json.load(open(os.path.join(self.dir, fn), encoding="utf-8"))
                    s = Session.from_dict(d)
                    self._sessions[s.session_id] = s
                except (json.JSONDecodeError, KeyError):
                    continue
