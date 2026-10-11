"""The assistant: learner question -> intent -> library retrieval -> deterministic checks -> Qwen explains.

Division of labour (see MATHENGINE_PROJECT_CONTEXT.md, section 6):
- Intent comes from knowledge.query.classify (rules, no model).
- Retrieval comes from the library index. Only reviewed records are used unless developer mode asks for drafts.
- Arithmetic is decided by SymPy. Qwen is never asked to calculate.
- Qwen receives a bounded excerpt of retrieved library text and is asked to explain it. It never sees the
  whole library, progress data, or hidden hints and answers.
- Any simple arithmetic claim in Qwen's reply is re-checked with SymPy. If one is wrong, Qwen's text is
  withheld and the learner sees the library text instead.
- Without Qwen (not running, model missing, timeout, bad reply), every library-based answer still works.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..knowledge.query import classify
from ..knowledge.retrieval import ContextBuilder, Retriever, SearchHit
from ..knowledge.store import KnowledgeStore
from ..math.checker import texts_equivalent
from ..math.evaluate import evaluate_expression
from ..math.expressions import ExpressionError
from .ollama import OllamaClient, OllamaUnavailableError

MAX_QUESTION_CHARS = 500
MAX_CONTEXT_CONCEPTS = 2  # at most this many records are sent to the model
MAX_CONTEXT_CHARS = 2400  # total library text sent to the model, across all records
MAX_REPLY_CHARS = 2000  # a model reply longer than this is cut and marked

SYSTEM_PROMPT = (
    "You are MathEngine's tutor. You explain math for a learner in plain English. "
    "Use ONLY the library text between the markers. If it does not answer the question, say that the library "
    "does not cover it. Never add facts, examples, numbers or calculations that are not in the library text. "
    "Do not do arithmetic yourself. Keep the answer under 150 words."
)

_CLAIM = re.compile(
    r"(?<![\w.])(-?\d+(?:\.\d+)?)\s*([+\-\u2212x\u00d7*\u00f7/])\s*(-?\d+(?:\.\d+)?)\s*=\s*(-?\d+(?:\.\d+)?)(?!\w|\.\d)"
)
_OPERATORS = {"+": "+", "-": "-", "\u2212": "-", "x": "*", "\u00d7": "*", "*": "*", "\u00f7": "/", "/": "/"}


@dataclass(frozen=True)
class Claim:
    text: str  # the claim as Qwen wrote it, e.g. "7 x 8 = 54"
    correct: bool | None  # SymPy's decision; None if it could not be decided


def arithmetic_claims(reply: str) -> list[Claim]:
    """Find simple two-number arithmetic claims ("7 x 8 = 56") and decide each one with SymPy."""
    claims: list[Claim] = []
    for match in _CLAIM.finditer(reply):
        left, op, right, result = match.groups()
        expression = f"({left}) {_OPERATORS[op]} ({right})"
        try:
            correct = texts_equivalent(expression, f"({result})")
        except Exception:  # defensive: an undecidable claim is reported, never trusted
            correct = None
        claims.append(Claim(text=match.group(0), correct=correct))
    return claims


def guard_reply(reply: str) -> dict[str, Any]:
    """Decide whether Qwen's reply may be shown. A single wrong arithmetic claim blocks the whole reply."""
    claims = arithmetic_claims(reply)
    wrong = [claim.text for claim in claims if claim.correct is False]
    undecided = [claim.text for claim in claims if claim.correct is None]
    if wrong or undecided:
        return {
            "allowed": False,
            "checked_claims": len(claims),
            "wrong_claims": wrong,
            "undecided_claims": undecided,
        }
    return {"allowed": True, "checked_claims": len(claims), "wrong_claims": [], "undecided_claims": []}


def build_prompt(question: str, library_text: str) -> str:
    return (
        "Library text (the only source you may use):\n<<<\n"
        f"{library_text}\n>>>\n\n"
        f"Learner question: {question}\n\n"
        "Explain the library text for this learner."
    )


def _hit_summary(hit: SearchHit) -> dict[str, str]:
    return {"id": hit.concept_id, "title": hit.title, "subject": hit.subject, "topic": hit.topic}


def _next_steps(store: KnowledgeStore, concept_ids: list[str]) -> list[dict[str, str]]:
    """Prerequisites first, then related records. Only ids that exist in the same index are returned."""
    steps: list[dict[str, str]] = []
    seen: set[str] = set(concept_ids)
    for concept_id in concept_ids:
        for related_id in store.direct_prerequisites(concept_id) + store.direct_related(concept_id):
            if related_id in seen:
                continue
            seen.add(related_id)
            try:
                concept = store.get(related_id, include_drafts=True)
            except Exception:
                continue
            steps.append({"id": concept.id, "title": concept.title})
            if len(steps) == 4:
                return steps
    return steps


