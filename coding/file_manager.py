"""File creation, reading, and editing with a project sandbox."""
from __future__ import annotations

from pathlib import Path
from typing import Any


class FileManager:
    """Create/read/edit files, always resolving paths inside a sandbox root.

    The sandbox prevents accidental writes outside the workspace. Escaping the
    root (via .. or an absolute path outside it) is rejected.
    """

    def __init__(self, root: str | Path, security_manager: Any | None = None) -> None:
        self.root = Path(root).resolve()
        self._security_manager = security_manager

    def _allowed(self) -> bool:
        if self._security_manager is None:
            return True
        return bool(self._security_manager.is_allowed())

    def _resolve(self, path: str | Path) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        resolved = candidate.resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise ValueError(f"Path escapes sandbox root: {path}")
        return resolved

    def create(self, path: str, content: str = "", overwrite: bool = False) -> dict[str, Any]:
        if not self._allowed():
            return {"success": False, "error": "Blocked: security manager disallows control actions"}
        try:
            target = self._resolve(path)
            if target.exists() and not overwrite:
                return {"success": False, "error": f"File already exists: {target}"}
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            # Independent verification.
            exists = target.exists()
            readback = target.read_text(encoding="utf-8") if exists else None
            return {
                "success": exists and readback == content,
                "path": str(target),
                "bytes": target.stat().st_size if exists else 0,
                "verified_content_match": readback == content,
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def read(self, path: str, max_bytes: int = 65536) -> dict[str, Any]:
        if not self._allowed():
            return {"success": False, "error": "Blocked: security manager disallows control actions"}
        try:
            target = self._resolve(path)
            if not target.exists():
                return {"success": False, "error": f"File not found: {target}"}
            data = target.read_text(encoding="utf-8", errors="replace")[:max_bytes]
            return {
                "success": True,
                "path": str(target),
                "content": data,
                "bytes": target.stat().st_size,
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def edit(self, path: str, old: str, new: str) -> dict[str, Any]:
        """Replace an exact substring; verifies the new content is present."""
        if not self._allowed():
            return {"success": False, "error": "Blocked: security manager disallows control actions"}
        try:
            target = self._resolve(path)
            if not target.exists():
                return {"success": False, "error": f"File not found: {target}"}
            text = target.read_text(encoding="utf-8")
            count = text.count(old)
            if count == 0:
                return {"success": False, "error": "Target text not found in file", "path": str(target)}
            updated = text.replace(old, new)
            target.write_text(updated, encoding="utf-8")
            readback = target.read_text(encoding="utf-8")
            return {
                "success": new in readback and old not in readback,
                "path": str(target),
                "replacements": count,
                "verified_new_present": new in readback,
                "verified_old_removed": old not in readback,
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def append(self, path: str, content: str) -> dict[str, Any]:
        if not self._allowed():
            return {"success": False, "error": "Blocked: security manager disallows control actions"}
        try:
            target = self._resolve(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as fh:
                fh.write(content)
            readback = target.read_text(encoding="utf-8")
            return {"success": content in readback, "path": str(target)}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def list_files(self, dir_path: str = ".", limit: int = 200) -> dict[str, Any]:
        if not self._allowed():
            return {"success": False, "error": "Blocked: security manager disallows control actions"}
        try:
            target = self._resolve(dir_path)
            if not target.is_dir():
                return {"success": False, "error": f"Not a directory: {target}"}
            entries = []
            for i, child in enumerate(sorted(target.iterdir(), key=lambda p: p.name.lower())):
                if i >= limit:
                    break
                entries.append({
                    "name": child.name,
                    "dir": child.is_dir(),
                    "size": child.stat().st_size if child.is_file() else None,
                })
            return {"success": True, "path": str(target), "entries": entries, "count": len(entries)}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def delete(self, path: str) -> dict[str, Any]:
        """Delete a file. Callers must have obtained CONFIRM authorization."""
        try:
            target = self._resolve(path)
            if not target.exists():
                return {"success": False, "error": f"File not found: {target}"}
            if target.is_dir():
                return {"success": False, "error": "Refusing to delete directories"}
            target.unlink()
            return {"success": not target.exists(), "path": str(target)}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def move(self, src: str, dst: str) -> dict[str, Any]:
        """Move/rename a file inside the sandbox and verify the result."""
        if not self._allowed():
            return {"success": False, "error": "Blocked: security manager disallows control actions"}
        try:
            source = self._resolve(src)
            target = self._resolve(dst)
            if not source.exists():
                return {"success": False, "error": f"File not found: {source}"}
            if source.is_dir():
                return {"success": False, "error": "Refusing to move directories"}
            if target.exists():
                return {"success": False, "error": f"Destination already exists: {target}"}
            target.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.move(str(source), str(target))
            return {
                "success": target.exists() and not source.exists(),
                "path": str(target),
                "from": str(source),
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def copy(self, src: str, dst: str) -> dict[str, Any]:
        """Copy a file inside the sandbox and verify size parity."""
        if not self._allowed():
            return {"success": False, "error": "Blocked: security manager disallows control actions"}
        try:
            source = self._resolve(src)
            target = self._resolve(dst)
            if not source.exists():
                return {"success": False, "error": f"File not found: {source}"}
            if source.is_dir():
                return {"success": False, "error": "Refusing to copy directories"}
            if target.exists():
                return {"success": False, "error": f"Destination already exists: {target}"}
            target.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(str(source), str(target))
            same = target.exists() and target.stat().st_size == source.stat().st_size
            return {"success": same, "path": str(target),
                    "bytes": target.stat().st_size if same else 0}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def search(self, pattern: str = "*", dir_path: str = ".", limit: int = 200) -> dict[str, Any]:
        """Find files under dir_path by glob or substring name pattern."""
        if not self._allowed():
            return {"success": False, "error": "Blocked: security manager disallows control actions"}
        try:
            import fnmatch
            target = self._resolve(dir_path)
            if not target.is_dir():
                return {"success": False, "error": f"Not a directory: {target}"}
            has_magic = any(ch in pattern for ch in "*?[")
            matches: list[dict[str, Any]] = []
            for child in sorted(target.rglob("*"), key=lambda p: str(p).lower()):
                if len(matches) >= limit:
                    break
                if not child.is_file():
                    continue
                name = child.name
                hit = fnmatch.fnmatch(name.lower(), pattern.lower()) if has_magic \
                    else pattern.lower() in name.lower()
                if hit:
                    try:
                        rel = str(child.relative_to(self.root))
                    except ValueError:
                        rel = str(child)
                    matches.append({"name": name, "path": rel, "bytes": child.stat().st_size})
            return {"success": True, "pattern": pattern, "path": str(target),
                    "entries": matches, "count": len(matches)}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

