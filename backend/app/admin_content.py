"""Persistent, validated storage for administrator-managed agent content."""

import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading

from .model import AgentAdminConfig


_SKILL_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_SKILL_FRONTMATTER = re.compile(
    r"\A---\r?\n(?P<header>.*?)\r?\n---(?:\r?\n|\Z)",
    re.DOTALL,
)
_LEGACY_DEFAULT_SUBAGENTS = frozenset(
    {
        "tflex_docs_researcher",
        "tflex_cad_document_researcher",
        "tflex_cad_2d_researcher",
        "tflex_cad_3d_researcher",
    }
)
_LEGACY_BUNDLED_SKILLS = frozenset(
    {
        "tflex-cad-2d-modeling",
        "tflex-cad-3d-modeling",
        "tflex-cad-document-workflow",
        "tflex-cad-object-model-map",
        "tflex-docs-macro-language",
        "tflex-docs-open-api-map",
        "tflex-docs-reference-object-editing",
        "tflex-docs-server-file-import",
    }
)
_CONTENT_MIGRATION_MARKER = ".api-examples-content-v1"


class AdminContentStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir.resolve()
        self.config_path = self.data_dir / "agent-content.json"
        self.skills_root = self.data_dir / "skills"
        self._lock = threading.RLock()

    def initialize(
        self, defaults: AgentAdminConfig, bundled_skills_root: Path
    ) -> AgentAdminConfig:
        with self._lock:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            migration_marker = self.data_dir / _CONTENT_MIGRATION_MARKER
            bundled_marker = self.data_dir / ".bundled-skills-copied"
            if self.config_path.exists():
                config = AgentAdminConfig.model_validate_json(
                    self.config_path.read_text(encoding="utf-8")
                )
                if not migration_marker.exists():
                    configured_names = {
                        subagent.name for subagent in config.subagents
                    }
                    missing_subagents = [
                        subagent.model_copy(deep=True)
                        for subagent in defaults.subagents
                        if subagent.name not in configured_names
                        and subagent.name not in _LEGACY_DEFAULT_SUBAGENTS
                    ]
                    if missing_subagents:
                        config.subagents.extend(missing_subagents)
                        self._write_atomic(
                            self.config_path,
                            json.dumps(
                                config.model_dump(mode="json"),
                                ensure_ascii=False,
                                indent=2,
                            ),
                        )
            else:
                config = defaults.model_copy(deep=True)
                self._write_atomic(
                    self.config_path,
                    json.dumps(config.model_dump(mode="json"), ensure_ascii=False, indent=2),
                )

            self.skills_root.mkdir(parents=True, exist_ok=True)
            if self.skills_root.is_symlink():
                raise ValueError("Каталог навыков не может быть символической ссылкой")
            for bundled_skill in bundled_skills_root.iterdir():
                if bundled_marker.exists() and (
                    migration_marker.exists()
                    or bundled_skill.name in _LEGACY_BUNDLED_SKILLS
                ):
                    continue
                target = self.skills_root / bundled_skill.name
                if not target.exists():
                    shutil.copytree(bundled_skill, target)
            if not bundled_marker.exists():
                self._write_atomic(bundled_marker, "initialized\n")
            if not migration_marker.exists():
                self._write_atomic(migration_marker, "api-examples-content-v1\n")
            return config

    def save_config(self, config: AgentAdminConfig) -> None:
        with self._lock:
            self._write_atomic(
                self.config_path,
                json.dumps(
                    config.model_dump(mode="json"), ensure_ascii=False, indent=2
                ),
            )

    def list_skills(self) -> list[dict[str, str]]:
        with self._lock:
            skills = []
            for directory in sorted(self.skills_root.iterdir()):
                skill_file = directory / "SKILL.md"
                if (
                    directory.is_dir()
                    and not directory.is_symlink()
                    and skill_file.is_file()
                    and not skill_file.is_symlink()
                ):
                    content = skill_file.read_text(encoding="utf-8")
                    name, description = skill_metadata(content)
                    skills.append(
                        {
                            "name": name or directory.name,
                            "description": description,
                        }
                    )
            return skills

    def get_skill(self, skill_id: str) -> str:
        with self._lock:
            skill_file = self._skill_file(skill_id)
            if not skill_file.is_file():
                raise FileNotFoundError(f"Навык не найден: {skill_id}")
            return skill_file.read_text(encoding="utf-8")

    def create_skill(self, skill_id: str, content: str) -> None:
        self._validate_skill(skill_id, content)
        with self._lock:
            directory = self._skill_dir(skill_id)
            if directory.exists():
                raise FileExistsError(f"Навык уже существует: {skill_id}")
            directory.mkdir()
            try:
                self._write_atomic(directory / "SKILL.md", content)
            except OSError:
                directory.rmdir()
                raise

    def update_skill(self, skill_id: str, content: str) -> None:
        self._validate_skill(skill_id, content)
        with self._lock:
            skill_file = self._skill_file(skill_id)
            if not skill_file.is_file():
                raise FileNotFoundError(f"Навык не найден: {skill_id}")
            self._write_atomic(skill_file, content)

    def delete_skill(self, skill_id: str) -> None:
        with self._lock:
            directory = self._skill_dir(skill_id)
            if not directory.is_dir() or not (directory / "SKILL.md").is_file():
                raise FileNotFoundError(f"Навык не найден: {skill_id}")
            shutil.rmtree(directory)

    def _validate_skill(self, skill_id: str, content: str) -> None:
        if not _SKILL_ID.fullmatch(skill_id):
            raise ValueError("ID навыка должен быть в формате kebab-case")
        match = _SKILL_FRONTMATTER.match(content)
        if match is None:
            raise ValueError("Файл должен начинаться с YAML frontmatter")
        name, description = skill_metadata(content)
        if name != skill_id:
            raise ValueError("Поле name во frontmatter должно совпадать с ID навыка")
        if not description:
            raise ValueError("В YAML frontmatter требуется непустое поле description")

    def _skill_dir(self, skill_id: str) -> Path:
        if not _SKILL_ID.fullmatch(skill_id):
            raise ValueError("Некорректный ID навыка")
        directory = self.skills_root / skill_id
        if directory.is_symlink():
            raise ValueError("Символические ссылки в каталоге навыков запрещены")
        if directory.resolve().parent != self.skills_root.resolve():
            raise ValueError("Каталог навыка находится вне разрешённого каталога")
        return directory

    def _skill_file(self, skill_id: str) -> Path:
        skill_file = self._skill_dir(skill_id) / "SKILL.md"
        if skill_file.is_symlink():
            raise ValueError("Символические ссылки в каталоге навыков запрещены")
        return skill_file

    @staticmethod
    def _write_atomic(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                delete=False,
            ) as temporary:
                temporary.write(content)
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()


def skill_metadata(content: str) -> tuple[str, str]:
    match = _SKILL_FRONTMATTER.match(content)
    if match is None:
        return "", ""
    name_match = re.search(r"^name:\s*(\S.*?)\s*$", match.group("header"), re.M)
    description_match = re.search(
        r"^description:\s*(.*?)\s*$", match.group("header"), re.M
    )
    return (
        name_match.group(1).strip() if name_match else "",
        description_match.group(1).strip().strip("\"'") if description_match else "",
    )