def answer_question(
    question: str,
    *,
    store: KnowledgeStore,
    ollama: OllamaClient,
    include_drafts: bool = False,
    include_diagnostics: bool = False,
) -> dict[str, Any]:
    """Answer one learner question. Never raises for model problems; they are reported in `qwen`."""
    question = question.strip()[:MAX_QUESTION_CHARS]
    intent = classify(question)
    base: dict[str, Any] = {
        "question": question,
        "intent": intent.kind,
        "intent_reason": intent.reason,
        "includes_drafts": include_drafts,
    }

    if intent.kind == "clarify":
        return {
            **base,
            "status": "clarify",
            "message": "What would you like to learn? For example: 'multiplication facts', 'long division', "
            "or a calculation such as '7 x 8'.",
            "options": [],
            "qwen": _qwen_skipped("No topic was found to look up."),
        }

    if intent.kind == "solve":
        return {**base, **_solve(intent.expression or question)}

    retriever = Retriever(store)
    result = retriever.search(question, include_drafts=include_drafts, include_diagnostics=include_diagnostics)
    dev = {"retrieved_ids": [hit.concept_id for hit in result.hits]} if include_diagnostics else {}

    if result.status == "ambiguous":
        return {
            **base,
            **dev,
            "status": "clarify",
            "message": result.message,
            "options": [_hit_summary(hit) for hit in result.options],
            "qwen": _qwen_skipped("The question is ambiguous; the learner must choose a topic first."),
        }
    if result.status != "matches" or not result.hits:
        return {
            **base,
            **dev,
            "status": "not_found",
            "message": result.message,
            "suggestions": [_hit_summary(hit) for hit in result.suggestions],
            "qwen": _qwen_skipped("No relevant library record was found, so the model is not asked."),
        }

    concept_ids = [hit.concept_id for hit in result.hits[:MAX_CONTEXT_CONCEPTS]]
    per_record = MAX_CONTEXT_CHARS // len(concept_ids)
    builder = ContextBuilder(store)
    bundles = [
        builder.build(concept_id, max_chars=per_record, include_drafts=include_drafts) for concept_id in concept_ids
    ]
    library_text = "\n\n".join(bundle.text for bundle in bundles)
    library = [
        {"id": bundle.concept_id, "text": bundle.text, "sources": list(bundle.sources)} for bundle in bundles
    ]
    return {
        **base,
        **dev,
        "status": "answer",
        "concepts": [_hit_summary(hit) for hit in result.hits[: len(concept_ids)]],
        "library": library,
        "next_steps": _next_steps(store, concept_ids),
        "qwen": _ask_model(question, library_text, ollama),
    }


def _solve(expression: str) -> dict[str, Any]:
    if "=" in expression:
        return {
            "status": "unsupported",
            "message": "The assistant checks calculations such as '7 x 8' or '3/4 + 1/4'. It does not solve "
            "equations yet. Ask for the lesson on the equation's topic instead.",
            "qwen": _qwen_skipped("Equation solving is not available in the assistant."),
        }
    try:
        result = evaluate_expression(expression)
    except ExpressionError as exc:
        return {
            "status": "unsupported",
            "message": f"I could not check that calculation: {exc}",
            "qwen": _qwen_skipped("The expression could not be checked."),
        }
    return {
        "status": "verified",
        "expression": expression,
        "result": result.exact,
        "approximate": result.approximate,
        "verified_by": "SymPy",
        "qwen": _qwen_skipped("Calculations are checked by SymPy; the language model is not used for them."),
    }


def _qwen_skipped(reason: str) -> dict[str, Any]:
    return {"status": "not_used", "reason": reason}


def _ask_model(question: str, library_text: str, ollama: OllamaClient) -> dict[str, Any]:
    """Call the model with bounded context. Every failure becomes a status, never an exception."""
    base = {"model": ollama.model}
    try:
        reply = ollama.generate(build_prompt(question, library_text), system=SYSTEM_PROMPT)
    except OllamaUnavailableError as exc:
        return {**base, "status": "unavailable", "error": str(exc)}
    if len(reply) > MAX_REPLY_CHARS:
        reply = reply[:MAX_REPLY_CHARS].rstrip() + "..."
    verdict = guard_reply(reply)
    if not verdict["allowed"]:
        return {
            **base,
            "status": "blocked",
            "error": "The model's reply contained arithmetic that SymPy could not confirm, so it was not shown. "
            "The library text is shown instead.",
            "guard": verdict,
        }
    return {**base, "status": "ok", "text": reply, "guard": verdict}
