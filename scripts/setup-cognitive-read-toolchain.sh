#!/usr/bin/env bash
set -euo pipefail

# The qualifier sets RUSTUP_TOOLCHAIN explicitly. That override selects the
# compiler, but does not install the components listed in rust-toolchain.toml.
# Resolve the same candidate pin here instead of the runner's default toolchain.
toolchain="$(PYTHONPATH=scripts python3 -c 'from pathlib import Path; from cognitive_read_evidence import qualification_env; print(qualification_env(Path.cwd())["RUSTUP_TOOLCHAIN"])')"
rustup toolchain install "$toolchain" --profile minimal \
  --component clippy --component rustfmt --component rust-src
rustup run "$toolchain" rustfmt --version
rustup run "$toolchain" clippy-driver --version
