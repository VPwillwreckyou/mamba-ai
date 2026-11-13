"""Inspect a project to detect its build/test tooling."""
from __future__ import annotations

from pathlib import Path
from typing import Any

BUILD_MARKERS: dict[str, str] = {
    "requirements.txt": "pip install -r requirements.txt",
    "pyproject.toml": "pip install -e .",
    "setup.py": "pip install -e .",
    "package.json": "npm install",
    "makefile": "make",
    "cargo.toml": "cargo build",
    "*.sln": "msbuild",
}

TEST_MARKERS: dict[str, str] = {
    "pytest.ini": "pytest",
    "tox.ini": "tox",
    "package.json": "npm test",
    "requirements-dev.txt": "pytest",
}


class ProjectInspector:
    """Report what a project is and how to build/test it, from real files."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def inspect(self, subdir: str = ".") -> dict[str, Any]:
        target = (self.root / subdir).resolve() if not Path(subdir).is_absolute() else Path(subdir)
        if not target.is_dir():
            return {"success": False, "error": f"Not a directory: {target}"}
        entries = []
        build_command = None
        test_command = None
        languages: set[str] = set()
        for child in sorted(target.iterdir(), key=lambda p: p.name.lower()):
            entries.append({
                "name": child.name,
                "dir": child.is_dir(),
                "size": child.stat().st_size if child.is_file() else None,
            })
            if child.is_file():
                name = child.name.lower()
                for marker, cmd in BUILD_MARKERS.items():
                    if marker.startswith("*"):
                        if name.endswith(marker[1:]):
                            build_command = build_command or cmd
                    elif name == marker:
                        build_command = build_command or cmd
                for marker, cmd in TEST_MARKERS.items():
                    if name == marker:
                        test_command = test_command or cmd
                ext = child.suffix.lower()
                if ext == ".py":
                    languages.add("python")
                elif ext in {".js", ".ts", ".jsx", ".tsx"}:
                    languages.add("javascript/typescript")
                elif ext in {".c", ".cpp", ".h"}:
                    languages.add("c/c++")
                elif ext == ".cs":
                    languages.add("csharp")
        # A project with tests/ and a requirements-dev.txt runs pytest.
        if test_command is None and (target / "tests").is_dir() and (
            (target / "requirements-dev.txt").exists() or (target / "pytest.ini").exists()
        ):
            test_command = "pytest"
        return {
            "success": True,
            "path": str(target),
            "entries": entries[:100],
            "entry_count": len(entries),
            "languages": sorted(languages),
            "build_command": build_command,
            "test_command": test_command,
        }

    def detect_test_command(self) -> str | None:
        info = self.inspect()
        return info.get("test_command") if info.get("success") else None
