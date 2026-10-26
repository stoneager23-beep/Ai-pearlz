"""SupportPearlz: a retrieval-augmented customer support assistant built with LangChain."""

import warnings

# langchain-community was archived in June 2026 but still provides the FAISS store and the PDF,
# CSV and text loaders used here (see "Known limitations" in the README). Without this filter its
# import-time deprecation warning would be printed by every command and in the web app.
warnings.filterwarnings(
    "ignore", message="`langchain-community` is being sunset", category=DeprecationWarning
)

# When a structured answer is streamed, langchain-openai serialises the OpenAI SDK's stream
# chunks, whose `parsed` field is typed None but holds the parsed AnswerDraft. Pydantic then
# warns on every answer. The values are correct; only this one warning is silenced.
warnings.filterwarnings(
    "ignore",
    message=r"Pydantic serializer warnings:\s+PydanticSerializationUnexpectedValue\(Expected `none`"
    r"[^\n]*field_name='parsed'",
    category=UserWarning,
)
