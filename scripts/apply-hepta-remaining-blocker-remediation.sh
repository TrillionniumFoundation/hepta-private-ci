#!/usr/bin/env bash
set -euo pipefail

EXPECTED_REPO="TrillionniumFoundation/hepta-private-ci"
CONTROLLER_BRANCH="ops/hepta-global-gap-closure-controller-20260910-r1"
WORKFLOW_MODE=false
if [[ "${1:-}" == "--workflow-mode" ]]; then
  WORKFLOW_MODE=true
fi

root="$(git rev-parse --show-toplevel)"
cd "${root}"
remote_url="$(git remote get-url origin)"
case "${remote_url}" in
  *"${EXPECTED_REPO}"*) ;;
  *) echo "unexpected origin: ${remote_url}" >&2; exit 2 ;;
esac

if [[ "${WORKFLOW_MODE}" != true ]]; then
  git fetch --prune origin
  git checkout "${CONTROLLER_BRANCH}"
  git pull --ff-only origin "${CONTROLLER_BRANCH}"
fi

python3 - <<'PY'
from pathlib import Path

r7 = Path("scripts/hepta-global-finalizer-r7.py")
text = r7.read_text(encoding="utf-8")
old = '''    conflicts: list[str] = []
    auto_resolved = False
    if not result.passed:
        conflicts = [
            line.strip()
            for line in git("diff", "--name-only", "--diff-filter=U", check=False).output.splitlines()
            if line.strip()
        ]
        if not generated_conflicts_only(conflicts):
            git("merge", "--abort", check=False)
            return {
                "lane": lane,
                "branch": branch,
                "merged": False,
                "before": before,
                "conflicts": conflicts,
                "outputTail": result.output.splitlines()[-100:],
            }
        for path in conflicts:
            git("checkout", "--ours", "--", path)
            git("add", "--", path)
        git(
            "commit",
            "--signoff",
            "-m",
            f"merge(lane-{lane.lower()}): resolve generated convergence metadata",
        )
        auto_resolved = True'''
new = '''    conflicts: list[str] = []
    auto_resolved = False
    lane_owner_conflict = False
    if not result.passed:
        conflicts = [
            line.strip()
            for line in git("diff", "--name-only", "--diff-filter=U", check=False).output.splitlines()
            if line.strip()
        ]
        lane_owner_conflict = lane == "E" and conflicts == ["docs/lane-e/README.md"]
        if not generated_conflicts_only(conflicts) and not lane_owner_conflict:
            git("merge", "--abort", check=False)
            return {
                "lane": lane,
                "branch": branch,
                "merged": False,
                "before": before,
                "conflicts": conflicts,
                "outputTail": result.output.splitlines()[-100:],
            }
        checkout_side = "--theirs" if lane_owner_conflict else "--ours"
        for path in conflicts:
            git("checkout", checkout_side, "--", path)
            git("add", "--", path)
        resolution_class = (
            "lane-E owner documentation"
            if lane_owner_conflict
            else "generated convergence metadata"
        )
        git(
            "commit",
            "--signoff",
            "-m",
            f"merge(lane-{lane.lower()}): resolve {resolution_class}",
        )
        auto_resolved = True'''
if old not in text:
    if "autoResolvedLaneOwnerOnly" not in text:
        raise SystemExit("r7 merge conflict anchor not found")
else:
    text = text.replace(old, new, 1)

old_receipt = '''        "autoResolvedGeneratedOnly": auto_resolved,
        "conflicts": conflicts,'''
new_receipt = '''        "autoResolvedGeneratedOnly": auto_resolved and not lane_owner_conflict,
        "autoResolvedLaneOwnerOnly": lane_owner_conflict,
        "conflicts": conflicts,'''
if old_receipt in text:
    text = text.replace(old_receipt, new_receipt, 1)
elif "autoResolvedLaneOwnerOnly" not in text:
    raise SystemExit("r7 receipt anchor not found")
r7.write_text(text, encoding="utf-8")

