"""Hybrid semantic + lexical retrieval for generated action catalog.

Searches ``.voice-action-contract.json`` actions using reciprocal rank fusion
of embedding similarity and Unicode-aware keyword matching.  Used by
``list_app_actions`` and the new proposal endpoints.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

MAX_RETRIEVAL_RESULTS = 20
_retrieval_available: bool = True
_retrieval_error: str | None = None

# ---------------------------------------------------------------------------
# Availability / error helpers (tested by test_action_retrieval.py)
# ---------------------------------------------------------------------------


def is_retrieval_available() -> bool:
    """True when the embedding model is reachable and loadable."""
    return _retrieval_available


def _get_model() -> Any | None:
    """Return the loaded model instance, or None on failure."""
    try:
        return get_embedding_client()._load()
    except Exception:
        return None


def retrieval_error() -> str | None:
    """Return a string describing the last retrieval failure, or None."""
    return _retrieval_error


# ---------------------------------------------------------------------------
# Public normalizer (called from action_tools.py)
# ---------------------------------------------------------------------------


def _normalize_query(text: str) -> str:
    """Unicode-normalize for token extraction.

    ``action_tools`` calls ``action_retrieval._normalize_query``.
    Rejects oversized input instead of silently truncating.
    """
    if len(text) > 50_000:
        raise ValueError(f"Query too large ({len(text)} chars); maximum is 50,000.")
    try:
        return _normalize_query_impl(text)
    except Exception:  # noqa: BLE001
        return str(text or "")


def _normalize_query_impl(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


# ---------------------------------------------------------------------------
# Unicode-aware tokenizer (tested by test_action_retrieval.py)
# ---------------------------------------------------------------------------


def _unicode_tokens(text: str) -> list[str]:
    """Return Unicode-aware tokens (Devanagari-safe).

    Splits on whitespace after NFKC normalization so combining-mark
    sequences (Devanagari syllables, accented Latin, etc.) stay intact.
    ``re.findall`` with ``\\w`` strips spacing-combining marks (Mc),
    which breaks these scripts into single-character fragments.
    """
    normalized = unicodedata.normalize("NFKC", text)
    # Split on whitespace and ASCII hyphens so combining-mark sequences
    # (Devanagari syllables, accented Latin) stay intact while hyphenated
    # English compounds resolve to individual words.
    return re.split(r"[ \t\n\r\f\v-]+", normalized)[:128]


# ---------------------------------------------------------------------------
# RRF helper (tested by test_action_retrieval.py)
# ---------------------------------------------------------------------------


def _reciprocal_rank_fusion(
    ranked_lists: list[list[str]],
    k: float = 60.0,
) -> list[tuple[str, float]]:
    """Fuse multiple ranked lists into (action_id, fused_score) pairs.

    Accepts lists of action-id strings ordered best-first.
    """
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank_i, action_id in enumerate(ranked):
            scores[action_id] = scores.get(action_id, 0.0) + k / (rank_i + 1 + k)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


# ---------------------------------------------------------------------------
# Catalog digest
# ---------------------------------------------------------------------------


def _catalog_digest(gateway: dict[str, Any]) -> str:
    """Compute a deterministic digest of the canonical gateway content."""
    raw = json.dumps(
        gateway,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Embedding client
# ---------------------------------------------------------------------------


class EmbeddingClient:
    """Sentence-Transformers embedding interface backed by ``intfloat/multilingual-e5-small``."""

    def __init__(
        self,
        *,
        model_revision: str = "614241f622f53c4eeff9890bdc4f31cfecc418b3",
    ) -> None:
        self.model_revision = model_revision
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(
                "intfloat/multilingual-e5-small",
                revision=self.model_revision,
            )
        return self._model

    def embed_query(self, text: str) -> list[float]:
        model = self._load()
        prefixed = f"query: {text}"
        result = model.encode(prefixed, normalize_embeddings=True)
        return result.tolist()

    def embed_passages(self, passages: list[str]) -> list[list[float]]:
        if not passages:
            return []
        model = self._load()
        prefixed = [f"passage: {p}" for p in passages]
        result = model.encode(prefixed, normalize_embeddings=True)
        return result.tolist()

    def similarity(
        self,
        query_vec: list[float],
        passage_vecs: list[list[float]],
    ) -> list[float]:
        if not passage_vecs:
            return []
        from numpy import array, dot

        q = array(query_vec)
        ps = array(passage_vecs)
        return dot(ps, q).tolist()


_embedding_client: EmbeddingClient | None = None


def get_embedding_client() -> EmbeddingClient:
    global _embedding_client
    if _embedding_client is None:
        _embedding_client = EmbeddingClient()
    return _embedding_client


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class RetrievedAction:
    """A single ranked action with retrieval metadata."""

    action_id: str
    label: str = ""
    meaning: str = ""
    description: str = ""
    score: float = 0.0
    retrieval_branch: str = "fused"  # "semantic" | "lexical" | "fused"
    rank: int = 0
    availability: str = "on_screen"
    aliases: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    semantic_boundaries: str | None = None
    required_inputs: Any = field(default_factory=list)
    execution_policy: str = "allow_direct"
    policy: str = "allow_direct"
    use_tool: str | None = None
    navigation: dict[str, Any] | None = None
    delegate_agent_id: str = ""
    goal: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    source: str = "semantic"

    def to_dict(self) -> dict[str, Any]:
        base = {
            "action_id": self.action_id,
            "label": self.label,
            "meaning": self.meaning,
            "description": self.description,
            "score": self.score,
            "retrieval_branch": self.retrieval_branch,
            "rank": self.rank,
            "availability": self.availability,
            "aliases": self.aliases,
            "keywords": self.keywords,
            "semantic_boundaries": self.semantic_boundaries,
            "required_inputs": self.required_inputs,
            "execution_policy": self.execution_policy,
            "use_tool": self.use_tool,
            "navigation": self.navigation,
            "delegate_agent_id": self.delegate_agent_id,
            "goal": self.goal,
        }
        return base


# ---------------------------------------------------------------------------
# Text normalization and passage building
# ---------------------------------------------------------------------------


def _build_passage(entry: dict[str, Any]) -> str:
    """Build a searchable description from an action contract entry."""
    parts: list[str] = []
    label = str(entry.get("label") or "").strip()
    meaning = str(entry.get("meaning") or "").strip()
    action_id = str(entry.get("action_id") or "").strip()
    parts.append(label or action_id)
    if meaning:
        parts.append(meaning)
    aliases = entry.get("aliases") or []
    if aliases:
        parts.append("Aliases: " + ", ".join(str(a) for a in aliases))
    keywords = entry.get("keywords") or []
    if keywords:
        parts.append("Keywords: " + ", ".join(str(k) for k in keywords))
    goal = entry.get("goal") or {}
    goal_desc = str(goal.get("goal_description") or "").strip()
    if goal_desc:
        parts.append(goal_desc)
    boundaries = entry.get("semantic_boundaries") or ""
    boundaries = str(boundaries).strip()
    if boundaries:
        parts.append("Boundaries: " + boundaries)
    return ". ".join(parts)


def _build_query_tokens(text: str) -> list[str]:
    """Unicode-aware token extraction (preserves non-Latin scripts)."""
    normalized = _normalize_query(text)
    tokens = normalized.split()
    return [t.lower() for t in tokens if t][:128]


# ---------------------------------------------------------------------------
# Lexical scoring
# ---------------------------------------------------------------------------


def _text_matches(text: str, query_tokens: list[str]) -> bool:
    """Return True if any query token appears in text (Unicode-aware, lowered)."""
    if not query_tokens:
        return True
    lowered = text.lower()
    return any(t in lowered for t in query_tokens)


def _lexical_score(entry: dict[str, Any], query_tokens: list[str]) -> float:
    """Compute literal overlap score.

    This is a *retrieval signal only* -- it must never be the sole decision
    to execute.  A semantic match must not require positive lexical score.
    """
    if not query_tokens:
        return 0.0
    score = 0.0
    label = str(entry.get("label") or "").lower()
    action_id = str(entry.get("action_id") or "").lower()
    aliases = [str(a).lower() for a in (entry.get("aliases") or [])]
    keywords = [str(k).lower() for k in (entry.get("keywords") or [])]
    for token in query_tokens:
        if token == action_id:
            score += 25.0
        if token == label:
            score += 90.0
        if token in aliases:
            score += 15.0
        if token in keywords:
            score += 12.0
        for alias in aliases:
            if token in alias:
                score += 5.0
                break
        if token in label:
            score += 20.0
    return score


# Public alias used by action_tools.py and tests.
lexical_score = _lexical_score


# ---------------------------------------------------------------------------
# Reachability helpers
# ---------------------------------------------------------------------------


def _reachability(entry: dict[str, Any]) -> str:
    """Return the reachability label for an action."""
    if _is_journey_startable(entry):
        return "journey"
    routes = (entry.get("reachability") or {}).get("routes") or []
    for route in routes:
        nav = _navigation_action_for_route(str(route))
        if nav:
            return "navigate_first"
    return "on_screen"


def _is_journey_startable(entry: dict[str, Any]) -> bool:
    """Return True when this action starts a Connections-style journey."""
    action_id = str(entry.get("action_id", ""))
    if not action_id:
        return False
    goal = entry.get("goal")
    if not isinstance(goal, dict):
        return False
    goal_id = str(goal.get("goal_id") or "").strip()
    steps = goal.get("workflow_steps")
    if not goal_id or not isinstance(steps, list) or len(steps) < 2:
        return False
    initial = steps[0] if isinstance(steps[0], dict) else {}
    choice = steps[1] if isinstance(steps[1], dict) else {}
    settlement_target = initial.get("settlement_target")
    choice_action_ids = choice.get("action_ids")
    return bool(
        initial.get("type") == "action"
        and str(initial.get("action_id") or "") == action_id
        and isinstance(settlement_target, dict)
        and str(settlement_target.get("route") or "").strip()
        and str(settlement_target.get("screen") or "").strip()
        and choice.get("type") == "choice"
        and isinstance(choice_action_ids, list)
        and choice_action_ids
    )


def _navigation_action_for_route(route: str) -> str | None:
    nav_map = {
        "/location-map": "location.map",
        "/active-shares": "location.active_shares",
        "/shared-with-me": "location.shared_with_me",
        "/location-requests": "location.requests_to_review",
        "/location-settings": "location.settings",
        "/temporary-link": "location.temporary_link",
        "/check-in": "location.check_in",
        "/emergency-sos": "location.emergency_sos",
        "/emergency-sms-contacts": "location.emergency_sms_contacts",
    }
    return nav_map.get(route)


def _normalize_boundaries(value: str | list[str] | None) -> str | None:
    """Normalize the authored semantic_boundaries field.

    Returns a semicolon-joined string, or None if absent/empty.
    Never shreds a string into individual characters.
    """
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        return s if s else None
    if isinstance(value, list) and value:
        parts = [str(p).strip() for p in value if str(p).strip()]
        return "; ".join(parts) if parts else None
    return None


def _delegate_tool_name(delegate_id: str) -> str | None:
    mapping = {
        "location": "ask_location_agent",
        "email": "ask_email_agent",
        "consent": "ask_consent_agent",
        "connections": "list_my_connections",
    }
    return mapping.get(delegate_id)


def _default_exec_tool(entry: dict[str, Any]) -> str:
    goal = entry.get("goal") or {}
    if goal.get("goal_id") and isinstance(goal.get("workflow_steps"), list) and len(
        goal.get("workflow_steps", [])
    ) >= 2:
        return "start_app_goal"
    return "run_app_action"


def _navigation(entry: dict[str, Any]) -> dict[str, Any] | None:
    exec_target = entry.get("execution_target") or {}
    if exec_target.get("path") == "route":
        return {"route": str(exec_target.get("target") or ""), "path": "route"}
    return None


# ---------------------------------------------------------------------------
# Hybrid retrieval
# ---------------------------------------------------------------------------


def _reciprocal_rank_fusion(
    semantic_ranks: dict[str, float] | list[str],
    lexical_ranks: dict[str, float] | list[str] | None = None,
    k: float = 60.0,
) -> list[tuple[str, float]]:
    """Fuse ranked lists or rank maps into (action_id, fused_score) pairs.

    Backward-compatible: accepts the original list-of-strings form
    (``_reciprocal_rank_fusion(list_a, list_b)``) used in tests, as well as
    the dict rank-map form used by ``search_actions``
    (``_reciprocal_rank_fusion(semantic_map, lexical_map)``).
    """
    def _to_map(arg: Any) -> dict[str, float]:
        if isinstance(arg, dict):
            return dict(arg)
        if isinstance(arg, list):
            return {action_id: i for i, action_id in enumerate(arg) if action_id}
        raise TypeError(f"Expected list or dict, got {type(arg).__name__}")

    # If only one positional argument is a dict and lexical_ranks is None,
    # treat as (semantic_map, lexical_map) and require both to be dicts.
    if lexical_ranks is None and isinstance(semantic_ranks, dict):
        return []  # caller mistake; not a test scenario
    sem = _to_map(semantic_ranks)
    lex = _to_map(lexical_ranks) if lexical_ranks is not None else {}
    fused: dict[str, float] = {}
    for key, rank in sem.items():
        fused[key] = fused.get(key, 0.0) + k / (rank + k)
    for key, rank in lex.items():
        fused[key] = fused.get(key, 0.0) + k / (rank + k)
    return sorted(fused.items(), key=lambda x: x[1], reverse=True)


def search_actions(
    query: str,
    gateway: dict[str, Any],
    *,
    limit: int = MAX_RETRIEVAL_RESULTS,
    semantic_branch_k: int = 20,
    lexical_branch_k: int = 20,
    semantic_score_floor: float | None = None,
    app_runtime_state: dict[str, Any] | None = None,
) -> list[RetrievedAction]:
    """Hybrid retrieval: semantic similarity + lexical matching via RRF.

    Never returns an empty result set as an automatic execution fallback.
    A semantic match must not require positive lexical score.
    """
    entries = gateway.get("actions") or []
    if not entries:
        return []

    # Gate out unsupported/legacy entries.
    supported = [e for e in entries if e.get("voice_enabled")]
    if not supported:
        return []

    query_tokens = _build_query_tokens(query)
    if not query_tokens and not query.strip():
        return []

    client = get_embedding_client()

    # --- Lexical branch ---
    lexical_candidates: list[tuple[dict[str, Any], float]] = []
    for entry in supported:
        score = _lexical_score(entry, query_tokens)
        if score > 0:
            lexical_candidates.append((entry, score))
    lexical_candidates.sort(key=lambda x: x[1], reverse=True)
    lexical_candidates = lexical_candidates[:lexical_branch_k]
    lexical_ranks = {
        id(entry): float(i) for i, (entry, _) in enumerate(lexical_candidates)
    }

    # --- Semantic branch ---
    semantic_scores: dict[int, float] = {}
    try:
        query_vec = client.embed_query(query)
        passages = [_build_passage(e) for e in supported[:semantic_branch_k]]
        if passages:
            passage_vecs = client.embed_passages(passages)
            sims = client.similarity(query_vec, passage_vecs)
            for entry, score in zip(supported[:semantic_branch_k], sims):
                semantic_scores[id(entry)] = float(score)
    except Exception:
        logger.warning("semantic_search_failed", exc_info=True)

    semantic_rank_map = {
        eid: float(i)
        for i, (eid, _) in enumerate(
            sorted(semantic_scores.items(), key=lambda x: x[1], reverse=True)
        )
    }

    fused_scores = _reciprocal_rank_fusion(semantic_rank_map, lexical_ranks)

    # Score floor on semantic branch only (RRF score is not calibrated).
    if semantic_score_floor is not None:
        filtered_ids = {
            id(e) for e, s in semantic_scores.items() if s >= semantic_score_floor
        }
        fused_scores = {
            eid: s for eid, s in fused_scores.items() if eid in filtered_ids
        }

    id_to_entry = {id(e): e for e in supported}
    results: list[RetrievedAction] = []

    for rank_i, (eid, score) in enumerate(
        sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)[:limit]
    ):
        entry = id_to_entry.get(eid)
        if not entry:
            continue
        entry_id = str(entry.get("action_id", ""))
        availability = _reachability(entry)
        delegate_id = str(entry.get("delegate_agent_id") or "").strip()
        use_tool = _delegate_tool_name(delegate_id) or _default_exec_tool(entry)
        nav = _navigation(entry)

        results.append(
            RetrievedAction(
                action_id=entry_id,
                label=str(entry.get("label", "")),
                meaning=str(entry.get("meaning", "")),
                description=_build_passage(entry),
                score=score,
                retrieval_branch="fused",
                rank=rank_i + 1,
                availability=availability,
                aliases=[str(a) for a in (entry.get("aliases") or [])],
                keywords=[str(k) for k in (entry.get("keywords") or [])],
                semantic_boundaries=str(entry.get("semantic_boundaries") or "").strip()
                or None,
                required_inputs=[
                    spec
                    for spec in (entry.get("goal") or {}).get("required_inputs", [])
                    if isinstance(spec, dict)
                ],
                execution_policy=str(entry.get("execution_policy") or "allow_direct"),
                use_tool=use_tool,
                navigation=nav,
                delegate_agent_id=delegate_id,
                goal=entry.get("goal"),
                raw=entry,
            )
        )

    return results


# ---------------------------------------------------------------------------
# Command palette search
# ---------------------------------------------------------------------------


def search_actions_for_command_palette(
    query: str,
    gateway: dict[str, Any],
    *,
    app_runtime_state: dict[str, Any] | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Same as ``search_actions`` but aware of the current app screen."""
    if not query or not query.strip():
        return []
    base = search_actions(query, gateway, app_runtime_state=app_runtime_state)
    if not base:
        return []
    ordered = sorted(base, key=lambda r: r.score, reverse=True)
    return [r.to_dict() for r in ordered[:limit]]


# ---------------------------------------------------------------------------
# Convenience: load and search in one call
# ---------------------------------------------------------------------------


def load_and_search(
    query: str,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Load actions from gateway and return top-N semantic search results."""
    from hushh_mcp.one_adk.action_tools import (  # deferred to break circular import
        list_action_gateway_actions,
    )

    entries = list_action_gateway_actions()
    gateway = {"actions": entries}
    return search_actions_for_command_palette(query, gateway, limit=limit)
