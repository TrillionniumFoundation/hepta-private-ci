#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{path}: expected exactly one replacement, found {count}: {old[:120]!r}"
        )
    target.write_text(text.replace(old, new), encoding="utf-8")


blocking = ".github/workflows/blocking-ci.yml"
replace_once(
    blocking,
    "permissions:\n  contents: read\n",
    "permissions:\n  contents: read\n  checks: read\n",
)
replace_once(
    blocking,
    "  hepta-contract-gate:\n",
    """  runtime-codex-qualification:
    name: Runtime codex qualification fan-in
    needs: scope
    if: needs.scope.outputs.native == 'true' || needs.scope.outputs.full_repo == 'true'
    runs-on: ubuntu-24.04
    timeout-minutes: 125
    steps:
      - name: Checkout exact candidate
        uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2
        with:
          ref: ${{ github.event.pull_request.head.sha || github.sha }}
          fetch-depth: 0
          persist-credentials: false

      - name: Regression-test check fan-in
        run: python3 -m unittest -v scripts.tests.test_wait_for_github_checks

      - name: Require exact-head and synthetic-merge qualification
        env:
          GITHUB_TOKEN: ${{ github.token }}
          TESTED_SHA: ${{ github.event.pull_request.head.sha || github.sha }}
        run: >-
          python3 scripts/wait_for_github_checks.py
          --sha "$TESTED_SHA"
          --timeout-seconds 7200
          "runtime.codex exact-head"
          "runtime.codex synthetic-merge"

  hepta-contract-gate:
""",
)
replace_once(
    blocking,
    """    needs:
      - scope
      - hepta-contract-gate
""",
    """    needs:
      - scope
      - runtime-codex-qualification
      - hepta-contract-gate
""",
)
replace_once(
    blocking,
    """          if not (native or full):
              allowed.append("hepta-contract-gate")
""",
    """          if not (native or full):
              allowed += ["hepta-contract-gate", "runtime-codex-qualification"]
""",
)

