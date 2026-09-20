# Script entrypoint index

This generated index maps every repository script to workflow, just/make or manual callers. `candidate-archive` means no textual caller was found; archive or delete only after an owner confirms dynamic invocation is absent.

| Script | Status | Entry points | Callers |
|---|---|---|---|
| `scripts/hepta-repository-integrity.py` | `active` | CI | `.github/workflows/hepta-diagnostic-source-export.yml`, `.github/workflows/hepta-repository-integrity.yml` |
| `scripts/test_hepta_cleanup_consumers.py` | `candidate-archive` | manual/indirect | — |
| `scripts/format.py` | `active` | just/make | `justfile` |
| `scripts/hepta-launchd-cutover-bridge` | `candidate-archive` | manual/indirect | — |
| `scripts/hepta_source_registry_closure.py` | `candidate-archive` | manual/indirect | — |
| `scripts/just-shell.py` | `active` | just/make | `justfile` |
| `scripts/hepta-state-snapshot` | `candidate-archive` | manual/indirect | — |
| `scripts/hepta-generation-pointer` | `candidate-archive` | manual/indirect | — |
| `scripts/list-bazel-clippy-targets.sh` | `active` | CI, just/make | `.github/workflows/bazel.yml`, `justfile` |
| `scripts/hepta-cns.py` | `active` | CI | `.github/workflows/hepta-audit-remediation.yml`, `.github/workflows/hepta-cns-embodiment.yml`, `.github/workflows/hepta-deployment-handoff.yml`, `.github/workflows/hepta-development-docs.yml`, `.github/workflows/hepta-implementation-readiness.yml` |
| `scripts/test_hepta_ci_v8.py` | `active` | CI | `.github/workflows/hepta-consolidated-source.yml` |
| `scripts/test_verify_cargo_lock.py` | `active` | CI | `.github/workflows/hepta-converged-learning.yml`, `.github/workflows/hepta-lane-d-semantic-conformance.yml`, `.github/workflows/hepta-ndu-recursion.yml` |
| `scripts/lane_a_foundation_lib.py` | `candidate-archive` | manual/indirect | — |
| `scripts/uv.lock` | `candidate-archive` | manual/indirect | — |
| `scripts/check_blob_size.py` | `active` | CI | `.github/workflows/blob-size-policy.yml` |
| `scripts/hepta-install-live-gateway` | `candidate-archive` | manual/indirect | — |
| `scripts/verify_hepta_callers.py` | `active` | CI | `.github/workflows/lane-a-foundation.yml`, `.github/workflows/repo-checks.yml` |
| `scripts/test_hepta_paper_evidence.py` | `active` | CI | `.github/workflows/hepta-cns-embodiment.yml` |
| `scripts/hepta-implementation-maps.py` | `active` | CI, indirect | `scripts/hepta-module-docs.py` |
| `scripts/test_hepta_ci_source_identity.py` | `active` | CI | `.github/workflows/hepta-consolidated-source.yml` |
| `scripts/verify_lane_a_foundation.py` | `active` | CI | `.github/workflows/lane-a-foundation.yml` |
| `scripts/hepta-module-docs.py` | `active` | CI | `.github/workflows/hepta-algorithm-docs.yml`, `.github/workflows/hepta-audit-remediation.yml`, `.github/workflows/hepta-cns-embodiment.yml`, `.github/workflows/hepta-converged-learning.yml`, `.github/workflows/hepta-deployment-handoff.yml`, `.github/workflows/hepta-development-docs.yml`, `.github/workflows/hepta-diagnostic-source-export.yml`, `.github/workflows/hepta-implementation-readiness.yml` |
| `scripts/hepta-cutover-guard` | `candidate-archive` | manual/indirect | — |
| `scripts/check-module-bazel-lock.sh` | `active` | CI, just/make | `.github/workflows/bazel.yml`, `.github/workflows/hepta-diagnostic-source-export.yml`, `justfile` |
| `scripts/verify_cargo_lock.py` | `active` | CI | `.github/workflows/hepta-converged-learning.yml`, `.github/workflows/hepta-lane-d-semantic-conformance.yml`, `.github/workflows/hepta-ndu-recursion.yml` |
| `scripts/test_hepta_module_status_facts.py` | `candidate-archive` | manual/indirect | — |
| `scripts/test-remote-env.sh` | `active` | CI | `.github/workflows/rust-ci-full-nextest-platform.yml` |
| `scripts/hepta-technical-receipts.py` | `active` | manual, indirect | `scripts/hepta-technical-receipts.py` |
| `scripts/test_hepta_module_doc_metadata.py` | `active` | CI | `.github/workflows/hepta-audit-remediation.yml` |
| `scripts/run_tui_with_exec_server.sh` | `active` | just/make | `justfile` |
| `scripts/readme_toc.py` | `active` | CI | `.github/workflows/repo-checks.yml` |
| `scripts/test_hepta_lane_d_scope.py` | `active` | CI | `.github/workflows/hepta-consolidated-source.yml` |
| `scripts/hepta-docs.py` | `active` | CI | `.github/workflows/hepta-algorithm-docs.yml`, `.github/workflows/hepta-audit-remediation.yml`, `.github/workflows/hepta-cns-embodiment.yml`, `.github/workflows/hepta-consolidated-source.yml`, `.github/workflows/hepta-converged-learning.yml`, `.github/workflows/hepta-development-docs.yml`, `.github/workflows/hepta-diagnostic-source-export.yml`, `.github/workflows/hepta-implementation-readiness.yml` |
| `scripts/hepta-technical-closure.py` | `active` | CI | `.github/workflows/hepta-implementation-readiness.yml` |
| `scripts/test_hepta_cleanup_history.py` | `active` | CI | `.github/workflows/hepta-development-docs.yml` |
| `scripts/hepta-lane-e-closure.py` | `active` | CI | `.github/workflows/hepta-lane-e-gap-closure.yml` |
| `scripts/list-bazel-release-targets.sh` | `active` | CI | `.github/workflows/bazel.yml` |
| `scripts/build_codex_package.py` | `active` | just/make | `justfile` |
| `scripts/hepta-readiness.py` | `active` | CI | `.github/workflows/hepta-converged-learning.yml`, `.github/workflows/hepta-development-docs.yml`, `.github/workflows/hepta-implementation-readiness.yml` |
| `scripts/stage_npm_packages.py` | `active` | CI | `.github/workflows/rust-release.yml` |
| `scripts/test_hepta_lane_b_truth.py` | `active` | CI | `.github/workflows/hepta-lane-b-truth.yml` |
| `scripts/hepta-hnmf.py` | `active` | CI | `.github/workflows/hepta-cns-embodiment.yml`, `.github/workflows/hepta-development-docs.yml`, `.github/workflows/hepta-diagnostic-source-export.yml`, `.github/workflows/hepta-implementation-readiness.yml`, `.github/workflows/hnmf-qualification.yml` |
| `scripts/hepta-gap-closure.py` | `active` | CI | `.github/workflows/hepta-audit-remediation.yml`, `.github/workflows/hepta-consolidated-source.yml` |
| `scripts/asciicheck.py` | `active` | CI | `.github/workflows/repo-checks.yml` |
| `scripts/hepta-lane-d-semantic-conformance.py` | `active` | CI | `.github/workflows/hepta-lane-d-semantic-conformance.yml` |
| `scripts/start-codex-exec.sh` | `candidate-archive` | manual/indirect | — |
| `scripts/hepta-live-soak.sh` | `candidate-archive` | manual/indirect | — |
| `scripts/hepta-lane-b-truth.py` | `active` | CI | `.github/workflows/hepta-lane-b-truth.yml` |
| `scripts/hepta-watchdog.sh` | `candidate-archive` | manual/indirect | — |
| `scripts/test_hepta_gap_closure.py` | `candidate-archive` | manual/indirect | — |
| `scripts/hepta_ci_v8.py` | `active` | CI | `.github/workflows/hepta-consolidated-source.yml` |
| `scripts/pyproject.toml` | `candidate-archive` | manual/indirect | — |
| `scripts/verify_lane_a_pr_tuple.py` | `active` | CI | `.github/workflows/lane-a-foundation.yml` |
| `scripts/hepta-immutable-release-tree` | `candidate-archive` | manual/indirect | — |
| `scripts/hepta-implementation-dossiers.py` | `active` | CI | `.github/workflows/hepta-implementation-readiness.yml` |
| `scripts/debug-codex.sh` | `candidate-archive` | manual/indirect | — |
| `scripts/run_lane_a_native_qualification.sh` | `active` | CI | `.github/workflows/lane-a-foundation.yml` |
| `scripts/hepta-paper-evidence.py` | `active` | CI | `.github/workflows/hepta-cns-embodiment.yml` |
| `scripts/hepta_module_doc_metadata.py` | `active` | CI | `.github/workflows/hepta-audit-remediation.yml`, `.github/workflows/hepta-consolidated-source.yml` |
| `scripts/verify_openbao_compatibility.py` | `active` | CI, just/make | `.github/workflows/openbao-compatibility.yml`, `justfile` |
| `scripts/hepta-algorithm-docs.py` | `active` | CI | `.github/workflows/hepta-algorithm-docs.yml`, `.github/workflows/hepta-cns-embodiment.yml`, `.github/workflows/hepta-development-docs.yml`, `.github/workflows/hepta-diagnostic-source-export.yml`, `.github/workflows/hepta-implementation-readiness.yml` |
| `scripts/hepta-install-live-watchdog` | `candidate-archive` | manual/indirect | — |
| `scripts/lane_a_foundation_core.py` | `candidate-archive` | manual/indirect | — |
| `scripts/.venv/.lock` | `candidate-archive` | manual/indirect | — |
| `scripts/.venv/pyvenv.cfg` | `candidate-archive` | manual/indirect | — |
| `scripts/.venv/CACHEDIR.TAG` | `candidate-archive` | manual/indirect | — |
| `scripts/.venv/.gitignore` | `candidate-archive` | manual/indirect | — |
| `scripts/hepta-runtime-tests/canary-e2e.sh` | `candidate-archive` | manual/indirect | — |
| `scripts/codex_package/test_zsh.py` | `candidate-archive` | manual/indirect | — |
| `scripts/codex_package/test_layout.py` | `candidate-archive` | manual/indirect | — |
| `scripts/codex_package/test_cargo.py` | `candidate-archive` | manual/indirect | — |
| `scripts/codex_package/test_cli.py` | `candidate-archive` | manual/indirect | — |
| `scripts/codex_package/layout.py` | `candidate-archive` | manual/indirect | — |
| `scripts/codex_package/README.md` | `active` | CI | `.github/workflows/hepta-cns-embodiment.yml`, `.github/workflows/hnmf-qualification.yml`, `.github/workflows/repo-checks.yml` |
| `scripts/codex_package/v8.py` | `candidate-archive` | manual/indirect | — |
| `scripts/codex_package/dotslash.py` | `candidate-archive` | manual/indirect | — |
| `scripts/codex_package/ripgrep.py` | `candidate-archive` | manual/indirect | — |
| `scripts/codex_package/cargo.py` | `candidate-archive` | manual/indirect | — |
| `scripts/codex_package/version.py` | `candidate-archive` | manual/indirect | — |
| `scripts/codex_package/test_archive.py` | `candidate-archive` | manual/indirect | — |
| `scripts/codex_package/cli.py` | `candidate-archive` | manual/indirect | — |
| `scripts/codex_package/rg` | `active` | CI | `.github/workflows/rust-release.yml` |
| `scripts/codex_package/archive.py` | `candidate-archive` | manual/indirect | — |
| `scripts/codex_package/__init__.py` | `candidate-archive` | manual/indirect | — |
| `scripts/codex_package/zsh.py` | `candidate-archive` | manual/indirect | — |
| `scripts/codex_package/targets.py` | `candidate-archive` | manual/indirect | — |
| `scripts/codex_package/codex-zsh` | `candidate-archive` | manual/indirect | — |
| `scripts/install/test_install_sh.py` | `candidate-archive` | manual/indirect | — |
| `scripts/install/install.sh` | `active` | CI | `.github/workflows/rust-release.yml` |
| `scripts/install/install.ps1` | `active` | CI | `.github/workflows/rust-release.yml` |
| `scripts/mcp_conformance/test_official_conformance.py` | `candidate-archive` | manual/indirect | — |
| `scripts/mcp_conformance/run_codex_compliance.py` | `candidate-archive` | manual/indirect | — |
| `scripts/mcp_conformance/test_codex_compliance.py` | `candidate-archive` | manual/indirect | — |
| `scripts/mcp_conformance/test_review_regressions.py` | `candidate-archive` | manual/indirect | — |
| `scripts/mcp_conformance/regression-baseline-v1.json` | `candidate-archive` | manual/indirect | — |
| `scripts/mcp_conformance/review_regressions.py` | `candidate-archive` | manual/indirect | — |
| `scripts/mcp_conformance/README.md` | `active` | CI | `.github/workflows/hepta-cns-embodiment.yml`, `.github/workflows/hnmf-qualification.yml`, `.github/workflows/repo-checks.yml` |
| `scripts/mcp_conformance/codex_conformance_adapter.py` | `candidate-archive` | manual/indirect | — |
| `scripts/mcp_conformance/server.py` | `candidate-archive` | manual/indirect | — |
| `scripts/mcp_conformance/test_server.py` | `candidate-archive` | manual/indirect | — |
| `scripts/mcp_conformance/review-regression-baseline-v1.json` | `candidate-archive` | manual/indirect | — |
| `scripts/mcp_conformance/official_conformance.py` | `candidate-archive` | manual/indirect | — |
| `scripts/.venv/bin/activate.fish` | `candidate-archive` | manual/indirect | — |
| `scripts/.venv/bin/activate.ps1` | `candidate-archive` | manual/indirect | — |
| `scripts/.venv/bin/activate.bat` | `candidate-archive` | manual/indirect | — |
| `scripts/.venv/bin/activate.nu` | `candidate-archive` | manual/indirect | — |
| `scripts/.venv/bin/activate.csh` | `candidate-archive` | manual/indirect | — |
| `scripts/.venv/bin/activate_this.py` | `candidate-archive` | manual/indirect | — |
| `scripts/.venv/bin/python3` | `active` | CI, just/make | `.github/workflows/Dockerfile.bazel`, `.github/workflows/bazel.yml`, `.github/workflows/blob-size-policy.yml`, `.github/workflows/blocking-ci.yml`, `.github/workflows/hepta-algorithm-docs.yml`, `.github/workflows/hepta-assimilation-discovery.yml`, `.github/workflows/hepta-audit-remediation.yml`, `.github/workflows/hepta-cns-embodiment.yml` (+28) |
| `scripts/.venv/bin/ruff` | `active` | CI | `.github/workflows/hepta-diagnostic-source-export.yml`, `.github/workflows/sdk.yml` |
| `scripts/.venv/bin/pydoc.bat` | `candidate-archive` | manual/indirect | — |
| `scripts/.venv/bin/deactivate.bat` | `candidate-archive` | manual/indirect | — |
| `scripts/.venv/bin/python` | `active` | CI, just/make | `.github/workflows/bazel.yml`, `.github/workflows/hepta-diagnostic-source-export.yml`, `.github/workflows/python-sdk-release.yml`, `.github/workflows/repo-checks.yml`, `.github/workflows/rust-release-windows.yml`, `.github/workflows/sdk.yml`, `justfile` |
| `scripts/.venv/bin/python3.13` | `candidate-archive` | manual/indirect | — |
| `scripts/.venv/bin/activate` | `candidate-archive` | manual/indirect | — |
| `scripts/.venv/lib/python3.13/site-packages/_virtualenv.pth` | `candidate-archive` | manual/indirect | — |
| `scripts/.venv/lib/python3.13/site-packages/_virtualenv.py` | `candidate-archive` | manual/indirect | — |
| `scripts/.venv/lib/python3.13/site-packages/ruff/__main__.py` | `candidate-archive` | manual/indirect | — |
| `scripts/.venv/lib/python3.13/site-packages/ruff/_find_ruff.py` | `candidate-archive` | manual/indirect | — |
| `scripts/.venv/lib/python3.13/site-packages/ruff/__init__.py` | `candidate-archive` | manual/indirect | — |
| `scripts/.venv/lib/python3.13/site-packages/ruff-0.15.13.dist-info/REQUESTED` | `candidate-archive` | manual/indirect | — |
| `scripts/.venv/lib/python3.13/site-packages/ruff-0.15.13.dist-info/RECORD` | `candidate-archive` | manual/indirect | — |
| `scripts/.venv/lib/python3.13/site-packages/ruff-0.15.13.dist-info/METADATA` | `candidate-archive` | manual/indirect | — |
| `scripts/.venv/lib/python3.13/site-packages/ruff-0.15.13.dist-info/INSTALLER` | `candidate-archive` | manual/indirect | — |
| `scripts/.venv/lib/python3.13/site-packages/ruff-0.15.13.dist-info/WHEEL` | `candidate-archive` | manual/indirect | — |
| `scripts/.venv/lib/python3.13/site-packages/ruff-0.15.13.dist-info/sboms/ruff.cyclonedx.json` | `candidate-archive` | manual/indirect | — |
| `scripts/.venv/lib/python3.13/site-packages/ruff-0.15.13.dist-info/licenses/LICENSE` | `candidate-archive` | manual/indirect | — |
| `scripts/codex_package/smoke_tests/uv.lock` | `candidate-archive` | manual/indirect | — |
| `scripts/codex_package/smoke_tests/conftest.py` | `candidate-archive` | manual/indirect | — |
| `scripts/codex_package/smoke_tests/fixtures.py` | `candidate-archive` | manual/indirect | — |
| `scripts/codex_package/smoke_tests/test_codex_package.py` | `candidate-archive` | manual/indirect | — |
| `scripts/codex_package/smoke_tests/pyproject.toml` | `candidate-archive` | manual/indirect | — |
