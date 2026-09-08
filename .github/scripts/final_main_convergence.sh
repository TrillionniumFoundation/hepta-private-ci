#!/usr/bin/env bash
set -Eeuo pipefail

repo="${GITHUB_REPOSITORY:-TrillionniumFoundation/hepta-private-ci}"
work_branch="ops/final-main-convergence-20260908"
report_dir="convergence"
mkdir -p "$report_dir"
exec > >(tee "$report_dir/final-main-convergence.log") 2>&1

git config user.name "hepta-convergence-bot"
git config user.email "hepta-convergence-bot@users.noreply.github.com"
git fetch origin '+refs/heads/*:refs/remotes/origin/*' '+refs/tags/*:refs/tags/*' --prune

current_branch="$(git branch --show-current)"
if [[ "$current_branch" != "$work_branch" ]]; then
  echo "unexpected branch: $current_branch" >&2
  exit 2
fi

initial_head="$(git rev-parse HEAD)"
main_before="$(git rev-parse origin/main)"
printf '%s\n' "$initial_head" > "$report_dir/initial-head.txt"
printf '%s\n' "$main_before" > "$report_dir/main-before.txt"

# The latest reviewed/converged implementation heads are merged normally.
# Older and diagnostic heads are incorporated later as history-only parents so
# they remain fully reachable without allowing stale trees to overwrite the
# canonical candidate.
canonical_refs=(
  "origin/codex/hepta-v9-blocker-closure-20260908"
  "origin/codex/hepta-w0-seven-lanes-handoff-20260908"
  "origin/reviewer/ci-governance-simplification-20260908"
  "origin/codex/hepta-bao-connect-20260908"
  "origin/codex/hepta-final-gap-closure-r3-20260908"
  "origin/codex/hepta-final-gap-closure-r2-20260908"
  "origin/integration/hepta-w0-internal-closure-20260908"
)

: > "$report_dir/canonical-merges.tsv"
for ref in "${canonical_refs[@]}"; do
  if ! git show-ref --verify --quiet "refs/remotes/${ref#origin/}"; then
    printf '%s\tmissing\n' "$ref" >> "$report_dir/canonical-merges.tsv"
    continue
  fi
  if git merge-base --is-ancestor "$ref" HEAD; then
    printf '%s\talready-contained\n' "$ref" >> "$report_dir/canonical-merges.tsv"
    continue
  fi
  echo "Normal merge of canonical source $ref"
  if git merge --no-ff --no-edit -X theirs "$ref" -m "merge(convergence): ${ref#origin/}"; then
    printf '%s\tnormal-merge\n' "$ref" >> "$report_dir/canonical-merges.tsv"
  else
    git merge --abort || true
    echo "Canonical source $ref has unresolved structural conflicts; refusing history-only downgrade" >&2
    printf '%s\tconflict\n' "$ref" >> "$report_dir/canonical-merges.tsv"
    exit 3
  fi
done

# Repair the reproduced reqwest/rustls 0.23 source-chain classification gap.
python3 .github/scripts/fix_http_tls_classification.py

# Capture every branch tip with a namespaced archive tag before deleting refs.
# Branch names are valid ref suffixes, so they are also valid below refs/tags.
mapfile -t remote_refs < <(
  git for-each-ref --format='%(refname:short)' refs/remotes/origin \
    | grep -v '^origin/HEAD$' \
    | sort -u
)
: > "$report_dir/archive-tags.tsv"
for ref in "${remote_refs[@]}"; do
  branch="${ref#origin/}"
  tag="archive/branch-tip/20260908/$branch"
  sha="$(git rev-parse "$ref")"
  if git show-ref --verify --quiet "refs/tags/$tag"; then
    existing="$(git rev-parse "refs/tags/$tag^{commit}")"
    if [[ "$existing" != "$sha" ]]; then
      tag="archive/branch-tip/20260908/$branch-${sha:0:12}"
    fi
  fi
  git tag -a "$tag" "$sha" -m "Archive branch tip $branch before single-main-tree convergence"
  printf '%s\t%s\t%s\n' "$branch" "$sha" "$tag" >> "$report_dir/archive-tags.tsv"
done

# Incorporate every remaining branch tip as a parent of the convergence history.
# This is deliberately an 'ours' history merge for residual heads: canonical
# code was selected above, while old backup/diagnostic/one-shot trees are not
# permitted to reintroduce superseded files.
: > "$report_dir/history-merges.tsv"
for ref in "${remote_refs[@]}"; do
  branch="${ref#origin/}"
  [[ "$branch" == "$work_branch" ]] && continue
  if git merge-base --is-ancestor "$ref" HEAD; then
    printf '%s\talready-contained\n' "$branch" >> "$report_dir/history-merges.tsv"
    continue
  fi
  echo "History-only merge of residual branch $branch"
  git merge --no-ff --no-edit -s ours --allow-unrelated-histories "$ref" \
    -m "merge(history): absorb $branch into canonical main lineage"
  printf '%s\thistory-only\n' "$branch" >> "$report_dir/history-merges.tsv"
