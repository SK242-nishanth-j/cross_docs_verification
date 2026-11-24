"""
File: validate_prompts.py
Purpose: Pre-commit check that prompt configs and Jinja2 templates are well formed.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: pyyaml
"""

import json
import sys
from pathlib import Path
from typing import Any

import yaml

PROMPTS_DIR = Path("backend/src/ai/prompts")
REQUIRED_FIELDS = ("name", "template", "model_config")
DANGEROUS_PATTERNS = (
    "ignore previous instructions",
    "forget everything above",
    "system:",
    "assistant:",
)
MAX_TEMPLATE_CHARS = 10_000


class PromptValidator:
    """Validates the prompt files under ``PROMPTS_DIR``."""

    def __init__(self, prompts_dir: Path) -> None:
        self.prompts_dir = prompts_dir
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def validate_all(self) -> bool:
        """Validate every config and template; return True when there are no errors."""
        if not self.prompts_dir.exists():
            self.errors.append(f"{self.prompts_dir} directory not found")
            return False
        configs = [
            *self.prompts_dir.glob("**/*.yaml"),
            *self.prompts_dir.glob("**/*.yml"),
            *self.prompts_dir.glob("**/*.json"),
        ]
        templates = list(self.prompts_dir.glob("**/*.j2"))
        if not configs and not templates:
            self.warnings.append(f"No prompt files found in {self.prompts_dir}")
        for path in configs:
            self._validate_config(path)
        for path in templates:
            self._validate_template_file(path)
        return not self.errors

    def _validate_config(self, path: Path) -> None:
        try:
            text = path.read_text(encoding="utf-8")
            data: Any = (
                json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
            )
        except (OSError, ValueError, yaml.YAMLError) as exc:
            self.errors.append(f"{path}: cannot read ({type(exc).__name__})")
            return
        if not isinstance(data, dict):
            self.errors.append(f"{path}: root must be a dictionary")
            return
        for field in REQUIRED_FIELDS:
            if field not in data:
                self.errors.append(f"{path}: missing required field '{field}'")
        template = data.get("template")
        if isinstance(template, str):
            self._validate_template_reference(path, template)
        user_template = data.get("user_template")
        if isinstance(user_template, str):
            self._validate_template_reference(path, user_template)
        if "model_config" in data:
            self._validate_model_config(path, data["model_config"])

    def _validate_template_reference(self, config_path: Path, template: str) -> None:
        """A template is either inline text or the name of a file in templates/."""
        if not template.strip():
            self.errors.append(f"{config_path}: template content is empty")
            return
        if template.endswith(".j2"):
            if not (self.prompts_dir / "templates" / template).is_file():
                self.errors.append(
                    f"{config_path}: template file '{template}' not found"
                )
            return
        self._validate_template_content(config_path, template)

    def _validate_template_file(self, path: Path) -> None:
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            self.errors.append(f"{path}: cannot read ({type(exc).__name__})")
            return
        if not content.strip():
            self.errors.append(f"{path}: template file is empty")
            return
        for opener, closer, label in (("{{", "}}", "variable"), ("{%", "%}", "block")):
            if opener in content and closer not in content:
                self.errors.append(f"{path}: unclosed Jinja2 {label}")
        self._validate_template_content(path, content)

    def _validate_template_content(self, path: Path, text: str) -> None:
        lowered = text.lower()
        for pattern in DANGEROUS_PATTERNS:
            if pattern in lowered:
                self.warnings.append(f"{path}: contains risky phrase '{pattern}'")
        if len(text) > MAX_TEMPLATE_CHARS:
            self.warnings.append(
                f"{path}: template is very long ({len(text)} chars); consider splitting"
            )

    def _validate_model_config(self, path: Path, config: Any) -> None:
        if not isinstance(config, dict):
            self.errors.append(f"{path}: model_config must be a dictionary")
            return
        if "model_id" not in config:
            self.errors.append(f"{path}: model_config is missing 'model_id'")
        temperature = config.get("temperature")
        if temperature is not None and (
            not isinstance(temperature, int | float) or not 0 <= temperature <= 1
        ):
            self.errors.append(f"{path}: temperature must be between 0 and 1")
        max_tokens = config.get("max_tokens")
        if max_tokens is not None and (
            not isinstance(max_tokens, int)
            or isinstance(max_tokens, bool)
            or max_tokens <= 0
        ):
            self.errors.append(f"{path}: max_tokens must be a positive integer")


def main() -> int:
    """Validate all prompt files and return the process exit code."""
    validator = PromptValidator(PROMPTS_DIR)
    valid = validator.validate_all()
    for error in validator.errors:
        print(f"ERROR   {error}")
    for warning in validator.warnings:
        print(f"WARNING {warning}")
    if valid and not validator.warnings:
        print("All prompt files are valid.")
    return 0 if valid else 1


if __name__ == "__main__":
    sys.exit(main())
