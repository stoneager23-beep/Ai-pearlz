"""SupportPearlz: a retrieval-augmented customer support assistant built with LangChain."""

import warnings

# langchain-community was archived in June 2026 but still provides the FAISS store and the PDF,
# CSV and text loaders used here (see "Known limitations" in the README). Without this filter its
# import-time deprecation warning would be printed by every command and in the web app.
warnings.filterwarnings(
    "ignore", message="`langchain-community` is being sunset", category=DeprecationWarning
)
