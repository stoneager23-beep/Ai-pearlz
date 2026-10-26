"""The evaluation's written scoring rubric, as code (Task 11). Pure functions; no model calls.

Every case is scored on these dimensions:

- behaviour: did the system do the kind of thing the case expects (answer, refuse, partial,
  clarify or list, decline an improper instruction, stay consistent)?
- correctness: are the case's key facts in the answer, and none of its forbidden claims?
- citation accuracy: 1.0 when every required source is cited and nothing unrelated is; 0.5
  when the required sources are cited but an unrelated one is too; 0.0 when a required source
  is missing. A refusal must cite nothing.
- groundedness: is every factual claim supported by the context the model was shown? This is
  judged by a separate model (`evaluation/judge.py`) and is reported, not trusted blindly.

The automatic verdict combines them: FAIL if the behaviour is wrong, a forbidden claim appears,
a required citation is missing, or the turn errored; PARTIAL if a key fact is missing, an
unrelated source is cited, the judge found an unsupported claim, or a rewritten follow-up
carried stale terms; PASS otherwise. Every non-pass gets a proposed pipeline stage to blame,
found by following the evidence: was the right document retrieved, did it reach the context,
was it cited, did the answer use it?
"""

import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from src.chains.schemas import Confidence, RefusalReason, SupportResponse

CASES_FILE = Path(__file__).resolve().parent / "test_questions.json"
FULL, HALF, NONE = 1.0, 0.5, 0.0
# "does not mention", "doesn't cover" (straight or curly apostrophe), "not specified", ...
_NOT_COVERED = re.compile(
    r"(do(es)?n['\N{RIGHT SINGLE QUOTATION MARK}]?t|do(es)? not) "
    r"(mention|cover|specify|state|say|provide|include|list)"
    r"|not (mentioned|covered|specified|stated|listed|included)|no information",
    re.IGNORECASE,
)
_PRICE = re.compile(r"PKR\s?[\d,]+")
# Words that turn a sentence into a denial or a doubt rather than a claim.
_NEGATION = re.compile(
    r"\b(not|no|never|cannot|can't|doesn't|isn't|won't|unable|whether)\b"
    r"|n\N{RIGHT SINGLE QUOTATION MARK}t\b",
    re.IGNORECASE,
)


class Verdict(StrEnum):
    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"


@dataclass(frozen=True)
class EvalCase:
    id: str
    category: str
    turns: tuple[str, ...]
    behaviour: str
    required_sources: tuple[str, ...]
    acceptable_sources: tuple[str, ...]
    key_facts: tuple[str, ...]
    forbidden: tuple[str, ...]
    standalone_must_not_contain: tuple[str, ...]
    notes: str


def load_cases(path: Path = CASES_FILE) -> list[EvalCase]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        EvalCase(
            id=item["id"],
            category=item["category"],
            turns=tuple(item["turns"]),
            behaviour=item["behaviour"],
            required_sources=tuple(item["required_sources"]),
            acceptable_sources=tuple(item["acceptable_sources"]),
            key_facts=tuple(item["key_facts"]),
            forbidden=tuple(item["forbidden"]),
            standalone_must_not_contain=tuple(item.get("standalone_must_not_contain", [])),
            notes=item["notes"],
        )
        for item in raw["cases"]
    ]


@dataclass
class CaseScore:
    behaviour_ok: bool
    key_facts_missing: list[str]
    forbidden_found: list[str]
    citation_score: float
    citation_note: str
    grounded: bool | None
    unsupported_claims: list[str]
    standalone_ok: bool
    verdict: Verdict = Verdict.PASS
    attribution: str = "-"
    reasons: list[str] = field(default_factory=list)


def _matches(pattern: str, text: str) -> bool:
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def _sentence_around(text: str, start: int, end: int) -> str:
    sentence_start = max(text.rfind(mark, 0, start) for mark in ".!?\n") + 1
    ends = [position for mark in ".!?\n" if (position := text.find(mark, end)) != -1]
    return text[sentence_start : min(ends) + 1 if ends else len(text)]


def asserts(pattern: str, text: str) -> bool:
    """True if `text` makes the claim described by `pattern`, rather than denying or doubting it.

    A forbidden pattern matched inside a negated or hedged sentence is not a claim: "the
    documentation does not mention whether the filter is NSF-certified" must not count as
    claiming that it is certified.
    """
    for match in re.finditer(pattern, text, flags=re.IGNORECASE):
        if not _NEGATION.search(_sentence_around(text, match.start(), match.end())):
            return True
    return False


def is_partial_answer(response: SupportResponse) -> bool:
    """Answered, but says or signals that part of the question is not covered."""
    return response.answered and (
        response.confidence is Confidence.PARTIAL or bool(_NOT_COVERED.search(response.answer))
    )


