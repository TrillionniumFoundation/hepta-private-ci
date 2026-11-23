set -euo pipefail
test "$(git rev-parse "$CANDIDATE^")" = "$BASE"
git merge-base --is-ancestor "$CANDIDATE" HEAD
test "$(git diff --name-only "$CANDIDATE" HEAD | sort)" = "$(printf '%s\n' .github/scripts/agentd-data-pairs-{cases.json,driver.py,prepare.sh} .github/workflows/agentd-readonly-data-pairs.yml | sort)"
where="$RUNNER_TEMP/data-pairs-lint-evidence"
mkdir -p "$where"
cp .github/scripts/agentd-data-pairs-cases.json "$RUNNER_TEMP/data-pairs-cases.json"
cp .github/scripts/agentd-data-pairs-driver.py "$RUNNER_TEMP/data-pairs-driver.py"
git diff --name-only "$BASE" "$CANDIDATE" -- > "$where/product-diff.txt"
expected=(cell_q24_model_current_admission.rs cell_q24_model_current_owner.rs neuron_cell_evaluation_model_material_proofs.rs neuron_cell_evaluation_on_policy_policy.rs root_independent_b_client.rs)
test "$(cat "$where/product-diff.txt")" = "$(printf 'codex-rs/hepta-agentd/src/%s\n' "${expected[@]}" | sort)"
suites=(test_q24_model_proposal_source_closure.py test_original_model_root_source_closure.py test_training_no_update_source_closure.py test_lint_preserved_owner_guards_source_closure.py test_original_on_policy_evaluation_source_closure.py test_original_b_acceptance_source_closure.py test_original_b_custody_source_closure.py test_original_b_publication_data_source_closure.py test_original_b_routes_source_closure.py)
for arm in base candidate; do
  if [ "$arm" = base ]; then ref="$BASE"; else ref="$CANDIDATE"; fi
  git worktree add --quiet --detach "$RUNNER_TEMP/data-pairs-$arm" "$ref"
  cd "$RUNNER_TEMP/data-pairs-$arm"
  git rev-parse HEAD > "$where/identity-$arm.txt"
  git rev-parse 'HEAD^{tree}' > "$where/tree-$arm.txt"
  git ls-tree -r HEAD -- CALLERS.toml scripts/verify_hepta_callers.py scripts/hepta_callers_manifest_parts "${suites[@]/#/qa\/b4-no-bypass\/}" > "$where/guards-$arm.txt"
  for suite in "${suites[@]}"; do
    test -f "qa/b4-no-bypass/$suite"
    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s qa/b4-no-bypass -p "$suite" -v > "$where/$arm-$suite.log" 2>&1
    grep -Eq '^Ran [1-9][0-9]* tests?' "$where/$arm-$suite.log"
  done
  cd "$GITHUB_WORKSPACE"
done
cmp "$where/guards-base.txt" "$where/guards-candidate.txt"
