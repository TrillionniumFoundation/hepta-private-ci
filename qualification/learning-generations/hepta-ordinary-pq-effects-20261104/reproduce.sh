#!/usr/bin/env bash
# Run from a checkout containing the qualified source. Keep every result.
set -uo pipefail

qualification_root=$(git rev-parse --show-toplevel) || exit 2
qualification_output=${1:-$(mktemp -d)}
mkdir -p "$qualification_output" || exit 2
qualification_output=$(cd "$qualification_output" && pwd) || exit 2
cd "$qualification_root" || exit 2

case $(uname -s) in
    Linux) ;;
    *) printf '%s\n' 'This ordinary SmolLM host selection requires Linux.' >&2; exit 2 ;;
esac

qualification_failed=0
run_check() {
    local name=$1
    shift
    "$@" >"$qualification_output/$name.log" 2>&1
    local status=$?
    printf '%s\t%s\n' "$name" "$status" >>"$qualification_output/status.tsv"
    if [ "$status" -ne 0 ]; then
        qualification_failed=1
    fi
}

git rev-parse HEAD >"$qualification_output/source.txt"
git diff HEAD --binary >>"$qualification_output/source.txt"
rustc --version >"$qualification_output/rustc.txt"
run_check leaf just test -p codex-hepta-contracts -p codex-hepta-learning-artifacts --locked --retries 0
run_check host-check cargo check --manifest-path codex-rs/Cargo.toml --locked -p codex-hepta-infer-worker-host --tests
run_check host-regression just test -p codex-hepta-infer-worker-host --lib --locked --retries 0 -E 'test(ordinary_open_) | test(ordinary_pq_) | test(pq_study_role_wire_) | test(ordinary_study_pq_)'
run_check lint just clippy -p codex-hepta-contracts -p codex-hepta-learning-artifacts -p codex-hepta-infer-worker-host --locked
run_check format just fmt --check --base 4c93a641945044f904a656cbf1d23e358a074d52
printf 'Results: %s\n' "$qualification_output"
exit "$qualification_failed"