done

# Strong graph invariant: every fetched branch tip must now be reachable.
python3 - <<'PY'
from __future__ import annotations
import json
import subprocess
from pathlib import Path

refs = subprocess.check_output(
    ["git", "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"],
    text=True,
).splitlines()
refs = sorted(ref for ref in refs if ref != "origin/HEAD")
rows = []
not_reachable = []
for ref in refs:
    sha = subprocess.check_output(["git", "rev-parse", ref], text=True).strip()
    reachable = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ref, "HEAD"],
        check=False,
    ).returncode == 0
    branch = ref.removeprefix("origin/")
    rows.append({"branch": branch, "sha": sha, "reachable_from_convergence": reachable})
    if not reachable:
        not_reachable.append(branch)
Path("convergence/branch-closure.json").write_text(
    json.dumps(
        {
            "schema": 1,
            "convergence_head": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True
            ).strip(),
            "branches": rows,
            "unreachable": not_reachable,
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
if not_reachable:
    raise SystemExit(f"unreachable branch tips: {not_reachable}")
PY

# The temporary controller must not survive in the canonical source tree.
rm -f \
  .github/convergence-probe.txt \
  .github/scripts/final_main_convergence.sh \
  .github/scripts/fix_http_tls_classification.py \
  .github/workflows/final-main-convergence.yml

# Persist the exact graph policy and the distinction between repository-closed
# gaps and external evidence gates.  No status is promoted merely by editing a
# claim file.
cat > "$report_dir/FINAL_MAIN_CONVERGENCE_20260908.md" <<'EOF'
# Final main convergence — 2026-09-08

The canonical source tree is selected from the latest Hepta W0/V9, CI-governance,
and HeptaBao convergence heads.  Those heads are normal merges.  Every residual
backup, diagnostic, controller and superseded branch is absorbed as a history-only
parent, which preserves full reachability without reintroducing stale files.

Before branch deletion every remote branch tip is retained by an annotated
`archive/branch-tip/20260908/...` tag.  `branch-closure.json` is the machine-readable
reachability receipt.

Repository-controlled blockers are admitted only after formatting, HTTP-client
TLS regression tests, workspace check, workspace Clippy and workspace tests pass.
Independent approval, future-duration evidence, owner consent, physical SIL/HIL,
operator acceptance and production release decisions are not self-issued by this
convergence operation and remain explicit external gates where applicable.
EOF

# Validate the resulting canonical tree.  Each command is fail-closed.
export CARGO_NET_GIT_FETCH_WITH_CLI=true
export CARGO_INCREMENTAL=0
mkdir -p "$RUNNER_TEMP/hepta-target"
export CARGO_TARGET_DIR="$RUNNER_TEMP/hepta-target"

run_gate() {
  local name="$1"
  shift
  echo "::group::$name"
  set +e
  "$@" 2>&1 | tee "$report_dir/$name.log"
  local rc=${PIPESTATUS[0]}
  set -e
  printf '%s\n' "$rc" > "$report_dir/$name.rc"
  echo "::endgroup::"
  return "$rc"
}

run_gate cargo-fmt cargo fmt --all -- --check
run_gate http-client-tests cargo test --locked -p codex-http-client --all-targets
run_gate workspace-check cargo check --locked --workspace --all-targets
run_gate workspace-clippy cargo clippy --locked --workspace --all-targets -- -D warnings
run_gate workspace-test cargo test --locked --workspace --all-targets

git diff --check

# Commit only durable source changes and receipts; large raw logs remain workflow
# artifacts and are excluded from the repository commit.
find "$report_dir" -type f -name '*.log' -delete

git add -A
git commit -s -m "merge: converge every branch into the canonical main lineage" \
  -m "Normal-merge current implementation heads; absorb superseded heads as history-only parents; close nested rustls TLS classification; record branch reachability and strict validation receipts."

git push origin "HEAD:refs/heads/$work_branch" --follow-tags

# Create one final PR if it does not already exist.  The PR is never admin-merged
# here; ordinary protected-branch checks remain authoritative.
existing="$(gh pr list --repo "$repo" --state open --head "$work_branch" --json number --jq '.[0].number // empty')"
if [[ -z "$existing" ]]; then
  gh pr create --repo "$repo" --base main --head "$work_branch" \
    --title "merge: final all-branch convergence into main" \
    --body-file "$report_dir/FINAL_MAIN_CONVERGENCE_20260908.md"
else
  echo "PR #$existing already exists"
fi
