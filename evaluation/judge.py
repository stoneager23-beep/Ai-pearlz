"""An LLM judge for groundedness (Task 11; bonus C8).

Given exactly the context blocks the answering model saw, the question and the answer, a
separate, stronger model (EVAL_JUDGE_MODEL) lists every factual claim in the answer that the
context does not support. Courtesy phrases, the support contact and statements that the
documents do not cover something are not claims.

The judge is an aid, not ground truth: its verdicts are compared with the human review, and
the disagreement is reported.
"""

from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

JUDGE_PROMPT_VERSION = "j1"

JUDGE_SYSTEM = """\
You check whether a customer-support answer is fully supported by the documents the assistant \
was given. You are strict about facts and relaxed about wording.

A claim is any statement of fact: a number, period, price, date, condition, procedure step, \
capability, or a statement about what is or is not covered or possible. A claim is supported \
only if the context states it or it follows directly from the context without outside \
knowledge.

These are NOT claims and must not be listed: greetings and courtesy phrases; the support \
contact ({support_contact}); statements that the documentation does not mention or cover \
something; suggestions to contact support.

List each unsupported claim briefly, in the answer's own words. If every claim is supported, \
return grounded = true and an empty list."""

JUDGE_HUMAN = """\
<context>
{context}
</context>

Question: {question}

Answer to check:
<answer>
{answer}
</answer>"""


class GroundednessVerdict(BaseModel):
    grounded: bool = Field(description="True if every factual claim is supported by the context.")
    unsupported_claims: list[str] = Field(
        description="Each factual claim not supported by the context; empty if none."
    )


def judge_groundedness(
    judge_model: BaseChatModel,
    *,
    question: str,
    answer: str,
    context: str,
    support_contact: str,
) -> GroundednessVerdict:
    prompt = ChatPromptTemplate.from_messages(
        [("system", JUDGE_SYSTEM), ("human", JUDGE_HUMAN)]
    ).partial(support_contact=support_contact)
    chain = prompt | judge_model.with_structured_output(
        GroundednessVerdict, method="json_schema", strict=True
    )
    return chain.invoke({"context": context, "question": question, "answer": answer})
