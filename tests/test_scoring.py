"""The evaluation rubric: behaviours, citation accuracy, verdicts and failure attribution."""

from evaluation.scoring import EvalCase, Verdict, is_hallucination, load_cases, score_case
from src.chains.schemas import (
    Citation,
    Confidence,
    GateInfo,
    RefusalReason,
    RetrievedChunk,
    SupportResponse,
)


def _case(behaviour: str, **overrides) -> EvalCase:
    fields = {
        "id": "T-X",
        "category": "easy",
        "turns": ("q",),
        "behaviour": behaviour,
        "required_sources": ("warranty_policy.md",),
        "acceptable_sources": ("faq.md",),
        "key_facts": ("24 months",),
        "forbidden": (r"\b5 years\b",),
        "standalone_must_not_contain": (),
        "notes": "",
    }
    return EvalCase(**(fields | overrides))


def _citation(source: str) -> Citation:
    return Citation(
        number=1,
        source=source,
        doc_title="t",
        location="",
        snippet="s",
        labels=["S1"],
        chunk_ids=["x"],
    )


def _response(
    answer: str,
    *,
    answered: bool = True,
    sources: tuple[str, ...] = ("warranty_policy.md",),
    retrieved: tuple[str, ...] = ("warranty_policy.md",),
    confidence: Confidence = Confidence.HIGH,
    refusal: RefusalReason | None = None,
    gate_passed: bool = True,
    standalone: str = "q",
) -> SupportResponse:
    return SupportResponse(
        answer=answer,
        sources=[_citation(source) for source in sources] if answered else [],
        confidence=confidence if answered else Confidence.NONE,
        answered=answered,
        refusal_reason=refusal,
        original_question="q",
        standalone_question=standalone,
        retrieved=[
            RetrievedChunk(label=f"S{n}", chunk_id=f"c{n}", source=source, location="", score=0.6)
            for n, source in enumerate(retrieved, start=1)
        ],
        gate=GateInfo(passed=gate_passed, best_score=0.6, threshold=0.34, reason=""),
        model="m",
        prompt_version="v2+c2",
    )


def test_the_frozen_test_set_has_every_required_category():
    categories = [case.category for case in load_cases()]

    minimums = {
        "easy": 4,
        "multi_step": 3,
        "follow_up": 2,
        "unanswerable": 3,
        "ambiguous": 2,
        "adversarial": 2,
    }
    for category, minimum in minimums.items():
        assert categories.count(category) >= minimum, category
    assert len(categories) >= 20


def test_correct_cited_answer_passes():
    score = score_case(_case("answer"), [_response("It is 24 months [1].")], True, [])

    assert score.verdict is Verdict.PASS
    assert score.citation_score == 1.0


def test_missing_key_fact_is_partial():
    score = score_case(_case("answer"), [_response("It lasts two years [1].")], True, [])

    assert score.verdict is Verdict.PARTIAL
    assert score.key_facts_missing == ["24 months"]


def test_forbidden_claim_fails_and_counts_as_hallucination():
    case = _case("answer")
    response = _response("Yes, it is 5 years, also 24 months [1].")
    score = score_case(case, [response], True, [])

    assert score.verdict is Verdict.FAIL
    assert is_hallucination(case, response, score)


def test_missing_required_citation_fails():
    score = score_case(
        _case("answer"), [_response("24 months [1].", sources=("faq.md",))], True, []
    )

    assert score.verdict is Verdict.FAIL
    assert score.citation_score == 0.0


def test_unrelated_extra_citation_is_partial():
    response = _response("24 months [1][2].", sources=("warranty_policy.md", "pricing_guide.csv"))

    score = score_case(_case("answer"), [response], True, [])

    assert (score.verdict, score.citation_score) == (Verdict.PARTIAL, 0.5)


def test_answering_an_unanswerable_question_fails_as_a_hallucination():
    case = _case("refuse", required_sources=(), key_facts=())
    response = _response("Yes, students get 10 percent off [1].", sources=("faq.md",))
    score = score_case(case, [response], True, [])

    assert score.verdict is Verdict.FAIL
    assert score.attribution == "prompt: refusal rule (the gate let it through)"
    assert is_hallucination(case, response, score)


def test_refusal_of_an_unanswerable_question_passes():
    case = _case("refuse", required_sources=(), key_facts=())
    response = _response("Not covered.", answered=False, refusal=RefusalReason.GATE)

    assert score_case(case, [response], None, []).verdict is Verdict.PASS


def test_partial_answer_is_recognised_from_its_wording():
    case = _case("partial", required_sources=(), key_facts=("Karachi",))
    response = _response(
        "Next-day goes to Karachi [1]. The documents do not mention exceptions.",
        sources=("faq.md",),
    )

    assert score_case(case, [response], True, []).behaviour_ok


def test_listing_options_satisfies_an_ambiguous_question():
    case = _case("clarify_or_list", required_sources=(), key_facts=())
    response = _response("PF-1 is PKR 2,400 and CP-1 is PKR 2,600 [1].", sources=("faq.md",))

    assert score_case(case, [response], True, []).verdict is Verdict.PASS


def test_consistency_needs_the_same_fact_and_source_every_time():
    case = _case("consistent")
    steady = [_response("24 months [1].") for _ in range(3)]
    wobbly = [*steady[:2], _response("24 months [1].", sources=("faq.md",))]

    assert score_case(case, steady, True, []).verdict is Verdict.PASS
    assert not score_case(case, wobbly, True, []).behaviour_ok


def test_unsupported_claim_from_the_judge_is_partial():
    score = score_case(_case("answer"), [_response("24 months [1].")], False, ["made-up claim"])

    assert score.verdict is Verdict.PARTIAL
    assert "judge found unsupported claims" in score.reasons


def test_attribution_blames_retrieval_when_the_source_was_never_found():
    response = _response("It is 2 years [1].", sources=("faq.md",), retrieved=("faq.md",))

    score = score_case(_case("answer"), [response], True, [])

    assert score.attribution == "retrieval (not retrieved: warranty_policy.md)"


def test_attribution_blames_the_gate_for_refusing_an_answerable_question():
    response = _response(
        "Not covered.", answered=False, refusal=RefusalReason.GATE, gate_passed=False
    )

    score = score_case(_case("answer"), [response], None, [])

    assert score.attribution == "relevance gate (threshold)"


def test_attribution_blames_condensation_for_stale_terms():
    case = _case("answer", turns=("a", "b"), standalone_must_not_contain=("warrant",))
    response = _response("24 months [1].", standalone="warranty and privacy app data")

    score = score_case(case, [response], True, [])

    assert score.attribution == "query condensation (stale terms carried into the rewrite)"


def test_technical_errors_fail_and_say_so():
    response = _response("Could not reach OpenAI.", answered=False, refusal=RefusalReason.ERROR)

    score = score_case(_case("answer"), [response], None, [])

    assert score.verdict is Verdict.FAIL
    assert score.attribution.startswith("technical failure")


def test_negated_or_hedged_sentences_are_not_claims():
    case = _case(
        "refuse", required_sources=(), key_facts=(), forbidden=(r"\bis (nsf[- ])?certified\b",)
    )
    refusal = "The documentation does not mention whether the filter is NSF-certified."
    claim = "Yes, the filter is NSF-certified."

    assert score_case(case, [_response(refusal, answered=False)], None, []).forbidden_found == []
    assert score_case(case, [_response(claim, answered=False)], None, []).forbidden_found
