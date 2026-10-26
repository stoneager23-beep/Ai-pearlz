"""Run the full evaluation set and write machine- and human-readable results (Task 11).

Usage:
    python -m evaluation.run_eval                       # all cases
    python -m evaluation.run_eval --cases T-07,T-08     # a subset
    python -m evaluation.run_eval --model gpt-4o-mini   # another offered chat model

Each case runs in a fresh session (multi-turn cases ask their turns in order). The final turn
is scored with the rubric in `evaluation/scoring.py`; answered turns are also checked for
groundedness by the judge model. Outputs, in RESULTS_DIR:

- eval_results.json: every response in full, with its scores (machine-readable);
- eval_results.md: the per-case table, aggregate metrics and the proposed failure attribution.

The verdicts written here are automatic and proposed. The final verdicts come from reading the
answers against the rubric (see docs/technical_report.md).
"""

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict
from statistics import mean

from langchain_community.vectorstores import FAISS

from evaluation.experiments.common import (
    markdown_table,
    run_timestamp,
    start_experiment,
    write_result,
)
from evaluation.judge import JUDGE_PROMPT_VERSION, judge_groundedness
from evaluation.scoring import EvalCase, is_hallucination, load_cases, score_case
from src.chains.context import build_context
from src.chains.schemas import SupportResponse
from src.chains.session import SupportSession
from src.config import ConfigError, Settings
from src.errors import describe_failure
from src.ingestion.embedding_cache import build_cached_embedder
from src.ingestion.indexing import load_or_build
from src.llm.clients import build_chat_model
from src.utils.api_keys import ApiKeyError

JSON_FILE = "eval_results.json"
MARKDOWN_FILE = "eval_results.md"
ANSWER_EXCERPT_CHARACTERS = 160


def context_shown(response: SupportResponse, store: FAISS, settings: Settings) -> str:
    """Rebuild the exact context blocks the answering model saw, in label order."""
    labelled = sorted(
        (chunk for chunk in response.retrieved if chunk.label),
        key=lambda chunk: int(chunk.label[1:]),
    )
    documents = [store.docstore.search(chunk.chunk_id) for chunk in labelled]
    return build_context(documents, settings.max_context_characters).text


def run_case(
    case: EvalCase,
    store: FAISS,
    settings: Settings,
    api_key: str,
    model_name: str | None,
    judge_model: object,
) -> dict:
    session = SupportSession(settings, store, build_chat_model(api_key, settings, model_name))
    responses = [session.ask(turn) for turn in case.turns]
    final = responses[-1]
    grounded, unsupported = None, []
    if final.answered:
        verdict = judge_groundedness(
            judge_model,
            question=final.standalone_question,
            answer=final.answer,
            context=context_shown(final, store, settings),
            support_contact=settings.support_contact,
        )
        grounded, unsupported = verdict.grounded, verdict.unsupported_claims
    score = score_case(case, responses, grounded, unsupported)
    return {
        "case": asdict(case),
        "responses": [response.model_dump(mode="json") for response in responses],
        "score": {**asdict(score), "verdict": score.verdict.value},
        "hallucination": is_hallucination(case, final, score),
    }


def _citation_list(response: dict) -> str:
    return ", ".join(f"{c['source']} {c['location']}".strip() for c in response["sources"])


def _excerpt(text: str) -> str:
    flat = " ".join(text.split()).replace("|", "/")
    if len(flat) <= ANSWER_EXCERPT_CHARACTERS:
        return flat
    return flat[:ANSWER_EXCERPT_CHARACTERS].rsplit(" ", 1)[0] + " ..."


def aggregate(records: list[dict]) -> dict:
    finals = [record["responses"][-1] for record in records]
    scores = [record["score"] for record in records]
    refuse_cases = [r for r in records if r["case"]["behaviour"] == "refuse"]
    judged = [s for s in scores if s["grounded"] is not None]
    fact_cases = [s for r, s in zip(records, scores, strict=True) if r["case"]["key_facts"]]
    return {
        "cases": len(records),
        "verdicts": dict(Counter(score["verdict"] for score in scores)),
        "behaviour_correct": sum(score["behaviour_ok"] for score in scores),
        "key_facts_all_present": sum(not score["key_facts_missing"] for score in fact_cases),
        "cases_with_key_facts": len(fact_cases),
        "mean_citation_score": round(mean(score["citation_score"] for score in scores), 3),
        "judged_answers": len(judged),
        "judged_grounded": sum(score["grounded"] for score in judged),
        "refusal_rate_unanswerable": (
            f"{sum(not r['responses'][-1]['answered'] for r in refuse_cases)}/{len(refuse_cases)}"
        ),
        "hallucinations": sum(record["hallucination"] for record in records),
        "turns": sum(len(record["responses"]) for record in records),
        "mean_latency_ms": round(
            mean(r["latency_ms"] for rec in records for r in rec["responses"])
        ),
        "input_tokens": sum(
            r["usage"]["input_tokens"] for rec in records for r in rec["responses"]
        ),
        "output_tokens": sum(
            r["usage"]["output_tokens"] for rec in records for r in rec["responses"]
        ),
        "gate_refusals": sum(final["refusal_reason"] == "gate" for final in finals),
    }


