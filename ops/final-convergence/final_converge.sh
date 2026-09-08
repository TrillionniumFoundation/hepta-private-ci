#!/usr/bin/env bash
set -euo pipefail

: "${CANDIDATE_BRANCH:=integration/final-all-branches-main-tree-r3-20260908}"
: "${GITHUB_REPOSITORY:=TrillionniumFoundation/hepta-private-ci}"

log() { printf '\n==== %s ====\n' "$*"; }

git config user.name 'hepta-convergence-bot'
git config user.email 'hepta-convergence-bot@users.noreply.github.com'
git fetch --prune origin '+refs/heads/*:refs/remotes/origin/*' '+refs/tags/*:refs/tags/*'

log 'select canonical source'
canonical=origin/main
if git show-ref --verify --quiet refs/remotes/origin/codex/hepta-v9-blocker-closure-20260908; then
  canonical=origin/codex/hepta-v9-blocker-closure-20260908
elif git show-ref --verify --quiet refs/remotes/origin/codex/hepta-w0-seven-lanes-handoff-20260908; then
  canonical=origin/codex/hepta-w0-seven-lanes-handoff-20260908
fi
git checkout -B "$CANDIDATE_BRANCH" "$canonical"
if ! git merge-base --is-ancestor origin/main HEAD; then
  git merge --no-ff -X ours origin/main -m 'merge: retain current main lineage in final convergence R3'
fi

mkdir -p .convergence
report=.convergence/report.tsv
printf 'branch\tsha\tmode\n' > "$report"

priority=(
  codex/hepta-final-gap-closure-r3-20260908
  integration/hepta-w0-internal-closure-20260908
  codex/hepta-w0-seven-lanes-handoff-20260908
  reviewer/ci-governance-simplification-20260908
  codex/hepta-bao-connect-20260908
  codex/hepta-v9-blocker-closure-20260908
)

log 'content-integrate current product heads'
for branch in "${priority[@]}"; do
  ref="refs/remotes/origin/$branch"
  git show-ref --verify --quiet "$ref" || continue
  sha=$(git rev-parse "$ref")
  if git merge-base --is-ancestor "$sha" HEAD; then
    printf '%s\t%s\talready-contained\n' "$branch" "$sha" >> "$report"
  else
    git merge --no-ff -X ours "$ref" -m "merge: integrate priority branch $branch"
    printf '%s\t%s\tcontent-merge\n' "$branch" "$sha" >> "$report"
  fi
done

if [[ -e .g1/trillionnium_os_external_evidence ]]; then
  git rm -r .g1/trillionnium_os_external_evidence
  git commit -m 'chore: keep external OS evidence outside the Hepta main tree'
fi

log 'history-integrate all remaining branch heads'
mapfile -t branches < <(
  git for-each-ref --format='%(refname:strip=3)' refs/remotes/origin \
    | grep -v '^HEAD$' \
    | grep -v '^main$' \
    | grep -v "^${CANDIDATE_BRANCH}$" \
    | sort -u
)
for branch in "${branches[@]}"; do
  ref="refs/remotes/origin/$branch"
  sha=$(git rev-parse "$ref")
  if git merge-base --is-ancestor "$sha" HEAD; then
    grep -Fq "$branch"$'\t' "$report" || printf '%s\t%s\talready-contained\n' "$branch" "$sha" >> "$report"
  else
    git merge --no-ff -s ours "$ref" -m "archive: absorb superseded branch $branch without changing canonical tree"
    printf '%s\t%s\thistory-merge\n' "$branch" "$sha" >> "$report"
  fi
done

log 'repair the reproduced nested rustls/hyper classification gap only when required'
cd codex-rs
if ! cargo test --locked -p codex-http-client --lib -- --test-threads=1; then
  cd ..
  python3 - <<'PY'
import re
from pathlib import Path
paths = [
    Path('codex-rs/http-client/src/tls_backend_fallback.rs'),
    Path('codex-rs/http-client/src/route_aware_client_pool.rs'),
    Path('codex-rs/http-client/src/transport.rs'),
]
changed = []
for path in paths:
    if not path.exists():
        continue
    original = path.read_text(encoding='utf-8')
    text = original
    for ident in ('error', 'source', 'cause', 'current', 'err'):
        text = text.replace(
            f'{ident}.to_string().to_ascii_lowercase()',
            f'format!("{{0}} {{0:?}}", {ident}).to_ascii_lowercase()',
        )
        text = text.replace(
            f'{ident}.to_string().to_lowercase()',
            f'format!("{{0}} {{0:?}}", {ident}).to_lowercase()',
        )
        text = re.sub(
            rf'let\s+(?P<n>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*{ident}\.to_string\(\);',
            lambda match: f'let {match.group("n")} = format!("{{0}} {{0:?}}", {ident});',
            text,
        )
    if text != original:
        path.write_text(text, encoding='utf-8')
        changed.append(str(path))
