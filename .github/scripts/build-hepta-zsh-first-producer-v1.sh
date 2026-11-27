#!/usr/bin/env bash
# A new build-only caller derived from build-zsh-release-artifact.sh.
# No release/tag or old multi-platform workflow is invoked.
set -euo pipefail
[[ "$#" -eq 1 ]] || { echo "expected prepare or build phase" >&2; exit 2; }
phase="$1"
root="${HEPTA_ZSH_PRODUCER_ROOT:?missing owned root}"
source_root="${root}/work/zsh"
package_root="${root}/work/codex-zsh"
evidence="${root}/evidence"
archive="${root}/artifacts/codex-zsh-aarch64-apple-darwin.tar.gz"
git_bin="${HEPTA_GIT:?missing original git}"
bash_bin="${HEPTA_BASH:?missing original bash}"
[[ "$root" = /* && -d "$root" && ! -L "$root" ]]
[[ "${ZSH_COMMIT:?missing immutable upstream}" = "77045ef899e53b9598bebc5a41db93a548a40ca6" ]]
[[ "$phase" = prepare || "$phase" = build ]]
events="${evidence}/${phase}-events.tsv"
( set -o noclobber; : > "$events" )
current_phase="initial"
failed() {
  original_exit=$?
  printf 'EXIT\t%s\t%s\n' "$current_phase" "$original_exit" >> "$events"
  exit "$original_exit"
}
trap failed EXIT
mark() { current_phase="$1"; printf 'START\t%s\n' "$current_phase" >> "$events"; }
done_phase() { printf 'DONE\t%s\n' "$current_phase" >> "$events"; }
# Preserve the fresh source/build tree. The old release script's rm -rf trap
# is deliberately absent, so diagnostics are not erased on failure.
if [[ "$phase" = prepare ]]; then
  [[ ! -e "$source_root" && ! -e "${evidence}/prepare-complete" ]]
  mark autoconf-prerequisite
  if ! command -v autoconf >/dev/null 2>&1; then
    [[ "${HEPTA_ALLOW_AUTOCONF_INSTALL:?}" = true ]]
    "${HEPTA_BREW:?autoconf is absent and brew is unavailable}" install autoconf
    printf 'installed\n' > "${evidence}/autoconf-origin.txt"
  else
    printf 'preinstalled\n' > "${evidence}/autoconf-origin.txt"
  fi
  command -v autoconf > "${evidence}/autoconf-command-path.txt"
  command -v autoheader > "${evidence}/autoheader-command-path.txt"
  command -v autom4te > "${evidence}/autom4te-command-path.txt"
  command -v m4 > "${evidence}/m4-command-path.txt"
  "${HEPTA_XCRUN:?}" --find clang > "${evidence}/clang-command-path.txt"
  "${HEPTA_XCRUN}" --show-sdk-path > "${evidence}/sdk-path.txt"
  "${HEPTA_XCODE_SELECT:?}" -p > "${evidence}/developer-directory.txt"
  done_phase
  mark upstream-clone-once
  "$git_bin" -c credential.helper= -c core.hooksPath=/dev/null clone \
    --no-checkout https://git.code.sf.net/p/zsh/code "$source_root"
  done_phase
  cd "$source_root"
  mark exact-upstream-checkout
  "$git_bin" -c core.hooksPath=/dev/null checkout --detach "$ZSH_COMMIT"
  [[ "$("$git_bin" rev-parse HEAD)" = "$ZSH_COMMIT" ]]
  "$git_bin" cat-file commit HEAD > "${evidence}/upstream-commit.raw"
  "$git_bin" ls-tree -r -z --full-tree HEAD > "${evidence}/upstream-tree.raw"
  "$git_bin" diff --exit-code
  done_phase
  mark reviewed-patch-once
  printf '%s' "${HEPTA_ZSH_PATCH_TEXT:?missing same-buffer patch}" | \
    "$git_bin" apply --index --whitespace=error -
  [[ "$("$git_bin" diff --cached --name-only)" = "Src/exec.c" ]]
  [[ "$("$git_bin" hash-object Src/exec.c)" = "f9cfa86d59c60592f214af0d12973a6c307baf8f" ]]
  "$git_bin" diff --exit-code
  "$git_bin" diff --cached --binary > "${evidence}/applied-upstream.patch"
  cp Src/exec.c "${evidence}/patched-exec.c"
  [[ ! -e Src/zsh ]]
  done_phase
  printf 'prepare-complete\n' > "${evidence}/prepare-complete"
  exit 0
fi

[[ -f "${evidence}/prepare-complete" && ! -e "${evidence}/build-complete" ]]
[[ -d "$source_root" && ! -L "$source_root" && ! -e "${source_root}/Src/zsh" ]]
cd "$source_root"
[[ "$("$git_bin" rev-parse HEAD)" = "$ZSH_COMMIT" ]]
[[ "$("$git_bin" hash-object Src/exec.c)" = "f9cfa86d59c60592f214af0d12973a6c307baf8f" ]]
"$git_bin" diff --exit-code
[[ "${HEPTA_MAKE_JOBS:?}" =~ ^[1-4]$ ]]
mark tool-identities
"$bash_bin" --version > "${evidence}/bash-version.txt"
"$git_bin" --version > "${evidence}/git-version.txt"
"${AUTOCONF:?}" --version > "${evidence}/autoconf-version.txt"
"${AUTOHEADER:?}" --version > "${evidence}/autoheader-version.txt"
"${HEPTA_AUTOM4TE:?}" --version > "${evidence}/autom4te-version.txt"
"${M4:?}" --version > "${evidence}/m4-version.txt"
"${HEPTA_MAKE:?}" --version > "${evidence}/make-version.txt"
"${CC:?}" --version > "${evidence}/clang-version.txt"
"${HEPTA_TAR:?}" --version > "${evidence}/tar-version.txt"
done_phase
mark preconfig-once
if ./Util/preconfig > "${evidence}/preconfig.stdout" 2> "${evidence}/preconfig.stderr"; then
  preconfig_exit=0
else
  preconfig_exit=$?
fi
printf '%s\n' "$preconfig_exit" > "${evidence}/preconfig.exit.txt"
cat "${evidence}/preconfig.stdout"
cat "${evidence}/preconfig.stderr" >&2
[[ "$preconfig_exit" -eq 0 ]]
# The fixed upstream Util/preconfig can print a nested failure and then exit 0.
# Keep that original failure; do not let its final exit mask the failed generator.
if grep -F './Util/preconfig:' "${evidence}/preconfig.stdout" | grep -F 'failed (status '; then
  echo "fixed upstream preconfig reported a nested generator failure" >&2
  exit 1
fi
done_phase
mark configure-once
./configure
done_phase
mark make-once
"${HEPTA_MAKE}" -j"${HEPTA_MAKE_JOBS}"
"${HEPTA_OTOOL:?}" -L "${source_root}/Src/zsh" > "${evidence}/binary-dylibs.txt"
"${HEPTA_FILE:?}" "${source_root}/Src/zsh" > "${evidence}/binary-file.txt"
done_phase
# The owner retains fixed generated diagnostics after the original child closes,
# including a failed preconfig/configure/make path; this phase does not erase them.
wrapper_path="${root}/work/exec-wrapper"
cat > "$wrapper_path" <<'WRAPPER'
#!/bin/bash
set -euo pipefail
: "${CODEX_WRAPPER_LOG:?missing CODEX_WRAPPER_LOG}"
printf '%s\n' "$@" > "$CODEX_WRAPPER_LOG"
file="$1"
shift
if [[ "$#" -eq 0 ]]; then
  exec "$file"
fi
arg0="$1"
shift
exec -a "$arg0" "$file" "$@"
WRAPPER
chmod +x "$wrapper_path"
cp "$wrapper_path" "${evidence}/exec-wrapper"
mark echo-wrapper-smoke-once
CODEX_WRAPPER_LOG="${evidence}/echo-wrapper.log" \
EXEC_WRAPPER="$wrapper_path" \
"${source_root}/Src/zsh" -fc '/bin/echo smoke-zsh' > "${evidence}/echo.stdout"
grep -Fx "smoke-zsh" "${evidence}/echo.stdout"
grep -Fx "/bin/echo" "${evidence}/echo-wrapper.log"
done_phase
mark missing-path-wrapper-smoke-once
touch_path="${HEPTA_TOUCH:?missing verified absolute touch}"
[[ "$touch_path" = /* ]]
empty_cwd="${root}/work/empty-cwd"
touch_marker="${root}/work/touch-marker"
mkdir "$empty_cwd"
printf '%s\n' "$touch_path" > "${evidence}/touch-command-path.txt"
printf '%s\n' "$touch_marker" > "${evidence}/touch-marker-path.txt"
(
  cd "$empty_cwd"
  CODEX_WRAPPER_LOG="${evidence}/touch-wrapper.log" \
  CODEX_TOUCH_MARKER="$touch_marker" \
  EXEC_WRAPPER="$wrapper_path" \
  PATH="${root}/work/missing:${empty_cwd}::${touch_path%/*}:${PATH}" \
  "${source_root}/Src/zsh" -fc 'touch "$CODEX_TOUCH_MARKER"' > "${evidence}/touch.stdout"
)
[[ -f "$touch_marker" && ! -L "$touch_marker" ]]
IFS= read -r intercepted_path < "${evidence}/touch-wrapper.log"
[[ "$intercepted_path" = "$touch_path" ]]
done_phase
mark archive-once
mkdir -p "$package_root/bin"
cp "${source_root}/Src/zsh" "$package_root/bin/zsh"
chmod 0755 "$package_root/bin/zsh"
(cd "${root}/work" && "${HEPTA_TAR:?}" -czf "$archive" codex-zsh)
"$git_bin" diff --exit-code
[[ "$("$git_bin" diff --cached --name-only)" = "Src/exec.c" ]]
done_phase
printf 'build-complete\n' > "${evidence}/build-complete"