target = ROOT / ".github/workflows/runtime-codex-target-host.yml"
target.write_text('name: runtime.codex target-host qualification\n\non:\n  workflow_dispatch:\n    inputs:\n      source_sha:\n        description: Exact qualified source commit to check out\n        required: true\n        type: string\n      agentd_socket:\n        description: Absolute Agentd control socket on the selected host\n        required: true\n        type: string\n      agent_id:\n        description: Exact owning Agent id\n        required: true\n        type: string\n      generation:\n        description: Exact Agent generation\n        required: true\n        type: string\n      model:\n        description: Exact production-candidate model id\n        required: true\n        type: string\n      authority_config:\n        description: Absolute protected final-use authority configuration\n        required: true\n        type: string\n      journal_root:\n        description: Absolute owner-private qualification journal directory\n        required: true\n        type: string\n      iterations:\n        description: Number of physical real-provider canary operations (3..20)\n        required: true\n        default: "5"\n        type: string\n\npermissions:\n  contents: read\n  id-token: write\n  attestations: write\n\nconcurrency:\n  group: runtime-codex-target-host-${{ inputs.agent_id }}-${{ inputs.generation }}\n  cancel-in-progress: false\n\njobs:\n  target-host:\n    name: runtime.codex target-host real-provider\n    runs-on: [self-hosted, linux, runtime-codex-target-host]\n    timeout-minutes: 120\n    env:\n      SOURCE_SHA: ${{ inputs.source_sha }}\n      AGENTD_SOCKET: ${{ inputs.agentd_socket }}\n      AGENT_ID: ${{ inputs.agent_id }}\n      AGENT_GENERATION: ${{ inputs.generation }}\n      MODEL: ${{ inputs.model }}\n      AUTHORITY_CONFIG: ${{ inputs.authority_config }}\n      JOURNAL_ROOT: ${{ inputs.journal_root }}\n      ITERATIONS: ${{ inputs.iterations }}\n      CARGO_INCREMENTAL: 0\n    steps:\n      - name: Check out exact protected candidate\n        uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd\n        with:\n          fetch-depth: 0\n          persist-credentials: false\n          ref: ${{ env.SOURCE_SHA }}\n\n      - name: Prepare repository CI environment\n        uses: ./.github/actions/setup-ci\n\n      - name: Install pinned Rust toolchain\n        uses: dtolnay/rust-toolchain@e081816240890017053eacbb1bdf337761dc5582\n        with:\n          toolchain: 1.95.0\n\n      - name: Verify target-host evidence tooling\n        run: >-\n          python3 -m unittest -v\n          scripts.tests.test_runtime_codex_target_host_evidence\n\n      - name: Fail closed unless the runner is independently provisioned\n        shell: bash\n        run: |\n          set -euo pipefail\n          test "$(git rev-parse HEAD)" = "${SOURCE_SHA}"\n          test -z "$(git status --porcelain --untracked-files=normal)"\n          [[ "${AGENTD_SOCKET}" = /* ]]\n          [[ "${AUTHORITY_CONFIG}" = /* ]]\n          [[ "${JOURNAL_ROOT}" = /* ]]\n          [[ "${ITERATIONS}" =~ ^[0-9]+$ ]]\n          (( ITERATIONS >= 3 && ITERATIONS <= 20 ))\n          test -S "${AGENTD_SOCKET}"\n          test -f "${AUTHORITY_CONFIG}"\n          test -d "${JOURNAL_ROOT}"\n          test "${HEPTA_RUNTIME_CODEX_REAL_PROVIDER:-}" = "1"\n          test -f "${HEPTA_RUNTIME_CODEX_HOST_IDENTITY_EVIDENCE:?}"\n          test -f "${HEPTA_RUNTIME_CODEX_ISSUER_CUSTODY_EVIDENCE:?}"\n          test -f "${HEPTA_RUNTIME_CODEX_ANTI_ROLLBACK_EVIDENCE:?}"\n          test -x "${HEPTA_RUNTIME_CODEX_PROVIDER_AUDIT_EXPORTER:?}"\n          test -x "${HEPTA_RUNTIME_CODEX_FAULT_DRIVER:?}"\n          test -x /usr/bin/time\n          mkdir -p \\\n            "${RUNNER_TEMP}/runtime-codex-target-host/runs" \\\n            "${RUNNER_TEMP}/runtime-codex-target-host/faults"\n\n      - name: Build the named native caller\n        working-directory: codex-rs\n        run: cargo build --locked -p codex-hepta-infer-worker-host --bin hepta-infer-worker\n\n      - name: Execute bounded real-provider canaries\n        shell: bash\n        run: |\n          set -euo pipefail\n          EVIDENCE="${RUNNER_TEMP}/runtime-codex-target-host"\n          BINARY="${CARGO_TARGET_DIR:-$(pwd)/codex-rs/target}/debug/hepta-infer-worker"\n          test -x "${BINARY}"\n          printf \'%s  %s\\n\' "$(sha256sum "${BINARY}" | cut -d\' \' -f1)" "${BINARY}" \\\n            > "${EVIDENCE}/binary.sha256"\n          for iteration in $(seq 1 "${ITERATIONS}"); do\n            request_id="target-host:${GITHUB_RUN_ID}:${GITHUB_RUN_ATTEMPT}:${iteration}"\n            journal="${JOURNAL_ROOT}/runtime-codex-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}.journal"\n            log="${EVIDENCE}/runs/${iteration}.log"\n            resource="${EVIDENCE}/runs/${iteration}.time"\n            output="${EVIDENCE}/runs/${iteration}.json"\n            prompt="Return the exact phrase runtime codex target host canary ${iteration}."\n            printf \'%s\' "${prompt}" | /usr/bin/time -v -o "${resource}" \\\n              "${BINARY}" \\\n                --profile native-app-server \\\n                --agentd-socket "${AGENTD_SOCKET}" \\\n                --agent-id "${AGENT_ID}" \\\n                --generation "${AGENT_GENERATION}" \\\n                --model "${MODEL}" \\\n                --journal "${journal}" \\\n                --request-id "${request_id}" \\\n                --maximum-in-flight 1 \\\n                --final-use-authority-config "${AUTHORITY_CONFIG}" \\\n                --timeout-ms 120000 \\\n              > "${log}" 2>&1\n            tail -n 1 "${log}" > "${output}"\n          done\n          "${HEPTA_RUNTIME_CODEX_PROVIDER_AUDIT_EXPORTER}" \\\n            --source-sha "${SOURCE_SHA}" \\\n            --run-id "${GITHUB_RUN_ID}" \\\n            --attempt "${GITHUB_RUN_ATTEMPT}" \\\n            --expected-requests "${ITERATIONS}" \\\n            --output "${EVIDENCE}/provider-audit.json"\n\n      - name: Execute real-provider crash and acknowledgement-loss matrix\n        shell: bash\n        run: |\n          set -euo pipefail\n          EVIDENCE="${RUNNER_TEMP}/runtime-codex-target-host"\n          BINARY="${CARGO_TARGET_DIR:-$(pwd)/codex-rs/target}/debug/hepta-infer-worker"\n          for scenario in provider-ack-loss event-lag process-death agentd-restart; do\n            "${HEPTA_RUNTIME_CODEX_FAULT_DRIVER}" \\\n              --scenario "${scenario}" \\\n              --source-sha "${SOURCE_SHA}" \\\n              --binary "${BINARY}" \\\n              --agentd-socket "${AGENTD_SOCKET}" \\\n              --agent-id "${AGENT_ID}" \\\n              --generation "${AGENT_GENERATION}" \\\n              --model "${MODEL}" \\\n              --authority-config "${AUTHORITY_CONFIG}" \\\n              --journal-root "${JOURNAL_ROOT}" \\\n              --run-id "${GITHUB_RUN_ID}" \\\n              --attempt "${GITHUB_RUN_ATTEMPT}" \\\n              --output "${EVIDENCE}/faults/${scenario}.json"\n          done\n\n      - name: Build and verify target-host evidence manifest\n        shell: bash\n        run: |\n          set -euo pipefail\n          EVIDENCE="${RUNNER_TEMP}/runtime-codex-target-host"\n          cp "${HEPTA_RUNTIME_CODEX_HOST_IDENTITY_EVIDENCE}" \\\n            "${EVIDENCE}/host-identity.json"\n          cp "${HEPTA_RUNTIME_CODEX_ISSUER_CUSTODY_EVIDENCE}" \\\n            "${EVIDENCE}/issuer-custody.json"\n          cp "${HEPTA_RUNTIME_CODEX_ANTI_ROLLBACK_EVIDENCE}" \\\n            "${EVIDENCE}/anti-rollback.json"\n          python3 scripts/runtime_codex_target_host_evidence.py build \\\n            --evidence-root "${EVIDENCE}" \\\n            --source-sha "${SOURCE_SHA}" \\\n            --source-tree "$(git rev-parse HEAD^{tree})" \\\n            --agent-id "${AGENT_ID}" \\\n            --generation "${AGENT_GENERATION}" \\\n            --model "${MODEL}" \\\n            --iterations "${ITERATIONS}" \\\n            --output "${EVIDENCE}/manifest.json"\n          python3 scripts/runtime_codex_target_host_evidence.py verify \\\n            "${EVIDENCE}/manifest.json"\n          mkdir -p .hepta-evidence/runtime-codex/target-host\n          cp -R "${EVIDENCE}/." .hepta-evidence/runtime-codex/target-host/\n\n      - name: Retain target-host evidence\n        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02\n        with:\n          name: runtime-codex-target-host-${{ env.SOURCE_SHA }}-${{ github.run_id }}\n          path: .hepta-evidence/runtime-codex/target-host/\n          if-no-files-found: error\n          retention-days: 90\n\n      - name: Attest target-host manifest provenance\n        uses: actions/attest-build-provenance@4d101475d8b20a2381f78447822ac1eab6504dd8 # v4.2.2\n        with:\n          subject-path: .hepta-evidence/runtime-codex/target-host/manifest.json\n', encoding="utf-8")
print("runtime.codex required gate and target-host evidence workflow applied")
