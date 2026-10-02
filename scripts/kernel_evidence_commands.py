#!/usr/bin/env python3
"""One governed candidate command plan shared by execution and receipt admission."""

import argparse

COMMANDS = {
    "exact_source": 'set -euo pipefail; test "$(git rev-parse HEAD)" = "$SOURCE_SHA"; test "$(git rev-parse HEAD^{tree})" = "$SOURCE_TREE"; cd codex-rs; cargo test --locked -p codex-hepta-evidence; cargo test --locked -p codex-hepta-agentd --lib --test kernel_evidence_product --test kernel_evidence_profile --test kernel_evidence_paging_product --test kernel_evidence_publication_cli',
    "metadata": "set -euo pipefail; bash scripts/kernel_evidence_validate_metadata.sh",
    "publication_diagnostics": 'set -euo pipefail; cd codex-rs; cargo test --locked -p codex-hepta-evidence --lib publication_tests:: -- --nocapture --test-threads=1; cargo test --locked -p codex-hepta-agentd --lib evidence_production::publication_driver_tests:: -- --nocapture --test-threads=1; cd "$GITHUB_WORKSPACE"; python3 - "$READINESS_RECORDS/crash/SUMMARY.json" <<"PY"\nimport json, pathlib, sys\nvalue = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))\nif value.get("schemaVersion") != 2 or value.get("passed") is not True:\n    raise SystemExit("crash matrix is not terminal success")\nif value.get("scenarioCount") != value.get("requiredScenarioCount"):\n    raise SystemExit("crash matrix inventory is incomplete")\nPY',
    "deterministic_merge": 'set -euo pipefail; test "$(git rev-parse HEAD)" = "$MERGE_SHA"; test "$(git rev-parse HEAD^{tree})" = "$MERGE_TREE"; cd codex-rs; cargo test --locked -p codex-hepta-evidence; cargo test --locked -p codex-hepta-agentd --lib --test kernel_evidence_product --test kernel_evidence_profile --test kernel_evidence_paging_product --test kernel_evidence_publication_cli; cd "$GITHUB_WORKSPACE"; SOURCE_SHA="$MERGE_SHA" SOURCE_TREE="$MERGE_TREE" READINESS_RECORDS="$READINESS_RECORDS/merge-metadata" bash scripts/kernel_evidence_validate_metadata.sh >"$READINESS_RECORDS/merge-metadata/metadata/metadata.log" 2>&1',
}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=COMMANDS)
    print(COMMANDS[parser.parse_args().kind])
