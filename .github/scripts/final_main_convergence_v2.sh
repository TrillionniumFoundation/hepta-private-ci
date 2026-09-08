#!/usr/bin/env bash
set -Eeuo pipefail

repo="${GITHUB_REPOSITORY:-TrillionniumFoundation/hepta-private-ci}"
work_branch="ops/final-main-convergence-20260908"
report_dir="convergence"
mkdir -p "$report_dir"
exec > >(tee "$report_dir/final-main-convergence-v2.log") 2>&1

git config user.name "hepta-convergence-bot"
git config user.email "hepta-convergence-bot@users.noreply.github.com"
git fetch origin '+refs/heads/*:refs/remotes/origin/*' '+refs/tags/*:refs/tags/*' --prune

[[ "$(git branch --show-current)" == "$work_branch" ]] || {
  echo "unexpected checkout branch" >&2
  exit 2
}

printf '%s\n' "$(git rev-parse HEAD)" > "$report_dir/initial-head.txt"
printf '%s\n' "$(git rev-parse origin/main)" > "$report_dir/main-before.txt"

resolve_conflicts() {
  local preference="$1"
  mapfile -d '' conflicts < <(git diff --name-only --diff-filter=U -z)
  for path in "${conflicts[@]}"; do
    if [[ "$preference" == theirs ]]; then
      if git ls-files -u -- "$path" | awk '$3 == 3 {found=1} END {exit !found}'; then
        git checkout --theirs -- "$path"
        git add -- "$path"
      else
        git rm -f --ignore-unmatch -- "$path"
      fi
    else
      if git ls-files -u -- "$path" | awk '$3 == 2 {found=1} END {exit !found}'; then
        git checkout --ours -- "$path"
        git add -- "$path"
      else
        git rm -f --ignore-unmatch -- "$path"
      fi
    fi
  done
  if git diff --name-only --diff-filter=U | grep -q .; then
    echo "unresolved paths remain" >&2
    git diff --name-only --diff-filter=U >&2
    return 1
  fi
}

merge_normal() {
  local ref="$1"
  local preference="$2"
  local label="$3"
  if git merge-base --is-ancestor "$ref" HEAD; then
    printf '%s\talready-contained\n' "$ref" >> "$report_dir/canonical-merges.tsv"
    return 0
  fi
  echo "Normal merge: $ref ($preference on conflicts)"
  set +e
  git merge --no-ff --no-edit -X "$preference" "$ref" -m "merge(convergence): $label"
  local rc=$?
  set -e
  if [[ $rc -ne 0 ]]; then
    resolve_conflicts "$preference"
    git commit -s --no-edit
  fi
  printf '%s\tnormal-merge\t%s\n' "$ref" "$preference" >> "$report_dir/canonical-merges.tsv"
}

: > "$report_dir/canonical-merges.tsv"
primary=""
for candidate in \
  "origin/codex/hepta-v9-blocker-closure-20260908" \
  "origin/codex/hepta-w0-seven-lanes-handoff-20260908" \
  "origin/codex/hepta-bao-connect-20260908" \
  "origin/codex/hepta-final-gap-closure-r3-20260908"; do
  if git show-ref --verify --quiet "refs/remotes/$candidate"; then
    primary="$candidate"
    break
  fi
done
[[ -n "$primary" ]] || { echo "no canonical Hepta candidate exists" >&2; exit 3; }
merge_normal "$primary" theirs "primary ${primary#origin/}"

supplemental_refs=(
  "origin/reviewer/ci-governance-simplification-20260908"
  "origin/codex/hepta-bao-connect-20260908"
  "origin/codex/hepta-w0-seven-lanes-handoff-20260908"
  "origin/codex/hepta-final-gap-closure-r3-20260908"
  "origin/codex/hepta-final-gap-closure-r2-20260908"
  "origin/integration/hepta-w0-internal-closure-20260908"
)
for ref in "${supplemental_refs[@]}"; do
  if git show-ref --verify --quiet "refs/remotes/$ref"; then
    merge_normal "$ref" ours "supplement ${ref#origin/}"
  else
    printf '%s\tmissing\n' "$ref" >> "$report_dir/canonical-merges.tsv"
  fi
done

python3 .github/scripts/fix_http_tls_classification.py

mapfile -t remote_refs < <(
  git for-each-ref --format='%(refname:short)' refs/remotes/origin \
    | grep -v '^origin/HEAD$' \
    | sort -u
)