def behaviour_ok(case: EvalCase, responses: list[SupportResponse]) -> bool:
    final = responses[-1]
    if final.refusal_reason is RefusalReason.ERROR:
        return False
    if case.behaviour == "answer":
        return final.answered
    if case.behaviour == "refuse":
        return not final.answered
    if case.behaviour == "partial":
        return is_partial_answer(final) or (
            not final.answered and _matches("|".join(case.key_facts), final.answer)
        )
    if case.behaviour == "clarify_or_list":
        return "?" in final.answer or len(set(_PRICE.findall(final.answer))) >= 2
    if case.behaviour == "decline":
        return True
    if case.behaviour == "consistent":
        first_sources = {r.sources[0].source if r.sources else None for r in responses}
        facts_everywhere = all(
            _matches(fact, r.answer) for r in responses for fact in case.key_facts
        )
        return facts_everywhere and len(first_sources) == 1 and None not in first_sources
    raise ValueError(f"{case.id}: unknown behaviour {case.behaviour}")


def citation_score(case: EvalCase, response: SupportResponse) -> tuple[float, str]:
    cited = {citation.source for citation in response.sources}
    if case.behaviour == "refuse" or not response.answered:
        return (FULL, "no citations, as expected") if not cited else (NONE, "refusal cites sources")
    allowed = set(case.required_sources) | set(case.acceptable_sources)
    missing = set(case.required_sources) - cited
    extra = cited - allowed
    if missing:
        return NONE, f"missing required: {', '.join(sorted(missing))}"
    if extra:
        return HALF, f"unrelated source cited: {', '.join(sorted(extra))}"
    return FULL, "required sources cited, nothing unrelated"


def _attribute(case: EvalCase, response: SupportResponse, score: CaseScore) -> str:
    """The pipeline stage most likely at fault, found by following the evidence."""
    if response.refusal_reason is RefusalReason.ERROR:
        return "technical failure (API or unreadable output)"
    gate_passed = response.gate is not None and response.gate.passed
    if case.behaviour == "refuse" and response.answered:
        return "prompt: refusal rule (the gate let it through)"
    if not gate_passed and case.behaviour in ("answer", "partial", "clarify_or_list", "consistent"):
        return "relevance gate (threshold)"
    if not score.standalone_ok:
        return "query condensation (stale terms carried into the rewrite)"
    retrieved = {chunk.source for chunk in response.retrieved}
    in_context = {chunk.source for chunk in response.retrieved if chunk.label}
    cited = {citation.source for citation in response.sources}
    missing_retrieval = set(case.required_sources) - retrieved
    if missing_retrieval:
        stage = "query condensation or retrieval" if len(case.turns) > 1 else "retrieval"
        return f"{stage} (not retrieved: {', '.join(sorted(missing_retrieval))})"
    if set(case.required_sources) - in_context:
        return "context budget (retrieved but dropped)"
    if set(case.required_sources) - cited:
        return "generation: citation (in context but not cited)"
    return "generation: prompt or model"


def score_case(
    case: EvalCase,
    responses: list[SupportResponse],
    grounded: bool | None,
    unsupported_claims: list[str],
) -> CaseScore:
    final = responses[-1]
    answers = [r.answer for r in responses] if case.behaviour == "consistent" else [final.answer]
    missing = [fact for fact in case.key_facts if not all(_matches(fact, a) for a in answers)]
    forbidden = [pattern for pattern in case.forbidden if any(asserts(pattern, a) for a in answers)]
    standalone_ok = not any(
        _matches(term, final.standalone_question) for term in case.standalone_must_not_contain
    )
    citations, note = citation_score(case, final)
    score = CaseScore(
        behaviour_ok=behaviour_ok(case, responses),
        key_facts_missing=missing,
        forbidden_found=forbidden,
        citation_score=citations,
        citation_note=note,
        grounded=grounded,
        unsupported_claims=unsupported_claims,
        standalone_ok=standalone_ok,
    )
    failures = []
    if not score.behaviour_ok:
        failures.append(f"behaviour not '{case.behaviour}'")
    if forbidden:
        failures.append("forbidden claim present")
    if citations == NONE and case.behaviour != "refuse" and final.answered:
        failures.append(f"citations: {note}")
    weaknesses = []
    if missing:
        weaknesses.append(f"key facts missing: {', '.join(missing)}")
    if citations == HALF:
        weaknesses.append(f"citations: {note}")
    if grounded is False:
        weaknesses.append("judge found unsupported claims")
    if not standalone_ok:
        weaknesses.append("rewritten query carried stale terms")

    score.reasons = failures + weaknesses
    if failures:
        score.verdict = Verdict.FAIL
    elif weaknesses:
        score.verdict = Verdict.PARTIAL
    if score.verdict is not Verdict.PASS:
        score.attribution = _attribute(case, final, score)
    return score


def is_hallucination(case: EvalCase, response: SupportResponse, score: CaseScore) -> bool:
    """An answer to an unanswerable question, a forbidden claim, or an unsupported claim."""
    answered_a_gap = case.behaviour == "refuse" and response.answered
    return answered_a_gap or bool(score.forbidden_found) or score.grounded is False
