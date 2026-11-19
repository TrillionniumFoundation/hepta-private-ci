# Original fixture and readonly dependency adapter

This source is frozen before its real original-reference executions. It does not change the two trained adapters, parent, any generation budget, the fixed repository/commit/source order, original patch AST gate or complete-function parser.

The earlier Parso attempt loaded 900 original cases but omitted the repository-root conftest and recorded 134 errors on each side. This version retains exact AFTER root conftest.py and pytest.ini, loads them at their original package-relative location, and rejects unsupported config rather than silently dropping it. The fixed explicit original test-file scope, per-case timeout, outer timeout, immutable test files, isolated network/PID namespaces and capability drop remain. Both BEFORE and exact one-function AFTER receive identical test material.

The earlier Wcmatch attempt recorded a collection error for the missing original dependency. Its original pyproject requires bracex>=3.2.2. The sibling retained official 3.2.2 wheel and manifest have verified PyPI digest, ZIP contents and RECORD entries. They are mounted as an additional read-only directory with outside/inside per-file hashes; the existing venv is unchanged. Package execution occurs only inside the existing real bubblewrap envelope.

The 16 prior CPU codec controls apply to the identical convert AST and original gate. They are not a claim that these new fixture/dependency branches passed a native test: each branch requires new actual before/after receipts. Previous failures, all cases and costs remain valid; no model evaluation or training is performed by source preparation.
