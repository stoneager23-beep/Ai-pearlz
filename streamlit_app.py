"""SupportPearlz web app entry point (`streamlit run streamlit_app.py`; Community Cloud runs it).

Kept thin on purpose: the interface lives in `app/`, the answering system in `src/`.
"""

from app.main import run

run()
