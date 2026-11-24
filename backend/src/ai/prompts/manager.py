"""
File: manager.py
Purpose: Load prompt configs and render Jinja2 prompt templates.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: jinja2, pyyaml, pydantic
"""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment
from jinja2 import FileSystemLoader
from jinja2 import StrictUndefined
from jinja2 import select_autoescape
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

_PROMPTS_DIR = Path(__file__).resolve().parent


class ModelParams(BaseModel):
    """Model settings a prompt was tuned for."""

    model_config = ConfigDict(protected_namespaces=())

    model_id: str
    temperature: float = Field(ge=0.0, le=1.0)
    max_tokens: int = Field(gt=0)


class PromptConfig(BaseModel):
    """A prompt definition from ``configs/<name>.yaml``."""

    # The YAML key is "model_config", which pydantic reserves, so it is aliased.
    model_config = ConfigDict(populate_by_name=True, protected_namespaces=())

    name: str
    description: str
    version: str
    template: str
    user_template: str
    llm: ModelParams = Field(alias="model_config")


class PromptManager:
    """Renders prompts from ``templates/`` using settings from ``configs/``."""

    def __init__(self, prompts_dir: Path | None = None) -> None:
        base = prompts_dir or _PROMPTS_DIR
        self._configs_dir = base / "configs"
        # Prompts are plain text, so HTML auto-escaping stays off for .j2 files.
        # Undefined variables raise instead of rendering as empty text.
        self._env = Environment(
            loader=FileSystemLoader(base / "templates"),
            autoescape=select_autoescape(enabled_extensions=("html", "xml")),
            undefined=StrictUndefined,
            keep_trailing_newline=False,
        )

    @lru_cache(maxsize=8)  # noqa: B019 - the manager lives for the whole process
    def config(self, name: str) -> PromptConfig:
        """Load and validate ``configs/<name>.yaml``.

        Args:
            name: Prompt name, for example ``document_extraction``.

        Returns:
            The validated prompt configuration.

        Raises:
            FileNotFoundError: If the config file does not exist.
            pydantic.ValidationError: If the config is malformed.
        """
        path = self._configs_dir / f"{name}.yaml"
        with path.open(encoding="utf-8") as handle:
            raw: Any = yaml.safe_load(handle)
        return PromptConfig.model_validate(raw)

    def render_system(self, name: str, **variables: Any) -> str:
        """Render the system prompt of ``name``.

        Args:
            name: Prompt name.
            **variables: Template variables.

        Returns:
            The rendered system prompt.
        """
        template = self._env.get_template(self.config(name).template)
        return template.render(**variables).strip()

    def render_user(self, name: str, **variables: Any) -> str:
        """Render the user prompt of ``name``.

        Args:
            name: Prompt name.
            **variables: Template variables.

        Returns:
            The rendered user prompt.
        """
        template = self._env.get_template(self.config(name).user_template)
        return template.render(**variables).strip()


@lru_cache(maxsize=1)
def get_prompt_manager() -> PromptManager:
    """Return the process-wide prompt manager.

    Returns:
        The cached ``PromptManager``.
    """
    return PromptManager()