r12 = Path("scripts/hepta-candidate-publisher-r12.py")
text = r12.read_text(encoding="utf-8")
constants_anchor = 'OUT = ROOT / "qualification" / "global-gap-closure-final-candidate"\n'
constants = '''OUT = ROOT / "qualification" / "global-gap-closure-final-candidate"
PUBLICATION_BASE_REF = os.environ.get(
    "HEPTA_PUBLICATION_BASE",
    "origin/ops/hepta-final-convergence-review-anchor-20260909",
)
TEMPORARY_MUTATION_PATHS = (
    ".github/workflows/hepta-candidate-publisher-r12.yml",
    ".github/workflows/hepta-fixed-point-sealer-r10.yml",
    ".github/workflows/hepta-fixed-point-sealer-r11.yml",
    ".github/workflows/hepta-global-finalizer-r6.yml",
    ".github/workflows/hepta-global-finalizer-r7.yml",
    ".github/workflows/hepta-global-finalizer-r8.yml",
    ".github/workflows/hepta-global-finalizer-r9.yml",
    ".github/workflows/hepta-global-gap-closure-controller-r2.yml",
    ".github/workflows/hepta-global-gap-closure-controller-r3.yml",
    ".github/workflows/hepta-global-gap-closure-controller-r4.yml",
    ".github/workflows/hepta-global-gap-closure-controller.yml",
    ".github/workflows/tmp-hepta-controller-remediation.yml",
    "scripts/apply-hepta-remaining-blocker-remediation.sh",
    "scripts/hepta-candidate-publisher-r12.py",
    "scripts/hepta-fixed-point-sealer-r10.py",
    "scripts/hepta-fixed-point-sealer-r11.py",
    "scripts/hepta-global-finalizer-r6.py",
    "scripts/hepta-global-finalizer-r7.py",
    "scripts/hepta-global-finalizer-r8-fixed.py",
    "scripts/hepta-global-finalizer-r8.py",
    "scripts/hepta-global-gap-closure-r4.py",
    "scripts/hepta-global-gap-closure.py",
)
'''
if "PUBLICATION_BASE_REF" not in text:
    if constants_anchor not in text:
        raise SystemExit("r12 constants anchor not found")
    text = text.replace(constants_anchor, constants, 1)

helper_anchor = "def main() -> int:\n"
helper = '''def remove_temporary_mutation_carriers() -> None:
    git("rm", "-f", "--ignore-unmatch", "--", *TEMPORARY_MUTATION_PATHS)
    survivors = [
        path for path in TEMPORARY_MUTATION_PATHS if (ROOT / path).exists()
    ]
    if survivors:
        raise RuntimeError(
            f"temporary mutation carriers survived cleanup: {survivors}"
        )


def assert_no_candidate_mutation_workflows(publication_base: str) -> None:
    changed = git(
        "diff",
        "--name-only",
        publication_base,
        "--",
        ".github/workflows",
        check=False,
    ).splitlines()
    violations: list[str] = []
    for path in sorted(set(changed)):
        candidate = ROOT / path
        if not candidate.is_file() or candidate.suffix not in {".yml", ".yaml"}:
            continue
        source = candidate.read_text(encoding="utf-8", errors="replace").lower()
        if (
            "contents: write" in source
            or "pull-requests: write" in source
            or "persist-credentials: true" in source
        ):
            violations.append(path)
    if violations:
        raise RuntimeError(
            f"candidate-controlled mutation workflows remain: {violations}"
        )


def publish_as_direct_child(staged_commit: str) -> tuple[str, str]:
    publication_base = git(
        "rev-parse",
        "--verify",
        f"{PUBLICATION_BASE_REF}^{{commit}}",
    )
    candidate_tree = git("rev-parse", f"{staged_commit}^{{tree}}")
    candidate_commit = git(
        "commit-tree",
        candidate_tree,
        "-p",
        publication_base,
        "-m",
        "fix(hepta): publish exact single-parent all-lanes blocker closure",
        "-m",
        "Signed-off-by: Hepta Canonical Candidate Publisher <noreply@openai.com>",
    )
    git("reset", "--hard", candidate_commit)
    parents = git("show", "-s", "--format=%P", candidate_commit).split()
    if parents != [publication_base]:
        raise RuntimeError(
            f"candidate parent mismatch: expected {[publication_base]}, got {parents}"
        )
    return candidate_commit, publication_base


def main() -> int:
'''
if "def publish_as_direct_child" not in text:
    if helper_anchor not in text:
        raise SystemExit("r12 main anchor not found")
    text = text.replace(helper_anchor, helper, 1)

commit_anchor = '''    candidate_commit = commit_if_dirty(
        "docs: publish canonical all-Hepta internal candidate r12"
    )
    git("push", "--force-with-lease", "origin", f"HEAD:refs/heads/{TARGET}")'''
