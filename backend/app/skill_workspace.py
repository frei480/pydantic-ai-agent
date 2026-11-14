"""Read-only workspace backend for loading bundled Harness skills."""

from collections.abc import Sequence
from pathlib import Path, PurePosixPath
import posixpath

from pydantic_ai.workspaces import FileEntry, WorkspaceReadOnlyError, WorkspaceRef


class SkillWorkspaceBackend:
    """Expose the app's bundled skills through a confined, read-only workspace."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    @property
    def ref(self) -> WorkspaceRef | None:
        return None

    async def working_dir(self) -> str:
        return "/skills"

    def _resolve(self, path: str) -> Path:
        normalized = posixpath.normpath(path)
        if not (
            posixpath.isabs(path)
            and (normalized == "/skills" or normalized.startswith("/skills/"))
        ):
            raise PermissionError(f"Path is outside the skill workspace: {path}")
        relative = PurePosixPath(normalized).relative_to("/skills")
        resolved = self._root.joinpath(*relative.parts).resolve()
        if not resolved.is_relative_to(self._root):
            raise PermissionError(f"Path is outside the skill workspace: {path}")
        return resolved

    async def read_bytes(self, path: str) -> bytes:
        return self._resolve(path).read_bytes()

    async def write_bytes(self, path: str, data: bytes) -> None:
        raise WorkspaceReadOnlyError("The skill workspace is read-only.")

    async def stat(self, path: str) -> FileEntry:
        resolved = self._resolve(path)
        details = resolved.stat()
        return FileEntry(
            name=resolved.name or "app",
            path=posixpath.normpath(path),
            is_dir=resolved.is_dir(),
            size=details.st_size if resolved.is_file() else None,
        )

    async def list_dir(self, path: str) -> Sequence[FileEntry]:
        directory = self._resolve(path)
        entries = []
        for child in directory.iterdir():
            child_path = posixpath.join(posixpath.normpath(path), child.name)
            resolved = self._resolve(child_path)
            details = resolved.stat()
            entries.append(
                FileEntry(
                    name=child.name,
                    path=child_path,
                    is_dir=resolved.is_dir(),
                    size=details.st_size if resolved.is_file() else None,
                )
            )
        return entries

    async def make_dir(self, path: str) -> None:
        raise WorkspaceReadOnlyError("The skill workspace is read-only.")

    async def remove(self, path: str) -> None:
        raise WorkspaceReadOnlyError("The skill workspace is read-only.")

    async def exists(self, path: str) -> bool:
        return self._resolve(path).exists()