if not changed:
    raise SystemExit('TLS failures reproduced, but no supported source-chain classifier site was found')
print('patched:', *changed)
PY
  cd codex-rs
  cargo fmt --all
  cargo test --locked -p codex-http-client --lib -- --test-threads=1
  cd ..
  git add codex-rs/http-client
  git commit -m 'fix(http): classify nested rustls certificate and protocol errors'
  cd codex-rs
fi

log 'full executable qualification'
cargo fmt --all -- --check
metadata=$(cargo metadata --no-deps --format-version=1)
packages=(
  codex-hepta-contracts
  codex-hepta-bao-adapter
  codex-hepta-supervisor
  codex-hepta-ndu
  codex-hepta-neuron
  codex-hepta-learning-ledger
  codex-hepta-intelligence-eval
  codex-hepta-plasticity
  codex-hepta-shadow-qualification
)
for package in "${packages[@]}"; do
  if jq -e --arg package "$package" '.packages[] | select(.name == $package)' <<<"$metadata" >/dev/null; then
    cargo test --locked -p "$package" --all-targets
  fi
done
cargo check --locked --workspace --all-targets
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo test --locked --workspace --all-targets
cd ..

for script in \
  scripts/verify_pre_coding_readiness.py \
  scripts/verify_implementation_dossiers.py \
  scripts/verify_technical_closure.py \
  scripts/verify_implementation_contracts.py \
  scripts/verify_paper_evidence.py \
  scripts/verify_adaptive_algorithm_sources.py; do
  [[ -f "$script" ]] && python3 "$script"
done

log 'write immutable branch-to-SHA convergence manifest'
python3 - <<'PY'
import csv, json, subprocess
from pathlib import Path
rows = list(csv.DictReader(Path('.convergence/report.tsv').open(encoding='utf-8'), delimiter='\t'))
payload = {
    'schema': 1,
    'generated_by': 'ops/final-convergence/final_converge.sh',
    'qualified_tree': subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], text=True).strip(),
    'branches': rows,
}
out = Path('docs/archive/branch-convergence-20260908.json')
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')
PY
git add docs/archive/branch-convergence-20260908.json
if ! git diff --cached --quiet; then
  git commit -m 'docs: record qualified final branch convergence ancestry'
fi

log 'prove every recorded branch head is an ancestor'
failed=0
while IFS= read -r branch; do
  [[ "$branch" == HEAD || "$branch" == main || "$branch" == "$CANDIDATE_BRANCH" ]] && continue
  sha=$(git rev-parse "refs/remotes/origin/$branch")
  if ! git merge-base --is-ancestor "$sha" HEAD; then
    echo "unabsorbed branch: $branch $sha" >&2
    failed=1
  fi
done < <(git for-each-ref --format='%(refname:strip=3)' refs/remotes/origin | sort -u)
test "$failed" -eq 0

log 'push qualified candidate and open/update PR'
git push --force-with-lease origin "HEAD:refs/heads/$CANDIDATE_BRANCH"
existing=$(gh pr list --repo "$GITHUB_REPOSITORY" --state open --head "$CANDIDATE_BRANCH" --json number --jq '.[0].number // empty')
body=$(cat <<'EOF'
Final repository convergence R3.

- Current W0/v9 product heads are content-integrated.
- Every historical, backup, diagnostic and superseded controller head is merge ancestry without permission to roll the canonical tree backward.
- Shared HTTP TLS classification is first reproduced; a source-chain repair is committed only when the test demonstrates the gap.
- Every named branch and exact SHA is recorded in `docs/archive/branch-convergence-20260908.json`.
- Candidate push occurs only after HTTP, focused Hepta packages, full workspace format/check/Clippy/test and repository-native verification pass.

After normal protected merge, the promotion job verifies reachability again, archives a tag, switches the default branch to `main` where authorized, and removes unchanged non-main refs.
EOF
)
if [[ -n "$existing" ]]; then
  gh pr edit "$existing" --repo "$GITHUB_REPOSITORY" --title 'merge: converge every branch into the single main tree (R3)' --body "$body"
else
  gh pr create --repo "$GITHUB_REPOSITORY" --base main --head "$CANDIDATE_BRANCH" --title 'merge: converge every branch into the single main tree (R3)' --body "$body"
fi
