from pathlib import Path
import argparse
import hashlib
import json
import textwrap

ROOT = Path(__file__).resolve().parent
WORKFLOW = ".github/workflows/hepta-b23-linux-app-server-original-gate.yml"
BASE = "67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed"


def identity(data):
    return {
        "bytes": len(data),
        "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def original_step(source, marker):
    start = source.index(marker)
    end = source.find("\n      - ", start + len(marker))
    end_job = source.find("\n  test-", start + len(marker))
    candidates = [offset for offset in (end, end_job) if offset >= 0]
    end = min(candidates) if candidates else len(source)
    return source[start:end].rstrip() + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--collector", type=Path)
    parser.add_argument("--collector-sha256")
    parser.add_argument("--collector-git-blob")
    parser.add_argument("--collector-review")
    args = parser.parse_args()
    baseline = (ROOT / "source/.github/workflows/bazel.yml").read_text()
    assert identity(baseline.encode())["git_blob"] == "9eed8ed8fa46c88d9d89d1499f55cb8c303137af"
    guard = (ROOT / "source_identity.py").read_text()
    compile(guard, "inline-source-identity.py", "exec")
    if args.collector:
        if not all((args.collector_sha256, args.collector_git_blob, args.collector_review)):
            parser.error("accepted collector identity and review are required")
        collector = args.collector.read_text()
        if not collector.endswith("\n"):
            parser.error("accepted collector must end with LF for exact heredoc embedding")
        collector_identity = identity(collector.encode())
        if collector_identity["sha256"] != args.collector_sha256:
            parser.error("collector SHA256 mismatch")
        if collector_identity["git_blob"] != args.collector_git_blob:
            parser.error("collector Git blob mismatch")
        compile(collector, "inline-accepted-collector.py", "exec")
        output = ROOT / "candidate" / WORKFLOW
        readiness = "READY_FOR_INDEPENDENT_WORKFLOW_REVIEW"
    else:
        collector = 'raise SystemExit("collector pending independent acceptance; draft only")\n'
        collector_identity = None
        output = ROOT / "draft" / (WORKFLOW + ".template")
        readiness = "DRAFT_COLLECTOR_NOT_ACCEPTED_NOT_PUBLISHABLE"
    checkout = original_step(baseline, "      - uses: actions/checkout@")
    prepare = original_step(baseline, "      - name: Prepare Bazel CI")
    rusty = original_step(baseline, "      - name: Check rusty_v8 MODULE.bazel checksums")
    lock = original_step(baseline, "      - name: Check MODULE.bazel.lock is up to date")
    cache = original_step(baseline, "      - name: Save bazel repository cache")
    clean = original_step(baseline, "      - name: Check for a clean worktree")
    # The baseline step extractor stops on the next step. The clean step is
    # the final step in its job, so explicitly limit it to that complete block.
    clean = clean.split("\n  ", 1)[0] + "\n" if "\n  test-" in clean else clean
    clean = """      - name: Check for a clean worktree
        if: always() && !cancelled()
        uses: ./.github/actions/check-clean-worktree
"""
    template = r"""# B23 keeps the original full Linux AppServer target and all product bytes.
# Diagnostic evidence does not make every main required job green.
name: Hepta B23 original Linux AppServer gate

"on":
  pull_request:
    types: [opened, synchronize, reopened]
    paths:
      - .github/workflows/hepta-b23-linux-app-server-original-gate.yml

permissions:
  contents: read

concurrency:
  group: __DOLLAR__{{ github.workflow }}-__DOLLAR__{{ github.event.pull_request.number }}
  cancel-in-progress: false

jobs:
  test:
    if: github.event.pull_request.head.repo.full_name == github.repository && github.head_ref == 'codex/b23-linux-app-server-original-gate-20261106'
    timeout-minutes: 120
    strategy:
      fail-fast: false
      matrix:
        include:
          - os: ubuntu-24.04
            target: x86_64-unknown-linux-gnu
    runs-on: __DOLLAR__{{ matrix.os }}
    name: Original AppServer target on __DOLLAR__{{ matrix.os }} for __DOLLAR__{{ matrix.target }}
    environment:
      name: bazel
      deployment: false
    steps:
__CHECKOUT__
      - name: Bind original source and merge checkout
        id: source_before
        shell: bash
        run: |
          set -euo pipefail
          cat >"__DOLLAR__{RUNNER_TEMP}/b23-source-identity.py" <<'PY'
__SOURCE_GUARD__
          PY
          python3 "__DOLLAR__{RUNNER_TEMP}/b23-source-identity.py" before
          command -v zstd >"__DOLLAR__{RUNNER_TEMP}/b23-app-server-evidence/zstd-path.txt"
          zstd --version >"__DOLLAR__{RUNNER_TEMP}/b23-app-server-evidence/zstd-version.txt"

__PREPARE__
__RUSTY__
__LOCK__
      - name: Run the original full AppServer unit-test target
        id: bazel
        continue-on-error: true
        env:
          BUILDBUDDY_API_KEY: __DOLLAR__{{ secrets.BUILDBUDDY_API_KEY }}
        shell: bash
        run: |
          set -euo pipefail
          public_dir="__DOLLAR__{RUNNER_TEMP}/b23-app-server-evidence"
          private_dir="__DOLLAR__{RUNNER_TEMP}/b23-app-server-private"
          mkdir -p "__DOLLAR__{public_dir}" "__DOLLAR__{private_dir}"
          bazel_targets=(
            //codex-rs/app-server:app-server-unit-tests
          )
          bazel_wrapper_args=(
            --print-failed-action-summary
            --print-failed-test-logs
          )
          bazel_test_args=(
            test
            --test_tag_filters=-argument-comment-lint
            --test_verbose_timeout_warnings
            --build_metadata=COMMIT_SHA=__DOLLAR__{GITHUB_SHA}
            --nocache_test_results
            --build_event_json_file="__DOLLAR__{private_dir}/build-events.jsonl"
            --nobuild_event_json_file_path_conversion
          )
          set +e
          ./.github/scripts/run-bazel-ci.sh \
            "__DOLLAR__{bazel_wrapper_args[@]}" \
            -- \
            "__DOLLAR__{bazel_test_args[@]}" \
            -- \
            "__DOLLAR__{bazel_targets[@]}" \
            2>&1 | tee "__DOLLAR__{public_dir}/console.log"
          pipeline_status=("__DOLLAR__{PIPESTATUS[@]}")
          set -e
          printf '%s\n' "__DOLLAR__{pipeline_status[0]}" >"__DOLLAR__{public_dir}/original-bazel-exit-code.txt"
          printf '%s\n' "__DOLLAR__{pipeline_status[1]}" >"__DOLLAR__{public_dir}/console-copy-exit-code.txt"
          exit "__DOLLAR__{pipeline_status[0]}"

      - name: Verify source after the original invocation
        id: source_after
        if: always() && !cancelled()
        shell: bash
        run: |
          set -euo pipefail
          python3 "__DOLLAR__{RUNNER_TEMP}/b23-source-identity.py" after

      - name: Collect every produced attempt and gate artifact privacy
        id: evidence
        if: always() && !cancelled()
        env:
          BUILDBUDDY_API_KEY: __DOLLAR__{{ secrets.BUILDBUDDY_API_KEY }}
        shell: bash
        run: |
          set -euo pipefail
          python3 - \
            "__DOLLAR__{RUNNER_TEMP}/b23-app-server-private/build-events.jsonl" \
            "__DOLLAR__{RUNNER_TEMP}/b23-app-server-evidence" \
            "//codex-rs/app-server:app-server-unit-tests" \
            "__DOLLAR__{RUNNER_TEMP}/bazel-execution-logs" <<'PY'
__COLLECTOR__
          PY

      - name: Upload original AppServer attempt evidence
        id: upload_evidence
        if: always() && !cancelled() && steps.evidence.outputs.safe-for-upload == 'true'
        continue-on-error: true
        uses: actions/upload-artifact@bbbca2ddaa5d8feaa63e36b76fdaad77386f024f # v7.0.0
        with:
          name: b23-linux-app-server-__DOLLAR__{{ github.run_id }}-attempt-__DOLLAR__{{ github.run_attempt }}
          path: __DOLLAR__{{ runner.temp }}/b23-app-server-evidence
          if-no-files-found: error

      - name: Upload original Bazel execution logs
        id: upload_compact
        if: always() && !cancelled() && steps.evidence.outputs.safe-for-upload == 'true'
        continue-on-error: true
        uses: actions/upload-artifact@bbbca2ddaa5d8feaa63e36b76fdaad77386f024f # v7.0.0
        with:
          name: b23-linux-app-server-compact-__DOLLAR__{{ github.run_id }}-attempt-__DOLLAR__{{ github.run_attempt }}
          path: __DOLLAR__{{ runner.temp }}/bazel-execution-logs
          if-no-files-found: error

__CACHE__
__CLEAN__
      - name: Preserve the original result and require complete evidence
        if: always() && !cancelled()
        env:
          ORIGINAL_OUTCOME: __DOLLAR__{{ steps.bazel.outcome }}
          SOURCE_BEFORE_OUTCOME: __DOLLAR__{{ steps.source_before.outcome }}
          SOURCE_AFTER_OUTCOME: __DOLLAR__{{ steps.source_after.outcome }}
          EVIDENCE_OUTCOME: __DOLLAR__{{ steps.evidence.outcome }}
          ARTIFACT_SAFE: __DOLLAR__{{ steps.evidence.outputs.safe-for-upload }}
          EVIDENCE_UPLOAD_OUTCOME: __DOLLAR__{{ steps.upload_evidence.outcome }}
          COMPACT_UPLOAD_OUTCOME: __DOLLAR__{{ steps.upload_compact.outcome }}
          JOB_STATUS: __DOLLAR__{{ job.status }}
        shell: bash
        run: |
          set -euo pipefail
          python3 - <<'PY'
          import json
          import os
          from pathlib import Path

          public = Path(os.environ["RUNNER_TEMP"]) / "b23-app-server-evidence"
          required = (
              "ORIGINAL_OUTCOME", "SOURCE_BEFORE_OUTCOME", "SOURCE_AFTER_OUTCOME",
              "EVIDENCE_OUTCOME", "EVIDENCE_UPLOAD_OUTCOME", "COMPACT_UPLOAD_OUTCOME",
              "JOB_STATUS",
          )
          outcomes = {name: os.environ.get(name) for name in required}
          if any(value != "success" for value in outcomes.values()):
              raise SystemExit("original execution or evidence step failed: " + json.dumps(outcomes))
          if os.environ.get("ARTIFACT_SAFE") != "true":
              raise SystemExit("artifact privacy gate did not pass")
          for filename in ("original-bazel-exit-code.txt", "console-copy-exit-code.txt"):
              if (public / filename).read_bytes() != b"0\n":
                  raise SystemExit("nonzero or missing original invocation/console exit")
          for phase in ("before", "after"):
              if json.loads((public / ("source-" + phase + ".json")).read_text())["status"] != "passed":
                  raise SystemExit("original source identity check failed")
          print(json.dumps({
              "original_full_target_exit": 0,
              "complete_evidence_retained": True,
              "independent_B23_acceptance": "pending",
              "all_main_required_jobs_passed": False,
          }))
          PY
"""
    for marker, value in (
        ("__CHECKOUT__", checkout.rstrip()),
        ("__PREPARE__", prepare.rstrip()),
        ("__RUSTY__", rusty.rstrip()),
        ("__LOCK__", lock.rstrip()),
        ("__CACHE__", cache.rstrip()),
        ("__CLEAN__", clean.rstrip()),
        ("__SOURCE_GUARD__", textwrap.indent(guard.rstrip(), "          ")),
        ("__COLLECTOR__", textwrap.indent(collector[:-1], "          ")),
    ):
        assert template.count(marker) == 1, marker
        template = template.replace(marker, value)
    template = template.replace("__DOLLAR__", "$")
    output.parent.mkdir(parents=True, exist_ok=True)
    data = template.encode()
    output.write_bytes(data)
    metadata = {
        "status": readiness,
        "source_commit": BASE,
        "source_tree": "3982ba56dc5a3f1da0c1de7ea57992f88125c359",
        "workflow_path": WORKFLOW,
        "output": str(output),
        "workflow_identity": identity(data),
        "source_identity_helper": identity(guard.encode()),
        "collector": collector_identity,
        "collector_review": args.collector_review,
        "original_product_files_changed": 0,
        "native_executed": False,
        "ref_written": False,
    }
    (ROOT / ("candidate-metadata.json" if args.collector else "draft-metadata.json")).write_text(
        json.dumps(metadata, indent=2) + "\n"
    )
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
