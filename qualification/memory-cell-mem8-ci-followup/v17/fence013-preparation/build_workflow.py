from pathlib import Path
import hashlib
import json

HERE = Path(__file__).resolve().parent
REVIEW = HERE.parent / "mem-fence013-feasibility"
index = json.loads((REVIEW / "SOURCE_INDEX.json").read_bytes())
expected = {}
for row in index["files"]:
    if row["path"] in {"action/main.cts", "action/lib.cts", "action/log.cts", "action/post.cts", "action/bundle-manifest.json"}:
        expected[row["path"]] = {"bytes": row["size"], "sha256": row["sha256"], "git_blob": row["sha"]}
expected["action.yml"] = {
    "bytes": 1520,
    "sha256": "26aa17917f78b69320d412e5d4c42617bc458e4f9787afe93055f18e3931430b",
    "git_blob": "97e91823b99e6b549291901818ebb918116c06d6",
}
expected["action/bin/fence"] = {
    "bytes": 2203880,
    "sha256": "1a1ac7ad60216e7803403645c202e8c8a4e738326350ce340f8138df1c9a5e04",
    "git_blob": "77eb796b522a7ae83eb83c42d579f85a41945b3d",
}
helper = (HERE / "capture.template.py").read_text().replace("__EXPECTED_FILES__", repr(dict(sorted(expected.items()))))
compile(helper, "capture.py", "exec")
(HERE / "capture.py").write_text(helper)
before = (HERE / "reference/ORIGINAL_BLOB_WORKFLOW.yml").read_text()
workflow = before.replace("name: blob-size-policy", "name: MEM Fence v0.13 isolated qualification", 1)
workflow = workflow.replace("  workflow_call:\n", "  push:\n    branches: [codex/mem8-fence013-qualification-20261111-ed353817]\n", 1)
workflow = workflow.replace("    timeout-minutes: 30\n", "    if: github.event_name == 'push' && github.ref == 'refs/heads/codex/mem8-fence013-qualification-20261111-ed353817'\n    timeout-minutes: 30\n", 1)
workflow = workflow.replace("      - uses: openai/fence@e6b39c80c51cb2b2a39448ddeff74b3b886c0a63 # pin@v0.10.0", "      - id: fence\n        uses: openai/fence@c7675fea986c29f1d655753a7a61fd6b4141be8f # pin@v0.13.0", 1)
workflow = workflow.replace("      - uses: actions/checkout@", "      - id: checkout\n        uses: actions/checkout@", 1)
workflow = workflow.replace("      - name: Test blob size policy\n", "      - name: Test blob size policy\n        id: policy_tests\n", 1)
workflow = workflow.replace("      - name: Check changed blob sizes\n", "      - name: Check changed blob sizes\n        id: policy_check\n", 1)
workflow = workflow.replace("      - name: Check for a clean worktree\n", "      - name: Check for a clean worktree\n        id: clean\n", 1)
preflight = """      - name: Retain and verify the exact Fence bundle before setup
        id: preflight
        env:
          HARNESS_BEFORE: ${{ github.event.before }}
        shell: bash
        run: |
          set -euo pipefail
          umask 077
          root="$RUNNER_TEMP/mem8-fence013-qualification"
          mkdir "$root"
          mkdir "$root/records"
          cat > "$root/capture.py" <<'PY'
__HELPER__
          PY
          python3 "$root/capture.py" preflight

""".replace("__HELPER__", "\n".join("          " + line if line else "          " for line in helper.splitlines()))
workflow = workflow.replace("      - id: fence\n", preflight + "      - id: fence\n", 1)
before_step = """      - name: Bind the original policy source and isolated harness parent
        id: source_before
        shell: bash
        run: python3 "$RUNNER_TEMP/mem8-fence013-qualification/capture.py" before

"""
workflow = workflow.replace("      - name: Determine comparison range\n", before_step + "      - name: Determine comparison range\n", 1)
workflow += """
      - name: Retain source and action identities after the original checks
        if: always()
        env:
          PREFLIGHT_OUTCOME: ${{ steps.preflight.outcome }}
          FENCE_OUTCOME: ${{ steps.fence.outcome }}
          CHECKOUT_OUTCOME: ${{ steps.checkout.outcome }}
          SOURCE_BEFORE_OUTCOME: ${{ steps.source_before.outcome }}
          RANGE_OUTCOME: ${{ steps.range.outcome }}
          POLICY_TESTS_OUTCOME: ${{ steps.policy_tests.outcome }}
          POLICY_CHECK_OUTCOME: ${{ steps.policy_check.outcome }}
          CLEAN_OUTCOME: ${{ steps.clean.outcome }}
        shell: bash
        run: python3 "$RUNNER_TEMP/mem8-fence013-qualification/capture.py" after

      - name: Preserve original qualification evidence before action post hooks
        if: always()
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: mem8-fence013-qualification-${{ github.run_id }}-${{ github.run_attempt }}
          path: |
            ${{ runner.temp }}/mem8-fence013-qualification/mem-fence013-qualification.tar.xz
            ${{ runner.temp }}/mem8-fence013-qualification/MANIFEST.json
            ${{ runner.temp }}/mem8-fence013-qualification/records/PREFLIGHT_CAPTURE.json
            ${{ runner.temp }}/mem8-fence013-qualification/records/AFTER_CAPTURE.json
          if-no-files-found: error
          retention-days: 14
"""
target = HERE / "source/.github/workflows/hepta-mem-fence013-qualification.yml"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(workflow)
print(json.dumps({"path": str(target), "bytes": len(workflow.encode()), "sha256": hashlib.sha256(workflow.encode()).hexdigest()}))