: > "$report_dir/archive-tags.tsv"
for ref in "${remote_refs[@]}"; do
  branch="${ref#origin/}"
  sha="$(git rev-parse "$ref")"
  tag="archive/branch-tip/20260908/$branch"
  if git show-ref --verify --quiet "refs/tags/$tag"; then
    existing="$(git rev-parse "refs/tags/$tag^{commit}")"
    [[ "$existing" == "$sha" ]] || tag="$tag-${sha:0:12}"
  fi
  git tag -a "$tag" "$sha" -m "Archive $branch before single-main-tree convergence"
  printf '%s\t%s\t%s\n' "$branch" "$sha" "$tag" >> "$report_dir/archive-tags.tsv"
done

: > "$report_dir/history-merges.tsv"
for ref in "${remote_refs[@]}"; do
  branch="${ref#origin/}"
  [[ "$branch" == "$work_branch" ]] && continue
  if git merge-base --is-ancestor "$ref" HEAD; then
    printf '%s\talready-contained\n' "$branch" >> "$report_dir/history-merges.tsv"
  else
    git merge --no-ff --no-edit -s ours --allow-unrelated-histories "$ref" \
      -m "merge(history): absorb $branch into canonical main lineage"
    printf '%s\thistory-only\n' "$branch" >> "$report_dir/history-merges.tsv"
  fi
done

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
unreachable = []
for ref in refs:
    sha = subprocess.check_output(["git", "rev-parse", ref], text=True).strip()
    ok = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ref, "HEAD"], check=False
    ).returncode == 0
    branch = ref.removeprefix("origin/")
    rows.append({"branch": branch, "sha": sha, "reachable_from_convergence": ok})
    if not ok:
        unreachable.append(branch)
Path("convergence/branch-closure.json").write_text(
    json.dumps(
        {
            "schema": 1,
            "convergence_head": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True
            ).strip(),
            "branches": rows,
            "unreachable": unreachable,
        },
        indent=2,
    ) + "\n",
    encoding="utf-8",
)
if unreachable:
    raise SystemExit(f"unreachable branch tips: {unreachable}")
PY

cat > "$report_dir/FINAL_MAIN_CONVERGENCE_20260908.md" <<'EOF'
# Final main convergence — 2026-09-08

The canonical tree is selected by normal-merging the newest V9/W0 Hepta source,
CI-governance cleanup and HeptaBao final-use implementation.  Primary conflicts
select the newest candidate side; supplemental conflicts retain the already
converged tree.  Residual backup, diagnostic, controller and superseded heads
are incorporated only as history parents, so every commit remains reachable
without reintroducing stale files.

Every branch tip is retained by an annotated `archive/branch-tip/20260908/...`
tag before branch deletion. `branch-closure.json` is the exact reachability
receipt. Repository-controlled admission remains fail-closed on formatting,
HTTP/TLS regression tests, workspace check, Clippy and workspace tests.

Independent human approval, owner authorization, future-duration experiments,
physical SIL/HIL, operator acceptance and production release decisions are not
self-issued by this operation and remain external gates where applicable.
EOF

export CARGO_NET_GIT_FETCH_WITH_CLI=true
export CARGO_INCREMENTAL=0
export CARGO_TARGET_DIR="$RUNNER_TEMP/hepta-target"
mkdir -p "$CARGO_TARGET_DIR"

run_gate() {
  local name="$1"; shift
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
mkdir -p "$RUNNER_TEMP/final-main-convergence-evidence"
cp -a "$report_dir/." "$RUNNER_TEMP/final-main-convergence-evidence/"
find "$report_dir" -type f -name '*.log' -delete

rm -f \
  .github/convergence-probe.txt \
  .github/scripts/final_main_convergence.sh \
  .github/scripts/final_main_convergence_v2.sh \
  .github/scripts/fix_http_tls_classification.py \
  .github/workflows/final-main-convergence.yml \
  .github/workflows/final-main-convergence-v2.yml

git add -A
git commit -s -m "merge: converge every branch into the canonical main lineage" \
  -m "Normal-merge current implementation heads; absorb superseded heads as history-only parents; close nested rustls TLS classification; record exact reachability and strict validation receipts."
git push origin "HEAD:refs/heads/$work_branch" --follow-tags

existing="$(gh pr list --repo "$repo" --state open --head "$work_branch" --json number --jq '.[0].number // empty')"
if [[ -z "$existing" ]]; then
  gh pr create --repo "$repo" --base main --head "$work_branch" \
    --title "merge: final all-branch convergence into main" \
    --body-file "$report_dir/FINAL_MAIN_CONVERGENCE_20260908.md"
else
  echo "PR #$existing already exists"
fi
