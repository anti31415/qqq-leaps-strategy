from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


def default_state(strategy_version: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "strategy_version": strategy_version,
        "managed_leaps": {},
        "pending_orders": [],
        "entry_history": [],
        "notes": [],
    }


def load_state(path: Path, strategy_version: str) -> dict[str, Any]:
    if not path.exists():
        return default_state(strategy_version)
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("strategy_version") != strategy_version:
        upgraded = default_state(strategy_version)
        upgraded.update(state)
        upgraded["strategy_version"] = strategy_version
        state = upgraded
    state.setdefault("managed_leaps", {})
    state.setdefault("pending_orders", [])
    state.setdefault("entry_history", [])
    state.setdefault("notes", [])
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def clone_state(state: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(state)

