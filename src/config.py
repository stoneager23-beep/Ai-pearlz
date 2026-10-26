"""Validated application settings: the only place tunables are read and given defaults.

Settings come from environment variables first, then an optional `.env` file in the project
root, then the defaults below. On Streamlit Community Cloud, top-level entries in the app's
secrets are exposed as environment variables, so the same code path serves both.

The OpenAI API key is deliberately not a setting. This object is printed, logged and shared
by every Streamlit session; a key belongs to one person. See `src/utils/api_keys.py`.

Smoke check:  python -m src.config
"""

import sys
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from src.utils.api_keys import (
    API_KEY_ENV_VAR,
    ApiKeyError,
    interactive_prompt,
    mask_secret,
    resolve_cli_api_key,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"

# Above this, sampling noise starts to change facts and citations between runs (manual Sec 4.1
# asks for a low, explicit temperature). Grounded support answers have no use for more.
MAX_TEMPERATURE = 0.3


class ChatModelOption(BaseModel):
    """A chat model the app can offer, with what the interface needs to describe it."""

    model_config = ConfigDict(frozen=True)

    name: str
    label: str
    retires_on: date | None = None


# OpenAI announced on 2026-10-14 that these four leave the API on 2027-01-14
# (developers.openai.com/api/docs/deprecations). All four are non-reasoning chat models, so they
# accept an explicit temperature of 0.
_GPT4_API_RETIREMENT = date(2027, 1, 14)

CHAT_MODEL_CATALOGUE: tuple[ChatModelOption, ...] = (
    ChatModelOption(name="gpt-4.1-mini", label="GPT-4.1 mini", retires_on=_GPT4_API_RETIREMENT),
    ChatModelOption(name="gpt-4.1", label="GPT-4.1", retires_on=_GPT4_API_RETIREMENT),
    ChatModelOption(name="gpt-4o-mini", label="GPT-4o mini", retires_on=_GPT4_API_RETIREMENT),
    ChatModelOption(name="gpt-4o", label="GPT-4o", retires_on=_GPT4_API_RETIREMENT),
)
_CATALOGUE_BY_NAME = {option.name: option for option in CHAT_MODEL_CATALOGUE}


class EmbeddingModelSpec(BaseModel):
    """What the index must know about an embedding model: its vector size and input limit."""

    model_config = ConfigDict(frozen=True)

    name: str
    dimension: int
    max_input_tokens: int


# From developers.openai.com/api/docs/guides/embeddings (checked 2026-10-26). LangChain's
# OpenAIEmbeddings splits any text longer than 8,191 tokens and averages the pieces, so chunks
# are checked against that stricter figure (EMBEDDING_SPLIT_LIMIT_TOKENS) before embedding.
EMBEDDING_MODEL_CATALOGUE: tuple[EmbeddingModelSpec, ...] = (
    EmbeddingModelSpec(name="text-embedding-3-small", dimension=1536, max_input_tokens=8192),
    EmbeddingModelSpec(name="text-embedding-3-large", dimension=3072, max_input_tokens=8192),
)
EMBEDDING_SPLIT_LIMIT_TOKENS = 8191
_EMBEDDING_SPECS_BY_NAME = {spec.name: spec for spec in EMBEDDING_MODEL_CATALOGUE}


class ConfigError(Exception):
    """Raised when configuration is invalid. The message is written for a person to read."""


class Settings(BaseSettings):
    """Every tunable of the system. Field names map to upper-case environment variables."""

    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        frozen=True,
    )

    llm_provider: Literal["openai"] = "openai"
    openai_chat_model: str = "gpt-4.1-mini"
    openai_chat_models: Annotated[tuple[str, ...], NoDecode] = (
        "gpt-4.1-mini",
        "gpt-4.1",
        "gpt-4o-mini",
        "gpt-4o",
    )
    openai_embedding_model: str = Field(default="text-embedding-3-small", min_length=1)
    llm_temperature: float = Field(default=0.0, ge=0.0, le=MAX_TEMPERATURE)
    openai_timeout_seconds: float = Field(default=30.0, gt=0)
    openai_max_retries: int = Field(default=4, ge=0)
    embedding_batch_size: int = Field(default=64, ge=1)

    knowledge_base_dir: Path = Path("data/knowledge_base")
    vector_store_dir: Path = Path("data/vector_store")
    collection_name: str = Field(default="pearlz_kb", pattern=r"^[A-Za-z0-9_-]+$")
    embedding_cache_path: Path = Path("data/embedding_cache/embeddings.sqlite3")
    results_dir: Path = Path("evaluation/results")

    chunk_size: int = Field(default=1500, gt=0)
    chunk_overlap: int = Field(default=225, ge=0)
    chunk_context_headers: bool = True
    retrieval_search_type: Literal["similarity", "mmr"] = "similarity"
    retrieval_k: int = Field(default=4, ge=1)
    retrieval_fetch_k: int = Field(default=20, ge=1)
    retrieval_mmr_lambda: float = Field(default=0.5, ge=0.0, le=1.0)
    relevance_threshold: float = Field(default=0.34, ge=0.0, le=1.0)
    confidence_high_score: float = Field(default=0.50, ge=0.0, le=1.0)
    max_context_characters: int = Field(default=8000, gt=0)
    history_turns: int = Field(default=4, ge=0)
    answer_prompt_version: Literal["v1", "v2"] = "v2"
    condense_prompt_version: Literal["c1", "c2"] = "c2"
    support_contact: str = Field(
        default="support@pearlzhome.example, toll-free 0800-73275 or WhatsApp +92 300 0732759",
        min_length=1,
    )

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_dir: Path = Path("logs")

    @field_validator("openai_chat_models", mode="before")
    @classmethod
    def _split_comma_separated(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(name.strip() for name in value.split(",") if name.strip())
        return value

    @field_validator("openai_chat_models")
    @classmethod
    def _models_must_be_in_catalogue(cls, names: tuple[str, ...]) -> tuple[str, ...]:
        if not names:
            raise ValueError("list at least one chat model")
        unknown = [name for name in names if name not in _CATALOGUE_BY_NAME]
        if unknown:
            known = ", ".join(_CATALOGUE_BY_NAME)
            raise ValueError(f"unknown model(s) {', '.join(unknown)}; choose from: {known}")
        return tuple(dict.fromkeys(names))

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_case_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("openai_embedding_model")
    @classmethod
    def _embedding_model_must_be_known(cls, name: str) -> str:
        if name not in _EMBEDDING_SPECS_BY_NAME:
            known = ", ".join(_EMBEDDING_SPECS_BY_NAME)
            raise ValueError(f"unknown embedding model {name}; choose from: {known}")
        return name

    @field_validator(
        "knowledge_base_dir", "vector_store_dir", "embedding_cache_path", "results_dir", "log_dir"
    )
    @classmethod
    def _resolve_from_project_root(cls, path: Path) -> Path:
        return path if path.is_absolute() else PROJECT_ROOT / path

    @model_validator(mode="after")
    def _check_relationships(self) -> "Settings":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError(
                f"CHUNK_OVERLAP ({self.chunk_overlap}) must be smaller than "
                f"CHUNK_SIZE ({self.chunk_size})"
            )
        if self.retrieval_fetch_k < self.retrieval_k:
            raise ValueError(
                f"RETRIEVAL_FETCH_K ({self.retrieval_fetch_k}) must be at least "
                f"RETRIEVAL_K ({self.retrieval_k})"
            )
        if self.openai_chat_model not in self.openai_chat_models:
            raise ValueError(
                f"OPENAI_CHAT_MODEL ({self.openai_chat_model}) must be one of "
                f"OPENAI_CHAT_MODELS ({', '.join(self.openai_chat_models)})"
            )
        return self

    def chat_model_options(self) -> tuple[ChatModelOption, ...]:
        """The catalogue entries for the models users may pick, in configured order."""
        return tuple(_CATALOGUE_BY_NAME[name] for name in self.openai_chat_models)

    @property
    def embedding_spec(self) -> EmbeddingModelSpec:
        """Dimension and input limit of the configured embedding model."""
        return _EMBEDDING_SPECS_BY_NAME[self.openai_embedding_model]


def load_settings(env_file: Path | None = DEFAULT_ENV_FILE) -> Settings:
    """Read and validate settings. Raises ConfigError with a readable message on any problem."""
    try:
        return Settings(_env_file=env_file)
    except ValidationError as error:
        raise ConfigError(_describe_validation_error(error)) from error


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The process-wide settings, loaded once. Safe to share: it is frozen and holds no secrets."""
    return load_settings()


def _describe_validation_error(error: ValidationError) -> str:
    lines = ["Configuration error (check .env or your environment variables):"]
    for problem in error.errors():
        message = problem["msg"].removeprefix("Value error, ")
        if problem["loc"]:
            variable = str(problem["loc"][0]).upper()
            lines.append(f"  - {variable}: {message}")
        else:
            lines.append(f"  - {message}")
    return "\n".join(lines)


def render_configuration(settings: Settings, api_key: str) -> str:
    """Every setting under its environment-variable name, followed by the masked key."""
    rows = [(name.upper(), _format_value(value)) for name, value in settings.model_dump().items()]
    rows.append((API_KEY_ENV_VAR, f"{mask_secret(api_key)} (set, masked)"))
    width = max(len(variable) for variable, _ in rows)
    return "\n".join(f"  {variable.ljust(width)}  {value}" for variable, value in rows)


def _format_value(value: object) -> str:
    if isinstance(value, tuple):
        return ", ".join(str(item) for item in value)
    if isinstance(value, Path) and value.is_relative_to(PROJECT_ROOT):
        return value.relative_to(PROJECT_ROOT).as_posix()
    return str(value)


def main(env_file: Path | None = DEFAULT_ENV_FILE) -> int:
    """Smoke check: print the loaded configuration, with the key masked. Exit code 1 on error."""
    try:
        settings = load_settings(env_file)
        api_key = resolve_cli_api_key(env_file, prompt=interactive_prompt())
    except (ConfigError, ApiKeyError) as error:
        print(error, file=sys.stderr)
        return 1

    print("SupportPearlz configuration")
    print(render_configuration(settings, api_key))
    return 0


if __name__ == "__main__":
    sys.exit(main())