commit_replacement = '''    publication_base = git(
        "rev-parse",
        "--verify",
        f"{PUBLICATION_BASE_REF}^{{commit}}",
    )
    remove_temporary_mutation_carriers()
    assert_no_candidate_mutation_workflows(publication_base)
    staged_commit = commit_if_dirty(
        "docs: publish canonical all-Hepta internal candidate r12"
    )
    candidate_commit, publication_base = publish_as_direct_child(staged_commit)
    git("push", "--force-with-lease", "origin", f"HEAD:refs/heads/{TARGET}")'''
if commit_anchor in text:
    text = text.replace(commit_anchor, commit_replacement, 1)
elif "publish_as_direct_child(staged_commit)" not in text:
    raise SystemExit("r12 publication anchor not found")

output_anchor = '''                "candidateCommit": candidate_commit,
                "fixedPointStable": True,'''
output_replacement = '''                "candidateCommit": candidate_commit,
                "publicationBase": publication_base,
                "directParentVerified": True,
                "temporaryMutationCarriersPresent": False,
                "fixedPointStable": True,'''
if output_anchor in text:
    text = text.replace(output_anchor, output_replacement, 1)
elif '"directParentVerified": True' not in text:
    raise SystemExit("r12 output anchor not found")
r12.write_text(text, encoding="utf-8")
PY

python3 - <<'ARGCOMMENTPY'
from pathlib import Path

repairs = (
    (
        Path("codex-rs/http-client/src/tls_backend_fallback.rs"),
        "walk_error_chain(error, 0, &mut |source| {",
        "walk_error_chain(error, /* depth */ 0, &mut |source| {",
        2,
    ),
    (
        Path("codex-rs/hepta-runtime/src/organs.rs"),
        "Generation::new(1).unwrap()",
        "Generation::new(/* value */ 1).unwrap()",
        1,
    ),
)

for path, old, new, expected_count in repairs:
    source = path.read_text(encoding="utf-8")
    observed = source.count(old)
    if observed == 0 and source.count(new) == expected_count:
        continue
    if observed != expected_count:
        raise SystemExit(
            f"argument-comment repair drift for {path}: "
            f"expected {expected_count} old occurrences, observed {observed}"
        )
    path.write_text(source.replace(old, new), encoding="utf-8")
ARGCOMMENTPY

PYTHON_FILES=(
  scripts/hepta-candidate-publisher-r12.py
  scripts/hepta-fixed-point-sealer-r10.py
  scripts/hepta-fixed-point-sealer-r11.py
  scripts/hepta-global-finalizer-r6.py
  scripts/hepta-global-finalizer-r7.py
  scripts/hepta-global-finalizer-r8-fixed.py
  scripts/hepta-global-finalizer-r8.py
  scripts/hepta-global-gap-closure-r4.py
  scripts/hepta-global-gap-closure.py
)

uv run --frozen --project scripts ruff format "${PYTHON_FILES[@]}"
uv run --frozen --project scripts ruff format --check "${PYTHON_FILES[@]}"
python3 -m py_compile "${PYTHON_FILES[@]}"
git diff --check

git config user.name "Hepta Blocker Remediator"
git config user.email "noreply@openai.com"
git add \
  "${PYTHON_FILES[@]}" \
  scripts/apply-hepta-remaining-blocker-remediation.sh \
  codex-rs/http-client/src/tls_backend_fallback.rs \
  codex-rs/hepta-runtime/src/organs.rs
if [[ -f .github/workflows/tmp-hepta-controller-remediation.yml ]]; then
  git add .github/workflows/tmp-hepta-controller-remediation.yml
fi

if ! git diff --cached --quiet; then
  git commit --signoff -m "fix(hepta): close convergence topology and formatting blockers"
  git push origin "HEAD:refs/heads/${CONTROLLER_BRANCH}"
fi

if [[ "${WORKFLOW_MODE}" == true ]]; then
  exit 0
fi

command -v gh >/dev/null
gh auth status >/dev/null
for workflow in \
  hepta-global-finalizer-r7.yml \
  hepta-global-finalizer-r8.yml \
  hepta-global-finalizer-r9.yml \
  hepta-fixed-point-sealer-r10.yml \
  hepta-fixed-point-sealer-r11.yml \
  hepta-candidate-publisher-r12.yml
do
  gh workflow run "${workflow}" \
    --repo "${EXPECTED_REPO}" \
    --ref "${CONTROLLER_BRANCH}"
done

printf '%s\n' \
  "Remediation committed and r7-r12 fixed-point pipeline dispatched." \
  "Do not merge or release until the final candidate's exact-head checks and independent review are terminal."
