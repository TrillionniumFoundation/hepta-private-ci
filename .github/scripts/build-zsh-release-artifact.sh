#!/usr/bin/env bash

set -euo pipefail

if [[ "$#" -ne 1 ]]; then
  echo "usage: $0 <archive-path>" >&2
  exit 1
fi

archive_path="$1"
workspace="${GITHUB_WORKSPACE:?missing GITHUB_WORKSPACE}"
zsh_commit="${ZSH_COMMIT:?missing ZSH_COMMIT}"
zsh_patch="${ZSH_PATCH:?missing ZSH_PATCH}"
temp_root="${RUNNER_TEMP:-/tmp}"
work_root="$(mktemp -d "${temp_root%/}/codex-zsh-release.XXXXXX")"
trap 'rm -rf "$work_root"' EXIT

source_root="${work_root}/zsh"
package_root="${work_root}/codex-zsh"
wrapper_path="${work_root}/exec-wrapper"
stdout_path="${work_root}/stdout.txt"
wrapper_log_path="${work_root}/wrapper.log"

git clone https://git.code.sf.net/p/zsh/code "$source_root"
cd "$source_root"
git checkout "$zsh_commit"
git apply "${workspace}/${zsh_patch}"
./Util/preconfig
./configure

cores="$(command -v nproc >/dev/null 2>&1 && nproc || getconf _NPROCESSORS_ONLN)"
make -j"${cores}"

cat > "$wrapper_path" <<'EOF'
#!/usr/bin/env bash
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
EOF
chmod +x "$wrapper_path"

CODEX_WRAPPER_LOG="$wrapper_log_path" \
EXEC_WRAPPER="$wrapper_path" \
"${source_root}/Src/zsh" -fc '/bin/echo smoke-zsh' > "$stdout_path"

grep -Fx "smoke-zsh" "$stdout_path"
grep -Fx "/bin/echo" "$wrapper_log_path"

candidate_root="${work_root}/path-candidates"
mkdir -p "$candidate_root/bin" "$candidate_root/nonregular/codex-wrapper-path-smoke"
ln -s /bin/echo "$candidate_root/bin/codex-wrapper-path-smoke"
for exported in exported unexported; do
  (
    cd "$candidate_root"
    CODEX_WRAPPER_LOG="$wrapper_log_path" \
    EXEC_WRAPPER="$wrapper_path" \
    "${source_root}/Src/zsh" -fc '
      path=( "$1/missing" missing-relative "" "$1/nonregular" "$1/bin" /usr/bin /bin )
      if [[ "$2" == unexported ]]; then
        typeset +x PATH
      fi
      unsetopt HASH_CMDS
      codex-wrapper-path-smoke "smoke-path-$2"
    ' zsh "$candidate_root" "$exported" > "$stdout_path"
  )
  grep -Fx "smoke-path-$exported" "$stdout_path"
  grep -Fx "$candidate_root/bin/codex-wrapper-path-smoke" "$wrapper_log_path"
done

# Mode bits alone do not describe every filesystem's execute authority. Keep
# even a mode-0644 regular target on the original wrapper/owner decision path.
owner_wrapper="${work_root}/owner-wrapper"
mode_target="${work_root}/mode0644-command"
cat > "$owner_wrapper" <<'EOF'
#!/bin/sh
printf '%s\n' "$1" > "$CODEX_WRAPPER_LOG"
exit 73
EOF
printf '#!/bin/sh\nexit 0\n' > "$mode_target"
chmod +x "$owner_wrapper"
chmod 0644 "$mode_target"
rm -f "$wrapper_log_path"
set +e
CODEX_WRAPPER_LOG="$wrapper_log_path" EXEC_WRAPPER="$owner_wrapper" \
  "${source_root}/Src/zsh" -fc '"$1"' zsh "$mode_target"
owner_status=$?
set -e
if [[ "$owner_status" -ne 73 ]]; then
  echo "Mode bits bypassed the escalation-wrapper decision." >&2
  exit 1
fi
grep -Fx "$mode_target" "$wrapper_log_path"

# Seatbelt may hide metadata for a real executable that the escalation owner
# could approve. The fork must still hand that exact target to the wrapper.
if [[ "$(uname -s)" == Darwin ]]; then
  metadata_target="${work_root}/metadata-protected-command"
  cp /bin/echo "$metadata_target"
  metadata_target="$(cd "$work_root" && pwd -P)/metadata-protected-command"
  metadata_policy='(version 1)(allow default)(deny file-read-metadata (literal (param "BLOCKED_PATH")))'
  if /usr/bin/sandbox-exec -D "BLOCKED_PATH=$metadata_target" \
    -p "$metadata_policy" /usr/bin/stat -f '%p' "$metadata_target"; then
    echo "Seatbelt did not reject the metadata probe." >&2
    exit 1
  fi
  rm -f "$wrapper_log_path"
  set +e
  CODEX_WRAPPER_LOG="$wrapper_log_path" EXEC_WRAPPER="$owner_wrapper" \
    /usr/bin/sandbox-exec -D "BLOCKED_PATH=$metadata_target" \
    -p "$metadata_policy" "${source_root}/Src/zsh" -fc '"$1"' zsh "$metadata_target"
  metadata_status=$?
  set -e
  if [[ "$metadata_status" -ne 73 ]]; then
    echo "Metadata denial bypassed the escalation-wrapper decision." >&2
    exit 1
  fi
  grep -Fx "$metadata_target" "$wrapper_log_path"
fi

# A wrapper that the kernel cannot execute must never fall through to the
# original command's interpreter without going through that wrapper.
invalid_wrapper="${work_root}/invalid-wrapper"
fallback_command="${work_root}/fallback-command"
fallback_marker="${work_root}/unmediated-command-ran"
printf 'invalid executable format\n' > "$invalid_wrapper"
printf '#!/bin/sh\n: > "$1"\n' > "$fallback_command"
chmod +x "$invalid_wrapper" "$fallback_command"
if EXEC_WRAPPER="$invalid_wrapper" "${source_root}/Src/zsh" \
  -fc '"$1" "$2"' zsh "$fallback_command" "$fallback_marker"; then
  echo "Invalid wrapper unexpectedly permitted command execution." >&2
  exit 1
fi
if [[ -e "$fallback_marker" ]]; then
  echo "Command bypassed the failed execution wrapper." >&2
  exit 1
fi

mkdir -p "$package_root/bin" "$(dirname "${workspace}/${archive_path}")"
cp "${source_root}/Src/zsh" "$package_root/bin/zsh"
chmod +x "$package_root/bin/zsh"

(cd "$work_root" && tar -czf "${workspace}/${archive_path}" codex-zsh)
