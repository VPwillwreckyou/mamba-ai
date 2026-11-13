# Test and Diagnostics Issue Report

**Date:** 2026-10-15  
**Overall result:** Python tests pass; Java build and spelling verification are blocked by missing project tooling/source context.

## Completed Checks

| Check | Result | Evidence |
| --- | --- | --- |
| Python test suite | PASS | `python -m pytest -q`: 67 passed |
| Local Ollama smoke test | PASS | `python -u verify_ollama.py`: 6/6 passed, including a live `qwen2.5:7b` response |
| Changed-file language diagnostics | PASS | No diagnostics in the checked Python files or `AIProvider.java` |
| Python lint autofix | PARTIAL | 44 safe fixes applied only to touched Python files; tests rerun successfully |
| Spelling verification | NOT RUN | `cspell`, `codespell`, and `typos` are unavailable; no spell-check configuration was found |

## Open Issues

### JAVA-001: Java/Minecraft project cannot be built

- **Severity:** Blocker
- **Affected files:** `src/main/java/com/minerbot/ai/AIAction.java`, `AiService.java`, and related sources
- **Observed:** Java diagnostics cannot resolve Minecraft/Fabric APIs or project classes including `BotManager`, `BotState`, and `BlockRegistrySearch`.
- **Evidence:** The workspace has no Gradle/Maven build descriptor or wrapper. `src/main/java/com/minerbot` currently contains only the `ai` package; the referenced application classes are absent.
- **Impact:** Java compilation and Java tests cannot be run reliably. Creating placeholder classes or guessing Minecraft/Fabric versions would hide the real integration problem rather than fix it.
- **Required to unblock:** Restore/open the complete Java mod project, including its build files, required source packages, Minecraft/Fabric versions and mappings. Then provide or confirm the intended Java test/build command.

### PY-001: `mamba.tools` package is incomplete and cannot import

- **Severity:** Blocker for consumers of this package
- **Affected files:** `mamba/tools/__init__.py`, `mamba/tools/task_engine.py`
- **Observed:** `python -c "import mamba.tools"` fails because `mamba.tools.computer_keyboard` is missing. The initializer also imports other absent modules, and `task_engine.py` refers to undefined task state, confirmation, verification, and execution functions.
- **Evidence:** The workspace contains only `mamba/tools/__init__.py` and `mamba/tools/task_engine.py`; the referenced modules and implementations are absent.
- **Impact:** The package cannot be imported or used. The existing main application tests pass because they do not depend on this package.
- **Required to unblock:** Restore the missing `mamba.tools` modules and the intended task-engine implementation, or confirm that this abandoned package should be removed and its consumers migrated. Reconstructing those APIs from names alone risks inventing behavior.

### LINT-001: Repository-wide Ruff findings remain

- **Severity:** Advisory
- **Observed:** `ruff check . --statistics` reports 291 findings across the repository, including 13 undefined names in the incomplete `mamba.tools` task engine. Fourteen findings remain across touched Python files (12 broad-exception warnings and two suppressed-exception warnings) in provider classification/fallback, task recovery, and UI-safe error boundaries.
- **Impact:** The full repository does not currently pass Ruff. A global autofix would rewrite unrelated files and was not applied.
- **Required to unblock:** Decide whether to schedule a repository-wide lint cleanup separately. Any change to the remaining provider exception boundaries should preserve current multi-provider error classification and fallback behavior.

### SPELL-001: No spelling checker available

- **Severity:** Advisory
- **Observed:** No `cspell`, `codespell`, or `typos` executable or project spell-check configuration was found.
- **Impact:** A dedicated spell-check pass could not be run, so spelling is not certified.
- **Required to unblock:** Install or enable the project's chosen spell checker and define its accepted dictionaries/terms, especially for provider names and technical vocabulary.

## Unblock Form

- **Java project root (if different):** ______________________________
- **Minecraft version:** ___________________________________________
- **Loader and version (Fabric/Forge/other):** ______________________
- **Mappings/toolchain version:** __________________________________
- **JDK version:** ________________________________________________
- **Location of missing Java source packages:** _____________________
- **Expected Java build/test command:** ____________________________
- **Preferred spelling checker/dictionary:** ________________________
