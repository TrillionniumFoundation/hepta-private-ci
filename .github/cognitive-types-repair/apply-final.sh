#!/usr/bin/env bash
set -euo pipefail

test "$(git rev-parse HEAD)" = "$GITHUB_SHA"
branch="${GITHUB_REF_NAME:?missing GITHUB_REF_NAME}"
remote_head="$(git ls-remote origin "refs/heads/${branch}" | cut -f1)"
test "$remote_head" = "$GITHUB_SHA"

patch_file="$RUNNER_TEMP/cognitive-types-final.patch"
cat .github/cognitive-types-repair/part-*.patch > "$patch_file"
actual_digest="$(python3 - "$patch_file" <<'PY'
import hashlib
import pathlib
import sys
print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())
PY
)"
test "$actual_digest" = '6b75ab829e85a28e316f948abf2ca613a24b954fa519195bea5b3a846439559a'
git apply --check "$patch_file"
git apply --index "$patch_file"

packages=(
  codex-hepta-cognitive-types
  codex-hepta-cognitive-store
  codex-hepta-context-compiler
  codex-hepta-intelligence
  codex-hepta-memory-retrieval
  codex-hepta-memory
  codex-hepta-authbus
  codex-hepta-agentd
)
for package in "${packages[@]}"; do
  cargo fmt --manifest-path codex-rs/Cargo.toml --package "$package"
  cargo fmt --manifest-path codex-rs/Cargo.toml --package "$package" -- --check
done

python3 scripts/hepta-hnmf.py self-test
python3 scripts/hepta-hnmf.py verify
python3 -m unittest discover -s qualification/cognitive-types-v1 -p 'test_*.py'
python3 qualification/cognitive-types-v1/verify_vectors.py
python3 qualification/cognitive-types-v1/verify_bound_vector.py
node qualification/cognitive-types-v1/verify_bound_vector.mjs
python3 qualification/cognitive-types-v2/verify_vectors.py
python3 qualification/cognitive-types-v1/render_traceability.py --check

cargo check --manifest-path codex-rs/Cargo.toml --locked --all-targets \
  $(printf -- '-p %s ' "${packages[@]}")
cargo test --manifest-path codex-rs/Cargo.toml --locked \
  $(printf -- '-p %s ' "${packages[@]}")
cargo check --manifest-path codex-rs/hepta-cognitive-types/fuzz/Cargo.toml --all-targets
cargo clippy --manifest-path codex-rs/Cargo.toml --locked --all-targets \
  $(printf -- '-p %s ' "${packages[@]}") -- -D warnings

remote_head="$(git ls-remote origin "refs/heads/${branch}" | cut -f1)"
test "$remote_head" = "$GITHUB_SHA"
rm -rf .github/cognitive-types-repair
rm -f \
  .github/workflows/cognitive-types-apply-final.yml \
  .github/workflows/cognitive-types-apply-pocket4.yml \
  .github/workflows/cognitive-types-apply-macbook.yml
git add -A
git diff --cached --check
test -z "$(find . -type d -name target -not -path './target' -print -quit)"
git config user.name 'Tomasrgbsf'
git config user.email 'tomasbraynt@gmail.com'
git commit -m 'fix(cognitive.types): close remaining qualification blockers'
git push origin "HEAD:refs/heads/${branch}"
