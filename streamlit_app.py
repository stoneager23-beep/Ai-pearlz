"""SupportPearlz web app entry point (`streamlit run streamlit_app.py`; Community Cloud runs it).

Kept thin on purpose: the interface lives in `app/`, the answering system in `src/`.
"""

import sys

import streamlit as st

try:
    from app.main import run
except ImportError as error:  # started with a Python that lacks the project's packages
    st.error(
        f"SupportPearlz could not start: the package `{error.name}` is missing from this Python "
        f"({sys.version.split()[0]}). Start the app from the project's virtual environment "
        "(Python 3.11 with requirements.txt installed): activate it, then run "
        "`python -m streamlit run streamlit_app.py`. See the README, section *The web app*."
    )
    st.stop()

run()
