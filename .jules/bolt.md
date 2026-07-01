## 2024-05-18 - Avoid over-eager linter auto-fixes
**Learning:** `ruff check . --fix` can aggressively remove necessary imports from facade modules, breaking application routing. The code review showed that removing unused imports from `__init__` or facade files causes cascading ImportErrors.
**Action:** When fixing linter errors to prepare a PR, always target fixes specifically to the modified file (`ruff check path/to/file.py --fix`) or manually verify every auto-fix to ensure it is not stripping necessary re-exports.