def render(records: list[dict], metrics: dict, settings: Settings, model_name: str) -> str:
    rows = []
    for record in records:
        case, final, score = record["case"], record["responses"][-1], record["score"]
        cited = ", ".join(f"{c['source']} {c['location']}".strip() for c in final["sources"]) or "-"
        rows.append(
            [
                case["id"],
                case["category"],
                case["behaviour"],
                f"**{score['verdict']}**",
                _excerpt(final["answer"]),
                cited.replace("|", "/"),
                f"{score['citation_score']:.1f}",
                {True: "yes", False: "**no**", None: "-"}[score["grounded"]],
                "; ".join(score["reasons"]) or "-",
                score["attribution"],
            ]
        )
    detail = []
    for record in records:
        case = record["case"]
        detail += [f"### {case['id']} ({case['category']}): {case['notes']}", ""]
        for number, response in enumerate(record["responses"], start=1):
            rewritten = response["standalone_question"] != response["original_question"]
            retrieved = ", ".join(
                f"`{c['chunk_id']}` {c['score']:.3f}" for c in response["retrieved"]
            )
            detail += [
                f"- **Turn {number}:** {response['original_question']}",
                f"  - searched for: {response['standalone_question']}"
                if rewritten
                else "  - searched for: (not rewritten)",
                f"  - gate: {response['gate']['reason'] if response['gate'] else '-'}",
                f"  - retrieved: {retrieved or '-'}",
                f"  - answer ({response['confidence']}, refusal: {response['refusal_reason']}): "
                + " ".join(response["answer"].split()),
                f"  - cited: {_citation_list(response) or '-'}",
            ]
        unsupported = record["score"]["unsupported_claims"]
        if unsupported:
            detail.append(f"- judge, unsupported claims: {'; '.join(unsupported)}")
        detail.append("")
    metric_rows = [[name.replace("_", " "), str(value)] for name, value in metrics.items()]
    return "\n".join(
        [
            "# Evaluation results (Task 11)",
            "",
            f"Run: {run_timestamp()}. Chat model `{model_name}`, temperature "
            f"{settings.llm_temperature}, prompts {settings.answer_prompt_version}+"
            f"{settings.condense_prompt_version}, k={settings.retrieval_k}, threshold "
            f"{settings.relevance_threshold}. Groundedness judge `{settings.eval_judge_model}` "
            f"(prompt {JUDGE_PROMPT_VERSION}). Verdicts and attributions are automatic proposals "
            "from `evaluation/scoring.py`; read the details before relying on them.",
            "",
            "## Aggregate metrics",
            "",
            markdown_table(["Metric", "Value"], metric_rows),
            "",
            "## Cases",
            "",
            markdown_table(
                [
                    "ID",
                    "Category",
                    "Expected",
                    "Verdict",
                    "Answer (excerpt)",
                    "Cited",
                    "Citation score",
                    "Grounded (judge)",
                    "Why not a pass",
                    "Proposed stage at fault",
                ],
                rows,
            ),
            "",
            "## Details",
            "",
            *detail,
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the SupportPearlz evaluation set.")
    parser.add_argument("--cases", help="Comma-separated case ids, e.g. T-07,T-08")
    parser.add_argument("--model", help="Chat model to evaluate (one of OPENAI_CHAT_MODELS)")
    args = parser.parse_args(argv)
    try:
        context = start_experiment()
    except (ConfigError, ApiKeyError) as error:
        print(error, file=sys.stderr)
        return 1
    settings = context.settings
    cases = load_cases()
    if args.cases:
        wanted = {case_id.strip() for case_id in args.cases.split(",")}
        cases = [case for case in cases if case.id in wanted]
    model_name = args.model or settings.openai_chat_model
    try:
        index = load_or_build(settings, build_cached_embedder(context.api_key, settings))
        judge = build_chat_model(context.api_key, settings, settings.eval_judge_model)
        records = []
        for case in cases:
            print(f"{case.id} ...", end=" ", flush=True)
            records.append(
                run_case(case, index.store, settings, context.api_key, model_name, judge)
            )
            print(records[-1]["score"]["verdict"])
    except Exception as error:  # an evaluation run should end with a message, not a traceback
        print(describe_failure(error).message, file=sys.stderr)
        return 1

    metrics = aggregate(records)
    write_result(
        settings, JSON_FILE, json.dumps({"metrics": metrics, "records": records}, indent=2)
    )
    path = write_result(settings, MARKDOWN_FILE, render(records, metrics, settings, model_name))
    print(json.dumps(metrics, indent=2))
    print(f"Written to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
