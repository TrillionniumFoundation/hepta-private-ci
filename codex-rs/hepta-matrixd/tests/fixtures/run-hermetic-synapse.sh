#!/bin/bash
# shellcheck disable=SC2016,SC2329
# SC2016 covers the deliberately single-quoted docker inner shell; SC2329
# covers cleanup helpers invoked indirectly by signal/EXIT traps.

# The shebang is only a bootstrap. Before parsing any qualification logic,
# bind the actual interpreter to a canonical regular executable, require
# modern Bash semantics, hash it, and re-exec exactly that path once.
if [[ ${HEPTA_R4_CANONICAL_BASH_REEXEC:-0} != 1 ]]; then
  bootstrap_python=/opt/homebrew/bin/python3
  qualification_bash=${HEPTA_R4_QUALIFICATION_BASH:-/opt/homebrew/bin/bash}
  [[ "$qualification_bash" == /* \
    && -f "$bootstrap_python" && -x "$bootstrap_python" ]] || {
    echo 'absolute bootstrap Python or qualification Bash authority is invalid' >&2
    exit 69
  }
  canonical_bash=$(
    "$bootstrap_python" - "$qualification_bash" <<'PY'
import os
import pathlib
import stat
import sys

candidate = pathlib.Path(sys.argv[1]).resolve(strict=True)
metadata = candidate.stat()
if not stat.S_ISREG(metadata.st_mode) or not os.access(candidate, os.X_OK):
    raise SystemExit("qualification Bash is not a regular executable")
print(candidate)
PY
  ) || exit 69
  canonical_bash_sha256=$(
    "$bootstrap_python" - "$canonical_bash" <<'PY'
import hashlib
import pathlib
import sys

digest = hashlib.sha256()
with pathlib.Path(sys.argv[1]).open("rb") as source:
    while chunk := source.read(1024 * 1024):
        digest.update(chunk)
print(digest.hexdigest())
PY
  ) || exit 69
  qualification_bash_major=$("$canonical_bash" -c 'printf "%s\n" "${BASH_VERSINFO[0]}"') || exit 69
  [[ "$qualification_bash_major" =~ ^[0-9]+$ \
    && "$qualification_bash_major" -ge 4 ]] || {
    echo 'qualification runner requires Bash >= 4' >&2
    exit 69
  }
  export HEPTA_R4_CANONICAL_BASH_REEXEC=1
  export HEPTA_R4_CANONICAL_BASH="$canonical_bash"
  export HEPTA_R4_CANONICAL_BASH_SHA256="$canonical_bash_sha256"
  exec "$canonical_bash" "$0" "$@"
fi

set -euo pipefail
IFS=$'\n\t'

readonly PINNED_SYNAPSE_IMAGE='matrixdotorg/synapse@sha256:467a587a5052dadd5d0bf1f8d89f043cc652d5201bca510307340f8dddb6b312'
readonly PINNED_IMAGE_ID='sha256:d1292ef4b8d934a5b2acc9471eeabc53f718dd748cf10773454f401f678db784'
readonly PINNED_SYNAPSE_VERSION='1.159.0'
readonly PINNED_SYNAPSE_GIT_SHA='7b10e6b9bc2dacc33f0974c999f640b55ef831bc'
readonly QUALIFICATION_TEST_NAME='real_synapse_dual_agentd_dual_matrixd_restart_and_isolation'
readonly PAIRED_RELEASE_ID='r2-g4-synapse-paired-v1'
readonly EXACT_SOURCE_MODE='exact'
readonly DIAGNOSTIC_SOURCE_MODE='diagnostic'

usage() {
  echo 'usage: run-hermetic-synapse.sh --source-root PATH [--source-mode exact|diagnostic] --artifacts-dir DIR' >&2
  exit 64
}

source_root_arg=''
source_mode=$EXACT_SOURCE_MODE
artifacts_dir_arg=''
while (($#)); do
  case "$1" in
    --source-root)
      (($# >= 2)) || usage
      source_root_arg=$2
      shift 2
      ;;
    --source-mode)
      (($# >= 2)) || usage
      source_mode=$2
      shift 2
      ;;
    --artifacts-dir)
      (($# >= 2)) || usage
      artifacts_dir_arg=$2
      shift 2
      ;;
    *) usage ;;
  esac
done
[[ -n "$source_root_arg" && $# -eq 0 ]] || usage
case "$source_mode" in
  "$EXACT_SOURCE_MODE"|"$DIAGNOSTIC_SOURCE_MODE") ;;
  *) usage ;;
esac
if [[ -n "${HEPTA_R4_PRESERVE_ROOT+x}" ]]; then
  echo 'qualification forbids HEPTA_R4_PRESERVE_ROOT in every source mode' >&2
  exit 65
fi
python_bootstrap=/opt/homebrew/bin/python3
[[ -f "$python_bootstrap" && -x "$python_bootstrap" ]] || {
  echo 'fixed bootstrap Python is not a regular executable file' >&2
  exit 69
}
python_bin=$("$python_bootstrap" - "$python_bootstrap" <<'PY'
import os
import pathlib
import stat
import sys

resolved = pathlib.Path(sys.argv[1]).resolve(strict=True)
metadata = resolved.stat()
if not stat.S_ISREG(metadata.st_mode) or not os.access(resolved, os.X_OK):
    raise SystemExit("python3 bootstrap did not resolve to a regular file")
print(resolved)
PY
)
bash_bin=$("$python_bin" - "$HEPTA_R4_CANONICAL_BASH" <<'PY'
import pathlib
import sys

print(pathlib.Path(sys.argv[1]).resolve(strict=True))
PY
)
running_bash=$("$python_bin" - "$BASH" <<'PY'
import pathlib
import sys

print(pathlib.Path(sys.argv[1]).resolve(strict=True))
PY
)
[[ "$bash_bin" == "$HEPTA_R4_CANONICAL_BASH" \
  && "$running_bash" == "$bash_bin" \
  && ${BASH_VERSINFO[0]} -ge 4 ]] || {
  echo 'canonical Bash re-exec identity/version drifted' >&2
  exit 69
}
runner_control_tool_pairs=(bash "$bash_bin" python3 "$python_bin")
docker_bin=''
jq_bin=''
openssl_bin=''
curl_bin=''
git_bin=''
cargo_bootstrap_bin=''
rustup_bin=''
rustc_bin=''
awk_bin=''
basename_bin=''
dirname_bin=''
mktemp_bin=''
chmod_bin=''
mkdir_bin=''
rm_bin=''
cp_bin=''
find_bin=''
mv_bin=''
sort_bin=''
stat_bin=''
tr_bin=''
head_bin=''
sleep_bin=''
tee_bin=''
cmp_bin=''
ln_bin=''
env_bin=''
kill_bin=''
ps_bin=''
bind_runner_control_tool() {
  local tool_name=$1
  local output_variable=$2
  local discovered
  local resolved
  discovered=$(command -v "$tool_name" 2>/dev/null || true)
  [[ "$discovered" == /* && -f "$discovered" && -x "$discovered" ]] || {
    echo "required runner control tool is absent: $tool_name" >&2
    return 69
  }
  resolved=$("$python_bin" - "$discovered" <<'PY'
import pathlib
import sys

resolved = pathlib.Path(sys.argv[1]).resolve(strict=True)
if not resolved.is_file():
    raise SystemExit("runner control tool did not resolve to a regular file")
print(resolved)
PY
  ) || return 69
  printf -v "$output_variable" '%s' "$resolved"
  runner_control_tool_pairs+=("$tool_name" "$resolved")
}
bind_absolute_runner_control_tool() {
  local tool_name=$1
  local candidate=$2
  local output_variable=$3
  local resolved
  [[ "$candidate" == /* && -f "$candidate" && -x "$candidate" ]] || {
    echo "fixed runner control tool is absent: $tool_name" >&2
    return 69
  }
  resolved=$("$python_bin" - "$candidate" <<'PY'
import pathlib
import sys

resolved = pathlib.Path(sys.argv[1]).resolve(strict=True)
if not resolved.is_file():
    raise SystemExit("fixed runner control tool did not resolve to a regular file")
print(resolved)
PY
  ) || return 69
  printf -v "$output_variable" '%s' "$resolved"
  runner_control_tool_pairs+=("$tool_name" "$resolved")
}
bind_runner_control_tool docker docker_bin
bind_runner_control_tool jq jq_bin
bind_runner_control_tool openssl openssl_bin
bind_runner_control_tool curl curl_bin
bind_runner_control_tool git git_bin
bind_runner_control_tool cargo cargo_bootstrap_bin
bind_runner_control_tool awk awk_bin
bind_runner_control_tool basename basename_bin
bind_runner_control_tool dirname dirname_bin
bind_runner_control_tool mktemp mktemp_bin
bind_runner_control_tool chmod chmod_bin
bind_runner_control_tool mkdir mkdir_bin
bind_runner_control_tool rm rm_bin
bind_runner_control_tool cp cp_bin
bind_runner_control_tool find find_bin
bind_runner_control_tool mv mv_bin
bind_runner_control_tool sort sort_bin
bind_runner_control_tool stat stat_bin
bind_runner_control_tool tr tr_bin
bind_runner_control_tool head head_bin
bind_runner_control_tool sleep sleep_bin
bind_runner_control_tool tee tee_bin
bind_runner_control_tool cmp cmp_bin
bind_runner_control_tool ln ln_bin
bind_runner_control_tool env env_bin
bind_absolute_runner_control_tool kill /bin/kill kill_bin
bind_absolute_runner_control_tool ps /bin/ps ps_bin
rustup_bin=/opt/homebrew/opt/rustup/bin/rustup
[[ -L "$rustup_bin" && -x "$rustup_bin" ]] || {
  echo 'fixed rustup shim is absent or not executable' >&2
  exit 69
}
rustc_toolchain_bin=$("$rustup_bin" which rustc)
bind_absolute_runner_control_tool rustc "$rustc_toolchain_bin" rustc_bin
[[ -n "$cargo_bootstrap_bin" ]] || {
  echo 'Cargo runner control binding unexpectedly disappeared' >&2
  exit 69
}

# RUNNER_CONTROL_ABSOLUTE_ONLY_BEGIN
source_root=$(cd "$source_root_arg" && pwd -P)
runner_dir=$(cd "$("$dirname_bin" "${BASH_SOURCE[0]}")" && pwd -P)
runner_path="$runner_dir/$("$basename_bin" "${BASH_SOURCE[0]}")"
expected_runner="$source_root/codex-rs/hepta-matrixd/tests/fixtures/run-hermetic-synapse.sh"
[[ "$runner_path" == "$expected_runner" ]] || {
  echo 'fixture runner must be the checked-in runner under --source-root' >&2
  exit 65
}
proxy_source_path="$source_root/codex-rs/hepta-matrixd/tests/fixtures/synapse-loopback-proxy.py"
[[ -f "$proxy_source_path" && ! -L "$proxy_source_path" && -x "$proxy_source_path" ]] || {
  echo 'loopback proxy source must be a checked-in executable regular file' >&2
  exit 65
}
sha256_file() {
  "$openssl_bin" dgst -sha256 -r "$1" | "$awk_bin" '{print $1}'
}
proxy_source_sha256=$(sha256_file "$proxy_source_path")
build_tmp_base=${TMPDIR:-/tmp}
[[ -d "$build_tmp_base" ]] || {
  echo 'temporary directory base does not exist' >&2
  exit 73
}
# hepta-ssd-run may expose TMPDIR with a trailing separator. Canonicalize the
# build base before composing private fixture paths so the recorded bounded
# PATH and Rust-side canonical-path checks have one stable spelling.
build_tmp_base=$(
  cd "$build_tmp_base"
  pwd -P
)
# Keep build scratch lane-scoped, but place the private qualification root at
# the short SSD temp parent. Darwin's SUN_LEN applies to the textual socket
# path; retaining the lane hash here would make the otherwise bounded agent
# control sockets unbindable. The parent is fixed by hepta-ssd-run and each
# r4.* root remains mode-0700 and uniquely generated below.
fixture_tmp_base=/Volumes/T5/hepta-vnext/tmp
if [[ "$build_tmp_base" != /Volumes/T5/hepta-vnext/tmp/l-* ]]; then
  fixture_tmp_base="$build_tmp_base"
fi
[[ -d "$fixture_tmp_base" && ! -L "$fixture_tmp_base" ]] || {
  echo 'qualification fixture temporary base is not a physical directory' >&2
  exit 73
}
umask 077
fixture_root=$("$mktemp_bin" -d "$fixture_tmp_base/r4.XXXXXX")
fixture_manifest="$fixture_root/fixture-manifest.json"
credentials_directory="$fixture_root/qualification-capabilities"
runtime_tmp_root="$fixture_root/runtime-tmp"
test_home="$fixture_root/test-home"
"$chmod_bin" 700 "$fixture_root"
"$mkdir_bin" "$credentials_directory" "$runtime_tmp_root" "$test_home"
"$chmod_bin" 700 "$credentials_directory" "$runtime_tmp_root" "$test_home"
runner_control_tool_ledger="$fixture_root/runner-control-tool-ledger.json"
write_runner_control_tool_ledger() {
  local output_file=$1
  "$python_bin" - "$output_file" "${runner_control_tool_pairs[@]}" <<'PY'
import hashlib
import json
import os
import pathlib
import stat
import sys
import tempfile

output = pathlib.Path(sys.argv[1])
bindings = sys.argv[2:]
if len(bindings) % 2:
    raise SystemExit("runner control tool bindings are not name/path pairs")
entries = []
names = set()
for index in range(0, len(bindings), 2):
    name = bindings[index]
    target = pathlib.Path(bindings[index + 1]).resolve(strict=True)
    target_stat = target.stat()
    if not name or "/" in name or name in names:
        raise SystemExit(f"invalid or duplicate runner control tool name: {name}")
    if not stat.S_ISREG(target_stat.st_mode) or not os.access(target, os.X_OK):
        raise SystemExit(f"runner control tool is not a regular executable: {target}")
    names.add(name)
    digest = hashlib.sha256()
    with target.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    entries.append(
        {
            "name": name,
            "target": str(target),
            "sha256": digest.hexdigest(),
            "size_bytes": target_stat.st_size,
        }
    )
entries = sorted(entries, key=lambda item: item["name"].encode("utf-8"))
payload = {"schema_version": 1, "tools": entries}
encoded = (json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n").encode()
fd, temporary_name = tempfile.mkstemp(prefix=output.name + ".", dir=output.parent)
try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "wb", closefd=True) as destination:
        destination.write(encoded)
        destination.flush()
        os.fsync(destination.fileno())
    os.replace(temporary_name, output)
finally:
    try:
        os.unlink(temporary_name)
    except FileNotFoundError:
        pass
PY
}
write_runner_control_tool_ledger "$runner_control_tool_ledger"
runner_control_tool_ledger_sha256=$(sha256_file "$runner_control_tool_ledger")
bash_command_sha256=$(sha256_file "$bash_bin")
[[ "$bash_command_sha256" == "$HEPTA_R4_CANONICAL_BASH_SHA256" ]] || {
  echo 'canonical Bash digest changed across the required re-exec' >&2
  exit 69
}
bash_version=$("$bash_bin" --version | "$head_bin" -n 1)
bash_version_file="$fixture_root/bash-version.txt"
printf '%s\n' "$bash_version" >"$bash_version_file"
"$chmod_bin" 600 "$bash_version_file"
bash_version_sha256=$(sha256_file "$bash_version_file")

runner_control_static_scan="$fixture_root/runner-control-static-scan.json"
write_runner_control_static_scan() {
  local output_file=$1
  "$python_bin" - "$runner_path" "$output_file" <<'PY'
import hashlib
import json
import pathlib
import re
import sys
import tempfile
import os

source_path = pathlib.Path(sys.argv[1]).resolve(strict=True)
output = pathlib.Path(sys.argv[2])
full_source = source_path.read_text(encoding="utf-8")
marker = "# RUNNER_CONTROL_ABSOLUTE_ONLY_BEGIN"
source_lines = full_source.splitlines()
boundaries = [index for index, line in enumerate(source_lines) if line == marker]
if len(boundaries) != 1:
    raise SystemExit("runner control absolute-only marker is absent or ambiguous")
source = "\n".join(source_lines[boundaries[0] + 1:])
banned = sorted({
    "awk", "basename", "bash", "cargo", "chmod", "cmp", "cp", "curl",
    "dirname", "docker", "env", "find", "git", "head", "jq", "ln",
    "kill", "mkdir", "mktemp", "mv", "openssl", "ps", "python3", "rm",
    "rustc", "seq", "sleep", "sort", "stat", "tee", "tr",
})
prefix = r"(?:^|[;|&(]|\bthen\s+|\bdo\s+|\belse\s+)\s*"
assignments = r"(?:[A-Za-z_][A-Za-z0-9_]*=[^;|&()\s]+\s+)*"
pattern = re.compile(prefix + r"(?:!\s*)?" + assignments + "(" + "|".join(map(re.escape, banned)) + r")(?=$|[\s;|&()<>])")
skip_depth = 0
violations = []
for line_number, line in enumerate(source.splitlines(), 1):
    if "RUNNER_CONTROL_SCAN_SKIP_BEGIN" in line:
        skip_depth += 1
        continue
    if "RUNNER_CONTROL_SCAN_SKIP_END" in line:
        skip_depth -= 1
        if skip_depth < 0:
            raise SystemExit("runner control scan skip markers are unbalanced")
        continue
    if skip_depth:
        continue
    code = line.split("#", 1)[0]
    match = pattern.search(code)
    if match:
        violations.append({"line": line_number, "command": match.group(1)})
if skip_depth:
    raise SystemExit("runner control scan skip markers are unbalanced")
if violations:
    raise SystemExit(f"bare runner control command invocation(s): {violations}")
payload = {
    "schema_version": 1,
    "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
    "scan_boundary": marker,
    "banned_external_commands": banned,
    "bare_external_invocations": violations,
    "runner_control_tools_absolute": True,
}
encoded = (json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n").encode()
fd, temporary = tempfile.mkstemp(prefix=output.name + ".", dir=output.parent)
try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "wb", closefd=True) as destination:
        destination.write(encoded)
        destination.flush()
        os.fsync(destination.fileno())
    os.replace(temporary, output)
finally:
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
PY
}
write_runner_control_static_scan "$runner_control_static_scan"
runner_control_static_scan_sha256=$(sha256_file "$runner_control_static_scan")
process_identity_ledger="$fixture_root/process-identity-ledger.json"
"$python_bin" - "$process_identity_ledger" <<'PY'
import json
import os
import pathlib
import sys

output = pathlib.Path(sys.argv[1])
payload = {
    "schema_version": 1,
    "active": [],
    "history": [],
    "explicit_shutdown_completed": False,
    "all_historical_pids_absent": False,
}
fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "wb") as destination:
    destination.write((json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n").encode())
    destination.flush()
    os.fsync(destination.fileno())
PY
make_runtime_tree_removable() {
  local removable_root=$1
  [[ -n "$removable_root" && -e "$removable_root" ]] || return 0
  "$python_bin" - "$removable_root" "$fixture_root" <<'PY'
import os
import pathlib
import stat
import sys

root = pathlib.Path(sys.argv[1])
fixture_root = pathlib.Path(sys.argv[2]).resolve(strict=True)
if root.is_symlink():
    raise SystemExit("runtime cleanup root must not be a symlink")
resolved = root.resolve(strict=True)
if resolved != fixture_root / "runtime-tmp":
    raise SystemExit("runtime cleanup root escaped the private fixture root")
for current, directories, files in os.walk(resolved, topdown=True, followlinks=False):
    current_path = pathlib.Path(current)
    os.chmod(current_path, stat.S_IRWXU)
    directories[:] = [name for name in directories
                      if not (current_path / name).is_symlink()]
    for name in files:
        path = current_path / name
        if not path.is_symlink():
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
PY
}
cleanup_fixture_root_early() {
  local fixture_rc=$1
  trap - EXIT INT TERM
  case "$fixture_root" in
    "$fixture_tmp_base"/r4.*)
      make_runtime_tree_removable "$runtime_tmp_root" || true
      "$rm_bin" -rf -- "$fixture_root"
      ;;
    *) echo 'refusing to remove unexpected fixture directory' >&2 ;;
  esac
  exit "$fixture_rc"
}
trap 'cleanup_fixture_root_early $?' EXIT
trap 'cleanup_fixture_root_early 130' INT
trap 'cleanup_fixture_root_early 143' TERM

for forbidden_git_variable in \
  GIT_ALTERNATE_OBJECT_DIRECTORIES \
  GIT_COMMON_DIR \
  GIT_CONFIG \
  GIT_CONFIG_GLOBAL \
  GIT_CONFIG_SYSTEM \
  GIT_DIR \
  GIT_OBJECT_DIRECTORY \
  GIT_WORK_TREE; do
  if [[ -n "${!forbidden_git_variable+x}" ]]; then
    echo "qualification runner forbids inherited $forbidden_git_variable" >&2
    exit 65
  fi
done
runner_git=(
  "$env_bin" -i
  "HOME=$test_home"
  'LANG=C'
  'LC_ALL=C'
  'GIT_CONFIG_NOSYSTEM=1'
  'GIT_CONFIG_GLOBAL=/dev/null'
  'GIT_OPTIONAL_LOCKS=0'
  "$git_bin"
)

git_toplevel=$("${runner_git[@]}" -C "$source_root" rev-parse --show-toplevel)
git_toplevel=$(cd "$git_toplevel" && pwd -P)
[[ "$git_toplevel" == "$source_root" ]] || {
  echo '--source-root must be the exact Git worktree root' >&2
  exit 65
}
candidate_sha=$("${runner_git[@]}" -C "$source_root" rev-parse --verify HEAD)
candidate_tree_sha=$("${runner_git[@]}" -C "$source_root" rev-parse --verify 'HEAD^{tree}')
[[ "$candidate_sha" =~ ^[0-9a-f]{40}$ && "$candidate_tree_sha" =~ ^[0-9a-f]{40}$ ]] || {
  echo 'candidate Git identity is not canonical SHA-1' >&2
  exit 65
}
source_status_file="$fixture_root/source-status.porcelain"
"${runner_git[@]}" -C "$source_root" status \
  --porcelain=v1 --untracked-files=all --ignored=matching >"$source_status_file"
source_status_sha256=$(sha256_file "$source_status_file")
source_clean=true
if [[ -s "$source_status_file" ]]; then
  source_clean=false
fi
if [[ "$source_mode" == "$EXACT_SOURCE_MODE" && "$source_clean" != true ]]; then
  echo 'exact source mode requires a clean Git worktree, including no untracked files' >&2
  exit 65
fi
if [[ -z "$artifacts_dir_arg" ]]; then
  echo 'every source mode requires a fresh --artifacts-dir for durable evidence' >&2
  exit 64
fi

cargo_lock="$source_root/codex-rs/Cargo.lock"
workspace_manifest="$source_root/codex-rs/Cargo.toml"
cargo_config="$source_root/codex-rs/.cargo/config.toml"
agentd_manifest="$source_root/codex-rs/hepta-agentd/Cargo.toml"
matrixd_manifest="$source_root/codex-rs/hepta-matrixd/Cargo.toml"
matrix_sdk_manifest="$source_root/codex-rs/hepta-matrix-sdk/Cargo.toml"
rust_toolchain_manifest="$source_root/codex-rs/rust-toolchain.toml"
for source_manifest in \
  "$cargo_lock" \
  "$workspace_manifest" \
  "$cargo_config" \
  "$agentd_manifest" \
  "$matrixd_manifest" \
  "$matrix_sdk_manifest" \
  "$rust_toolchain_manifest"; do
  [[ -f "$source_manifest" ]] || {
    echo "required source manifest is absent: $source_manifest" >&2
    exit 65
  }
done
cargo_lock_sha256=$(sha256_file "$cargo_lock")
workspace_manifest_sha256=$(sha256_file "$workspace_manifest")
cargo_config_sha256=$(sha256_file "$cargo_config")
agentd_manifest_sha256=$(sha256_file "$agentd_manifest")
matrixd_manifest_sha256=$(sha256_file "$matrixd_manifest")
matrix_sdk_manifest_sha256=$(sha256_file "$matrix_sdk_manifest")
rust_toolchain_manifest_sha256=$(sha256_file "$rust_toolchain_manifest")
rust_toolchain_channel=$(
  "$python_bin" - "$rust_toolchain_manifest" <<'PY'
import pathlib
import sys
import tomllib

manifest = pathlib.Path(sys.argv[1])
with manifest.open("rb") as source:
    channel = tomllib.load(source).get("toolchain", {}).get("channel")
if not isinstance(channel, str) or not channel:
    raise SystemExit("rust-toolchain.toml omitted a non-empty toolchain channel")
print(channel)
PY
)

# Rustup chooses a directory toolchain before it invokes rustc. Resolve that
# choice from the candidate Cargo workspace so an invocation from another working
# directory cannot silently select a different canonical toolchain.
rustc_sysroot=$(
  cd "$source_root/codex-rs"
  "$rustc_bin" --print sysroot
)
rustc_command=$("$python_bin" - "$rustc_sysroot/bin/rustc" <<'PY'
import pathlib
import sys

print(pathlib.Path(sys.argv[1]).resolve(strict=True))
PY
)
cargo_command=$("$python_bin" - "$rustc_sysroot/bin/cargo" <<'PY'
import pathlib
import sys

print(pathlib.Path(sys.argv[1]).resolve(strict=True))
PY
)
rustdoc_command=$("$python_bin" - "$rustc_sysroot/bin/rustdoc" <<'PY'
import pathlib
import sys

print(pathlib.Path(sys.argv[1]).resolve(strict=True))
PY
)
[[ -f "$rustc_command" && -x "$rustc_command" \
  && -f "$cargo_command" && -x "$cargo_command" \
  && -f "$rustdoc_command" && -x "$rustdoc_command" ]] || {
  echo 'canonical Rust toolchain executables are absent or not executable' >&2
  exit 65
}
rustc_command_sha256=$(sha256_file "$rustc_command")
cargo_command_sha256=$(sha256_file "$cargo_command")
rustdoc_command_sha256=$(sha256_file "$rustdoc_command")
rustc_verbose_file="$fixture_root/rustc-vv.txt"
"$rustc_command" -Vv >"$rustc_verbose_file"
rustc_verbose_sha256=$(sha256_file "$rustc_verbose_file")
rustc_release=$("$awk_bin" -F ': ' '$1 == "release" { print $2 }' "$rustc_verbose_file")
rustc_commit=$("$awk_bin" -F ': ' '$1 == "commit-hash" { print $2 }' "$rustc_verbose_file")
rustc_host=$("$awk_bin" -F ': ' '$1 == "host" { print $2 }' "$rustc_verbose_file")
target_triple=$rustc_host
cargo_version=$("$cargo_command" -V)
[[ -n "$rustc_release" && "$rustc_commit" =~ ^[0-9a-f]{40}$ && -n "$rustc_host" && -n "$target_triple" && -n "$cargo_version" ]] || {
  echo 'Rust toolchain identity is incomplete' >&2
  exit 65
}
[[ "$rustc_release" == "$rust_toolchain_channel" ]] || {
  echo 'canonical rustc release disagrees with candidate rust-toolchain.toml' >&2
  exit 65
}

echo "R4_SOURCE mode=$source_mode candidate_sha=$candidate_sha candidate_tree_sha=$candidate_tree_sha clean=$source_clean status_sha256=$source_status_sha256"
echo "R4_BUILD target=$rustc_host agentd_profile=dev matrixd_profile=dev test_profile=test matrixd_features=real-synapse-e2e sdk_features=qualification-failpoints"

for forbidden_build_variable in \
  RUSTFLAGS \
  CARGO_ENCODED_RUSTFLAGS \
  RUSTC_WRAPPER \
  RUSTC_WORKSPACE_WRAPPER \
  MACOSX_DEPLOYMENT_TARGET; do
  if [[ -n "${!forbidden_build_variable+x}" ]]; then
    echo "qualification build forbids inherited $forbidden_build_variable" >&2
    exit 65
  fi
done
while IFS='=' read -r build_variable_name _build_variable_value; do
  case "$build_variable_name" in
    CARGO_PROFILE_*|CARGO_TARGET_*_RUSTFLAGS)
      echo "qualification build forbids inherited $build_variable_name" >&2
      exit 65
      ;;
  esac
done < <("$env_bin")

build_home="$fixture_root/build-home"
product_build_target="$fixture_root/cargo-target-product"
test_build_target="$fixture_root/cargo-target-test"
qualification_cargo_home="$build_home/cargo-home"
rust_tool_bin="$build_home/rust-tools"
"$mkdir_bin" -p \
  "$build_home" \
  "$product_build_target" \
  "$test_build_target" \
  "$qualification_cargo_home" \
  "$rust_tool_bin"
"$chmod_bin" 700 \
  "$build_home" \
  "$product_build_target" \
  "$test_build_target" \
  "$qualification_cargo_home" \
  "$rust_tool_bin"
"$ln_bin" -s "$rustc_command" "$rust_tool_bin/rustc"
"$ln_bin" -s "$cargo_command" "$rust_tool_bin/cargo"
"$ln_bin" -s "$rustdoc_command" "$rust_tool_bin/rustdoc"

# Do not pass the invoking account's PATH into Cargo or build scripts.  A
# private tool directories expose only the closed, recorded Rust and host-tool
# sets required by Cargo/build scripts. This remains a qualification of the
# exact Mac/Xcode host, not a claim that Apple's SDK or linker are hermetic.
host_tool_bin="$build_home/host-tools"
host_tool_ledger="$fixture_root/host-tool-ledger.json"
"$mkdir_bin" "$host_tool_bin"
"$chmod_bin" 700 "$host_tool_bin"
readonly -a REQUIRED_HOST_TOOLS=(
  # RUNNER_CONTROL_SCAN_SKIP_BEGIN: build-tool allowlist data, not invocations.
  ar awk bash c++ cat cc chmod clang clang++ cmake codesign cp cut date dirname
  dsymutil env find git grep head install_name_tool ld lipo ln make mkdir mv nm
  otool perl python3 ranlib rm sed sh sort strip tail touch tr uname wc xargs
  xcode-select xcodebuild xcrun
  # RUNNER_CONTROL_SCAN_SKIP_END
)
for host_tool_name in "${REQUIRED_HOST_TOOLS[@]}"; do
  host_tool_source=$(command -v "$host_tool_name" 2>/dev/null || true)
  [[ "$host_tool_source" == /* && -f "$host_tool_source" && -x "$host_tool_source" ]] || {
    echo "qualification host tool is absent or not an executable file: $host_tool_name" >&2
    exit 69
  }
  host_tool_source=$(
    "$python_bin" - "$host_tool_source" <<'PY'
import pathlib
import sys

print(pathlib.Path(sys.argv[1]).resolve(strict=True))
PY
  )
  "$ln_bin" -s "$host_tool_source" "$host_tool_bin/$host_tool_name"
done

write_link_tool_ledger() {
  local tool_root=$1
  local output_file=$2
  "$python_bin" - "$tool_root" "$output_file" <<'PY'
import hashlib
import json
import os
import pathlib
import stat
import sys
import tempfile

root = pathlib.Path(sys.argv[1])
output = pathlib.Path(sys.argv[2])
entries = []
for entry in sorted(os.scandir(root), key=lambda item: os.fsencode(item.name)):
    link = pathlib.Path(entry.path)
    link_stat = link.lstat()
    if not stat.S_ISLNK(link_stat.st_mode):
        raise SystemExit(f"host tool allowlist entry is not a symlink: {link}")
    target = link.resolve(strict=True)
    target_stat = target.stat()
    if not stat.S_ISREG(target_stat.st_mode) or not os.access(target, os.X_OK):
        raise SystemExit(f"host tool target is not a regular executable: {target}")
    digest = hashlib.sha256()
    with target.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    entries.append(
        {
            "name": entry.name,
            "target": str(target),
            "sha256": digest.hexdigest(),
            "size_bytes": target_stat.st_size,
        }
    )
payload = {"schema_version": 1, "tools": entries}
encoded = (json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n").encode()
fd, temporary_name = tempfile.mkstemp(prefix=output.name + ".", dir=output.parent)
try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "wb", closefd=True) as destination:
        destination.write(encoded)
        destination.flush()
        os.fsync(destination.fileno())
    os.replace(temporary_name, output)
finally:
    try:
        os.unlink(temporary_name)
    except FileNotFoundError:
        pass
PY
}
write_link_tool_ledger "$host_tool_bin" "$host_tool_ledger"
host_tool_ledger_sha256=$(sha256_file "$host_tool_ledger")
rust_tool_ledger="$fixture_root/rust-tool-ledger.json"
write_link_tool_ledger "$rust_tool_bin" "$rust_tool_ledger"
rust_tool_ledger_sha256=$(sha256_file "$rust_tool_ledger")
build_path="$rust_tool_bin:$host_tool_bin"
[[ "$build_path" != *"$PATH"* ]] || {
  echo 'qualification build PATH unexpectedly inherited the invoking PATH' >&2
  exit 65
}

xcrun_command=$(
  "$python_bin" - "$host_tool_bin/xcrun" <<'PY'
import pathlib
import sys

print(pathlib.Path(sys.argv[1]).resolve(strict=True))
PY
)
xcode_select_command=$(
  "$python_bin" - "$host_tool_bin/xcode-select" <<'PY'
import pathlib
import sys

print(pathlib.Path(sys.argv[1]).resolve(strict=True))
PY
)
xcodebuild_command=$("$xcrun_command" --find xcodebuild)
clang_command=$("$xcrun_command" --sdk macosx --find clang)
clangxx_command=$("$xcrun_command" --sdk macosx --find clang++)
linker_command=$("$xcrun_command" --sdk macosx --find ld)
ar_command=$("$xcrun_command" --sdk macosx --find ar)
ranlib_command=$("$xcrun_command" --sdk macosx --find ranlib)
macos_sdk_path=$("$xcrun_command" --sdk macosx --show-sdk-path)
developer_dir=$("$xcode_select_command" -p)
for canonical_host_path_variable in \
  xcodebuild_command clang_command clangxx_command linker_command ar_command ranlib_command \
  macos_sdk_path developer_dir; do
  printf -v "$canonical_host_path_variable" '%s' "$(
    "$python_bin" - "${!canonical_host_path_variable}" <<'PY'
import pathlib
import sys

print(pathlib.Path(sys.argv[1]).resolve(strict=True))
PY
  )"
done
[[ -f "$xcodebuild_command" && -x "$xcodebuild_command" \
  && -f "$clang_command" && -x "$clang_command" \
  && -f "$clangxx_command" && -x "$clangxx_command" \
  && -f "$linker_command" && -x "$linker_command" \
  && -f "$ar_command" && -x "$ar_command" \
  && -f "$ranlib_command" && -x "$ranlib_command" \
  && -d "$macos_sdk_path" && -d "$developer_dir" ]] || {
  echo 'bounded Xcode toolchain or macOS SDK identity is invalid' >&2
  exit 65
}
macos_sdk_version=$("$xcrun_command" --sdk macosx --show-sdk-version)
macos_sdk_build_version=$("$xcrun_command" --sdk macosx --show-sdk-build-version)
clang_resource_dir=$("$clang_command" -print-resource-dir)
clang_resource_dir=$(
  "$python_bin" - "$clang_resource_dir" <<'PY'
import pathlib
import sys

print(pathlib.Path(sys.argv[1]).resolve(strict=True))
PY
)
[[ -d "$clang_resource_dir" ]] || {
  echo 'Apple clang resource directory is absent' >&2
  exit 65
}
macos_sdk_settings="$macos_sdk_path/SDKSettings.json"
[[ -f "$macos_sdk_settings" ]] || {
  echo 'macOS SDK settings identity is absent' >&2
  exit 65
}
xcrun_command_sha256=$(sha256_file "$xcrun_command")
xcodebuild_command_sha256=$(sha256_file "$xcodebuild_command")
clang_command_sha256=$(sha256_file "$clang_command")
clangxx_command_sha256=$(sha256_file "$clangxx_command")
linker_command_sha256=$(sha256_file "$linker_command")
ar_command_sha256=$(sha256_file "$ar_command")
ranlib_command_sha256=$(sha256_file "$ranlib_command")
macos_sdk_settings_sha256=$(sha256_file "$macos_sdk_settings")
xcodebuild_version_file="$fixture_root/xcodebuild-version.txt"
"$xcodebuild_command" -version >"$xcodebuild_version_file"
xcodebuild_version_sha256=$(sha256_file "$xcodebuild_version_file")

apple_build_input_ledger="$fixture_root/apple-build-input-ledger.json"
write_apple_build_input_ledger() {
  local output_file=$1
  "$python_bin" - \
    "$developer_dir" \
    "$macos_sdk_path" \
    "$clang_resource_dir" \
    "$output_file" <<'PY'
import hashlib
import json
import os
import pathlib
import stat
import sys
import tempfile

developer = pathlib.Path(sys.argv[1]).resolve(strict=True)
roots = [
    ("macos_sdk", pathlib.Path(sys.argv[2]).resolve(strict=True)),
    ("clang_resource", pathlib.Path(sys.argv[3]).resolve(strict=True)),
]
output = pathlib.Path(sys.argv[4])
entries = []


def within(path: pathlib.Path, root: pathlib.Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def visit(label: str, root: pathlib.Path, directory: pathlib.Path) -> None:
    directory_stat = directory.lstat()
    if not stat.S_ISDIR(directory_stat.st_mode):
        raise SystemExit(f"Apple build input root is not a physical directory: {directory}")
    for entry in sorted(os.scandir(directory), key=lambda item: os.fsencode(item.name)):
        entry_path = pathlib.Path(entry.path)
        entry_stat = entry.stat(follow_symlinks=False)
        relative = entry_path.relative_to(root).as_posix()
        relative.encode("utf-8", "strict")
        ledger_path = f"{label}/{relative}"
        if stat.S_ISDIR(entry_stat.st_mode):
            visit(label, root, entry_path)
            continue
        if stat.S_ISREG(entry_stat.st_mode):
            digest = hashlib.sha256()
            with entry_path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
            entries.append(
                {
                    "kind": "file",
                    "path": ledger_path,
                    "sha256": digest.hexdigest(),
                    "size_bytes": entry_stat.st_size,
                }
            )
            continue
        if stat.S_ISLNK(entry_stat.st_mode):
            link_target = os.readlink(entry_path)
            resolved = entry_path.resolve(strict=True)
            # Every symlink target must remain inside one of the two fully
            # enumerated roots. That makes the target's eventual file bytes
            # appear elsewhere in this same ledger instead of trusting an
            # unmanifested path elsewhere in the Xcode developer directory.
            if not any(within(resolved, manifest_root) for _, manifest_root in roots):
                raise SystemExit(f"Apple build input symlink escapes manifest roots: {entry_path}")
            entries.append(
                {
                    "kind": "symlink",
                    "path": ledger_path,
                    "target": link_target,
                    "resolved": str(resolved),
                }
            )
            continue
        raise SystemExit(f"Apple build input contains a non-regular entry: {entry_path}")


for label, root in roots:
    if not within(root, developer):
        raise SystemExit(f"Apple build input root escapes Xcode developer dir: {root}")
    visit(label, root, root)
entries = sorted(entries, key=lambda item: item["path"].encode("utf-8"))
payload = {
    "schema_version": 1,
    "developer_dir": str(developer),
    "roots": [{"label": label, "path": str(root)} for label, root in roots],
    "entries": entries,
}
encoded = (json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n").encode()
fd, temporary_name = tempfile.mkstemp(prefix=output.name + ".", dir=output.parent)
try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "wb", closefd=True) as destination:
        destination.write(encoded)
        destination.flush()
        os.fsync(destination.fileno())
    os.replace(temporary_name, output)
finally:
    try:
        os.unlink(temporary_name)
    except FileNotFoundError:
        pass
PY
}
write_apple_build_input_ledger "$apple_build_input_ledger"
apple_build_input_ledger_sha256=$(sha256_file "$apple_build_input_ledger")
apple_build_input_entry_count=$("$jq_bin" -er '.entries | length' "$apple_build_input_ledger")
target_linker_environment_key="CARGO_TARGET_$(printf '%s' "$target_triple" | "$tr_bin" '[:lower:]-' '[:upper:]_')_LINKER"

# Cargo may otherwise reuse unpacked or mutable dependency source from the invoking account.
# Seed a fresh credential-free Cargo home only with immutable registry archives/index data and
# bare git databases. Cargo recreates registry/src and git/checkouts itself under --offline;
# Cargo.lock binds registry archives by checksum and git dependencies by exact commit.
inherited_cargo_home=${CARGO_HOME:-"$HOME/.cargo"}
inherited_cargo_home=$(
  cd "$inherited_cargo_home"
  pwd -P
) || {
  echo 'qualification Cargo seed home is unavailable' >&2
  exit 65
}
for inherited_cargo_config in \
  "$inherited_cargo_home/config" \
  "$inherited_cargo_home/config.toml" \
  "$inherited_cargo_home/credentials" \
  "$inherited_cargo_home/credentials.toml"; do
  if [[ -e "$inherited_cargo_config" || -L "$inherited_cargo_config" ]]; then
    case "$("$basename_bin" "$inherited_cargo_config")" in
      config|config.toml)
        echo 'qualification forbids inherited Cargo home configuration' >&2
        exit 65
        ;;
      credentials|credentials.toml)
        # Credentials are deliberately not copied into the sanitized offline home.
        ;;
    esac
  fi
done
readonly -a CARGO_SEED_ROOTS=(registry/cache registry/index git/db)
for cargo_seed_relative in "${CARGO_SEED_ROOTS[@]}"; do
  cargo_seed_source="$inherited_cargo_home/$cargo_seed_relative"
  [[ -d "$cargo_seed_source" ]] || continue
  if [[ -n "$("$find_bin" "$cargo_seed_source" -type l -print -quit)" ]]; then
    echo "qualification Cargo seed contains a symlink: $cargo_seed_relative" >&2
    exit 65
  fi
  "$mkdir_bin" -p "$("$dirname_bin" "$qualification_cargo_home/$cargo_seed_relative")"
  "$cp_bin" -R "$cargo_seed_source" "$qualification_cargo_home/$cargo_seed_relative"
done
"$chmod_bin" -R u+rwX,go-rwx "$qualification_cargo_home"
for forbidden_sanitized_path in \
  "$qualification_cargo_home/config" \
  "$qualification_cargo_home/config.toml" \
  "$qualification_cargo_home/credentials" \
  "$qualification_cargo_home/credentials.toml" \
  "$qualification_cargo_home/registry/src" \
  "$qualification_cargo_home/git/checkouts"; do
  if [[ -e "$forbidden_sanitized_path" || -L "$forbidden_sanitized_path" ]]; then
    echo "sanitized Cargo home unexpectedly contains $("$basename_bin" "$forbidden_sanitized_path")" >&2
    exit 65
  fi
done

cargo_seed_ledger="$fixture_root/cargo-dependency-seed-ledger.json"
write_cargo_seed_ledger() {
  local output_file=$1
  "$python_bin" - "$qualification_cargo_home" "$output_file" <<'PY'
import hashlib
import json
import os
import pathlib
import stat
import sys
import tempfile

root = pathlib.Path(sys.argv[1])
output = pathlib.Path(sys.argv[2])
seed_roots = ("registry/cache", "registry/index", "git/db")
files = []


def visit(directory: pathlib.Path) -> None:
    directory_stat = directory.lstat()
    if not stat.S_ISDIR(directory_stat.st_mode):
        raise SystemExit(f"Cargo dependency seed path is not a physical directory: {directory}")
    for entry in sorted(os.scandir(directory), key=lambda item: os.fsencode(item.name)):
        entry_path = pathlib.Path(entry.path)
        entry_stat = entry.stat(follow_symlinks=False)
        if stat.S_ISLNK(entry_stat.st_mode):
            raise SystemExit(f"Cargo dependency seed contains a symlink: {entry_path}")
        if stat.S_ISDIR(entry_stat.st_mode):
            visit(entry_path)
            continue
        if not stat.S_ISREG(entry_stat.st_mode):
            raise SystemExit(f"Cargo dependency seed contains a non-regular entry: {entry_path}")
        relative = entry_path.relative_to(root).as_posix()
        relative.encode("utf-8", "strict")
        digest = hashlib.sha256()
        with entry_path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        files.append(
            {
                "path": relative,
                "sha256": digest.hexdigest(),
                "size_bytes": entry_stat.st_size,
            }
        )


root_stat = root.lstat()
if not stat.S_ISDIR(root_stat.st_mode):
    raise SystemExit("sanitized Cargo home is not a physical directory")
for relative_root in seed_roots:
    seed_root = root / relative_root
    if seed_root.exists() or seed_root.is_symlink():
        current = root
        for component in pathlib.PurePosixPath(relative_root).parts:
            current /= component
            current_stat = current.lstat()
            if not stat.S_ISDIR(current_stat.st_mode):
                raise SystemExit(
                    f"Cargo dependency seed ancestor is a symlink or non-directory: {current}"
                )
        visit(seed_root)
files = sorted(files, key=lambda item: item["path"].encode("utf-8"))
payload = {
    "schema_version": 1,
    "roots": list(seed_roots),
    "files": files,
}
encoded = (json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n").encode()
output.parent.mkdir(parents=True, exist_ok=True)
fd, temporary_name = tempfile.mkstemp(prefix=output.name + ".", dir=output.parent)
try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "wb", closefd=True) as destination:
        destination.write(encoded)
        destination.flush()
        os.fsync(destination.fileno())
    os.replace(temporary_name, output)
finally:
    try:
        os.unlink(temporary_name)
    except FileNotFoundError:
        pass
PY
}
cargo_seed_preflight_ledger="$fixture_root/cargo-dependency-seed-preflight.json"
write_cargo_seed_ledger "$cargo_seed_preflight_ledger"
"$rm_bin" -f -- "$cargo_seed_preflight_ledger"

seed_git=(
  "$env_bin" -i
  "HOME=$build_home"
  'LANG=C'
  'LC_ALL=C'
  'GIT_CONFIG_NOSYSTEM=1'
  'GIT_CONFIG_GLOBAL=/dev/null'
  'GIT_ALTERNATE_OBJECT_DIRECTORIES='
  "$git_bin"
)
reject_external_git_database_authority() {
  local database=$1
  local alternate
  local config_file
  local config_name
  local config_names_file
  if [[ -e "$database/shallow" || -L "$database/shallow" ]]; then
    echo "Cargo git database is shallow and cannot be used as an exact seed: $database/shallow" >&2
    return 65
  fi
  if [[ -n "$("$find_bin" "$database/objects/pack" -type f -name '*.promisor' -print -quit 2>/dev/null)" ]]; then
    echo "Cargo git database contains a promisor pack marker: $database" >&2
    return 65
  fi
  for alternate in \
    "$database/objects/info/alternates" \
    "$database/objects/info/http-alternates"; do
    if [[ -e "$alternate" || -L "$alternate" ]]; then
      echo "Cargo git database contains external object authority: $alternate" >&2
      return 65
    fi
  done
  if [[ -n "$("$find_bin" "$database" \
    \( -path '*/objects/info/alternates' -o -path '*/objects/info/http-alternates' \) \
    -print -quit)" ]]; then
    echo "Cargo git database contains nested alternate object authority: $database" >&2
    return 65
  fi
  for config_file in "$database/config" "$database/config.worktree"; do
    [[ -e "$config_file" || -L "$config_file" ]] || continue
    [[ -f "$config_file" && ! -L "$config_file" ]] || {
      echo "Cargo git database config is not a physical regular file: $config_file" >&2
      return 65
    }
    config_names_file="$fixture_root/git-config-names.$$.txt"
    "$rm_bin" -f -- "$config_names_file"
    if ! "${seed_git[@]}" config \
      --file "$config_file" --no-includes --name-only --list >"$config_names_file"; then
      echo "Cargo git database config is malformed: $config_file" >&2
      "$rm_bin" -f -- "$config_names_file"
      return 65
    fi
    while IFS= read -r config_name; do
      case "${config_name,,}" in
        include.*|includeif.*|core.alternaterefscommand|extensions.partialclone|remote.*.promisor|remote.*.partialclonefilter)
          echo "Cargo git database config contains external authority $config_name: $config_file" >&2
          return 65
          ;;
      esac
    done <"$config_names_file"
    "$rm_bin" -f -- "$config_names_file"
  done
}

cargo_git_database_count=0
if [[ -d "$qualification_cargo_home/git/db" ]]; then
  while IFS= read -r cargo_git_database; do
    [[ -n "$cargo_git_database" ]] || continue
    [[ -d "$cargo_git_database" && ! -L "$cargo_git_database" ]] || {
      echo "Cargo git database is not a physical directory: $cargo_git_database" >&2
      exit 65
    }
    [[ "$("${seed_git[@]}" --git-dir="$cargo_git_database" rev-parse --is-bare-repository)" == true ]] || {
      echo "Cargo git dependency database is not bare: $cargo_git_database" >&2
      exit 65
    }
    reject_external_git_database_authority "$cargo_git_database"
    "${seed_git[@]}" --git-dir="$cargo_git_database" repack -a -d
    reject_external_git_database_authority "$cargo_git_database"
    "${seed_git[@]}" --git-dir="$cargo_git_database" fsck --full --strict --no-reflogs
    cargo_git_database_count=$((cargo_git_database_count + 1))
  done < <("$find_bin" "$qualification_cargo_home/git/db" \
    -mindepth 1 -maxdepth 1 -type d -print | LC_ALL=C "$sort_bin")
fi
[[ "$cargo_git_database_count" =~ ^[0-9]+$ ]] || {
  echo 'Cargo git database count is invalid' >&2
  exit 65
}
write_cargo_seed_ledger "$cargo_seed_ledger"
cargo_seed_manifest_sha256=$(sha256_file "$cargo_seed_ledger")
[[ "$cargo_seed_manifest_sha256" =~ ^[0-9a-f]{64}$ ]] || {
  echo 'sanitized Cargo dependency seed manifest digest is invalid' >&2
  exit 65
}
cargo_seed_file_count=$("$jq_bin" -er '.files | length' "$cargo_seed_ledger") || {
  echo 'sanitized Cargo dependency seed ledger is malformed' >&2
  exit 65
}
[[ "$cargo_seed_file_count" =~ ^[0-9]+$ ]] || {
  echo 'sanitized Cargo dependency seed ledger has an invalid file count' >&2
  exit 65
}

# Cargo also discovers configuration by walking cwd ancestors. The candidate-owned config above
# is the sole allowed file; an untracked host/worktree-parent config would change the build.
verify_bound_cargo_configs() {
  local cargo_config_scan_directory="$source_root/codex-rs"
  local discovered_cargo_config
  while :; do
    for discovered_cargo_config in \
      "$cargo_config_scan_directory/.cargo/config" \
      "$cargo_config_scan_directory/.cargo/config.toml"; do
      if [[ -e "$discovered_cargo_config" || -L "$discovered_cargo_config" ]]; then
        discovered_cargo_config=$(
          cd "$("$dirname_bin" "$discovered_cargo_config")"
          printf '%s/%s\n' "$PWD" "$("$basename_bin" "$discovered_cargo_config")"
        )
        [[ "$discovered_cargo_config" == "$cargo_config" ]] || {
          echo "qualification forbids Cargo config outside the bound candidate path: $discovered_cargo_config" >&2
          return 65
        }
      fi
    done
    [[ "$cargo_config_scan_directory" == / ]] && break
    cargo_config_scan_directory=$("$dirname_bin" "$cargo_config_scan_directory")
  done
}
verify_bound_cargo_configs
build_environment=(
  "$env_bin" -i
  "PATH=$build_path"
  "HOME=$build_home"
  "TMPDIR=$build_tmp_base"
  'LANG=C'
  'LC_ALL=C'
  'CARGO_NET_OFFLINE=true'
  "CARGO_HOME=$qualification_cargo_home"
  "RUSTC=$rust_tool_bin/rustc"
  "RUSTDOC=$rust_tool_bin/rustdoc"
  "SDKROOT=$macos_sdk_path"
  "DEVELOPER_DIR=$developer_dir"
  "CC=$clang_command"
  "CXX=$clangxx_command"
  "AR=$ar_command"
  "RANLIB=$ranlib_command"
  "LD=$linker_command"
  "$target_linker_environment_key=$clang_command"
)

run_cargo_json() {
  local output_path=$1
  local target_directory=$2
  shift 2
  local temporary_output="$output_path.tmp"
  "$rm_bin" -f -- "$temporary_output"
  if ! (
    cd "$source_root/codex-rs"
    "${build_environment[@]}" "CARGO_TARGET_DIR=$target_directory" \
      "$cargo_command" "$@" --message-format=json-render-diagnostics
  ) >"$temporary_output"; then
    echo "candidate-owned Cargo build failed: $*" >&2
    return 65
  fi
  "$mv_bin" "$temporary_output" "$output_path"
}

resolve_single_cargo_artifact() {
  local json_path=$1
  local target_name=$2
  local target_kind=$3
  local expected_test_profile=$4
  local output_variable=$5
  local artifact
  artifact=$("$jq_bin" -r \
    --arg target_name "$target_name" \
    --arg target_kind "$target_kind" \
    --argjson expected_test_profile "$expected_test_profile" \
    'select(
      .reason == "compiler-artifact"
      and .target.name == $target_name
      and (.target.kind | index($target_kind)) != null
      and .executable != null
      and .profile.test == $expected_test_profile
    ) | .executable' "$json_path" | LC_ALL=C "$sort_bin" -u) || {
      echo "failed to parse Cargo JSON artifact for $target_name" >&2
      return 65
    }
  [[ -n "$artifact" && "$artifact" != *$'\n'* && -f "$artifact" && -x "$artifact" ]] || {
    echo "Cargo JSON did not identify exactly one executable $target_kind artifact for $target_name" >&2
    return 65
  }
  local artifact_directory
  artifact_directory=$(cd "$("$dirname_bin" "$artifact")" && pwd -P)
  printf -v "$output_variable" '%s' "$artifact_directory/$("$basename_bin" "$artifact")"
}

assert_cargo_artifact_features() {
  local json_path=$1
  local target_name=$2
  local target_kind=$3
  local expected_features_json=$4
  "$jq_bin" -se \
    --arg target_name "$target_name" \
    --arg target_kind "$target_kind" \
    --argjson expected_features "$expected_features_json" \
    '[.[] | select(
      .reason == "compiler-artifact"
      and .target.name == $target_name
      and (.target.kind | index($target_kind)) != null
    )] as $artifacts
    | ($artifacts | length) > 0
      and all($artifacts[];
        (.features | sort_by(.)) == ($expected_features | sort_by(.))
      )' "$json_path" >/dev/null || {
    echo "Cargo JSON feature set disagreed for $target_name" >&2
    return 65
  }
}

agentd_build_json="$fixture_root/agentd-build.jsonl"
matrixd_build_json="$fixture_root/matrixd-build.jsonl"
test_build_json="$fixture_root/test-build.jsonl"
agentd_bin=''
matrixd_bin=''
test_bin=''
# Build the test in an isolated target first. Product binaries are built last in a different
# target and hashed immediately, so test-profile compilation cannot overwrite a claimed dev
# artifact through a shared path.
run_cargo_json "$test_build_json" "$test_build_target" \
  test --locked --offline --target "$target_triple" --profile test \
  -p codex-hepta-matrixd --features real-synapse-e2e \
  --test real_synapse_e2e --no-run
run_cargo_json "$agentd_build_json" "$product_build_target" \
  build --locked --offline --target "$target_triple" --profile dev \
  -p codex-hepta-agentd --bin codex-hepta-agentd
run_cargo_json "$matrixd_build_json" "$product_build_target" \
  build --locked --offline --target "$target_triple" --profile dev \
  -p codex-hepta-matrixd --features real-synapse-e2e --bin codex-hepta-matrixd
resolve_single_cargo_artifact "$agentd_build_json" codex-hepta-agentd bin false agentd_bin
resolve_single_cargo_artifact "$matrixd_build_json" codex-hepta-matrixd bin false matrixd_bin
resolve_single_cargo_artifact "$test_build_json" real_synapse_e2e test true test_bin
assert_cargo_artifact_features "$agentd_build_json" codex-hepta-agentd bin '[]'
assert_cargo_artifact_features \
  "$matrixd_build_json" codex-hepta-matrixd bin '["default", "real-synapse-e2e"]'
assert_cargo_artifact_features \
  "$matrixd_build_json" codex_hepta_matrix_sdk lib '["default", "qualification-failpoints"]'
assert_cargo_artifact_features \
  "$test_build_json" real_synapse_e2e test '["default", "real-synapse-e2e"]'
assert_cargo_artifact_features \
  "$test_build_json" codex_hepta_matrix_sdk lib '["default", "qualification-failpoints"]'

agentd_build_json_sha256=$(sha256_file "$agentd_build_json")
matrixd_build_json_sha256=$(sha256_file "$matrixd_build_json")
test_build_json_sha256=$(sha256_file "$test_build_json")
agentd_sha256=$(sha256_file "$agentd_bin")
matrixd_sha256=$(sha256_file "$matrixd_bin")
test_binary_sha256=$(sha256_file "$test_bin")
runner_sha256=$(sha256_file "$runner_path")
for fixture_digest in \
  "$agentd_build_json_sha256" \
  "$matrixd_build_json_sha256" \
  "$test_build_json_sha256" \
  "$rustc_command_sha256" \
  "$cargo_command_sha256" \
  "$agentd_sha256" \
  "$matrixd_sha256" \
  "$test_binary_sha256" \
  "$runner_sha256" \
  "$proxy_source_sha256"; do
  [[ "$fixture_digest" =~ ^[0-9a-f]{64}$ ]] || {
    echo 'candidate build artifact or provenance digest is invalid' >&2
    exit 65
  }
done
echo "R4_BUILD_BOUND agentd_sha256=$agentd_sha256 matrixd_sha256=$matrixd_sha256 test_sha256=$test_binary_sha256 runner_sha256=$runner_sha256 proxy_source_sha256=$proxy_source_sha256"

container_name="hepta-r4-synapse-$$-$RANDOM"
generate_container_name="$container_name-generate"
config_container_name="$container_name-config"
digest_container_name="$container_name-digest"
network_name="hepta-r4-internal-$$-$RANDOM"
volume_name="hepta-r4-data-$$-$RANDOM"
proxy_script="$fixture_root/synapse-loopback-proxy.py"
proxy_ready_file="$fixture_root/synapse-loopback-proxy-ready.json"
proxy_log="$fixture_root/synapse-loopback-proxy.log"
proxy_pid_file="$fixture_root/synapse-loopback-proxy.pid"
proxy_pid=''
proxy_port=''
proxy_ready_sha256=''
artifacts_dir=''
artifacts_final_dir=''
artifacts_parent_dir=''
artifacts_staging_dir=''
artifacts_quarantine_dir=''
release_copy_observation_count=0

durable_install_file() {
  local source_path=$1
  local destination_path=$2
  local expected_mode=$3
  "$python_bin" - "$source_path" "$destination_path" "$expected_mode" <<'PY' || return 74
import os
import pathlib
import shutil
import sys
import tempfile

source = pathlib.Path(sys.argv[1])
destination = pathlib.Path(sys.argv[2])
mode = int(sys.argv[3], 8)
if not source.is_file():
    raise SystemExit("durable source is not a file")
if destination.exists():
    raise SystemExit("refusing to overwrite durable evidence")
destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
try:
    with os.fdopen(fd, "wb") as output, source.open("rb") as input_file:
        shutil.copyfileobj(input_file, output)
        os.fchmod(output.fileno(), mode)
        output.flush()
        os.fsync(output.fileno())
    # Publish without an overwrite window. A concurrent or stale destination
    # must fail the qualification instead of being replaced.
    os.link(temporary, destination, follow_symlinks=False)
    os.unlink(temporary)
    directory_fd = os.open(destination.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
except BaseException:
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
    raise
PY
  [[ -f "$destination_path" ]] || return 74
  [[ "$("$stat_bin" -f '%Lp' "$destination_path")" == "$expected_mode" ]] || return 74
  [[ "$(sha256_file "$source_path")" == "$(sha256_file "$destination_path")" ]] || return 74
}

install_loopback_proxy_source() {
  [[ "$(sha256_file "$proxy_source_path")" == "$proxy_source_sha256" ]] || {
    echo 'loopback proxy source changed before launch' >&2
    return 65
  }
  durable_install_file "$proxy_source_path" "$proxy_script" 600 || return 74
  [[ "$(sha256_file "$proxy_script")" == "$proxy_source_sha256" ]] || {
    echo 'installed loopback proxy source digest disagreed with candidate' >&2
    return 65
  }
}

initialize_artifact_staging() {
  [[ -n "$artifacts_dir_arg" ]] || return 0
  local requested_parent
  local requested_name
  local staging_nonce
  requested_parent=$("$dirname_bin" "$artifacts_dir_arg")
  requested_name=$("$basename_bin" "$artifacts_dir_arg")
  [[ -n "$requested_name" && "$requested_name" != . && "$requested_name" != .. ]] || {
    echo 'artifact directory basename is invalid' >&2
    return 73
  }
  "$mkdir_bin" -p "$requested_parent"
  artifacts_parent_dir=$(cd "$requested_parent" && pwd -P)
  artifacts_final_dir="$artifacts_parent_dir/$requested_name"
  [[ ! -e "$artifacts_final_dir" && ! -L "$artifacts_final_dir" ]] || {
    echo 'formal artifact directory must not already exist' >&2
    return 73
  }
  staging_nonce=$("$openssl_bin" rand -hex 16)
  artifacts_staging_dir="$artifacts_parent_dir/.$requested_name.staging.$staging_nonce"
  "$python_bin" - "$artifacts_parent_dir" "$artifacts_staging_dir" <<'PY' || return 73
import os
import pathlib
import stat
import sys

parent = pathlib.Path(sys.argv[1])
staging = pathlib.Path(sys.argv[2])
parent_metadata = parent.lstat()
if not stat.S_ISDIR(parent_metadata.st_mode):
    raise SystemExit("artifact parent is not a physical directory")
os.mkdir(staging, 0o700)
staging_metadata = staging.lstat()
if not stat.S_ISDIR(staging_metadata.st_mode) or stat.S_IMODE(staging_metadata.st_mode) != 0o700:
    raise SystemExit("artifact staging is not a private physical directory")
parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
try:
    os.fsync(parent_fd)
finally:
    os.close(parent_fd)
PY
  artifacts_dir=$artifacts_staging_dir
}

publish_artifact_staging() {
  [[ -n "$artifacts_staging_dir" && "$artifacts_dir" == "$artifacts_staging_dir" ]] || return 73
  "$python_bin" - \
    "$artifacts_parent_dir" "$artifacts_staging_dir" "$artifacts_final_dir" <<'PY' || return 74
import ctypes
import os
import pathlib
import stat
import sys

parent = pathlib.Path(sys.argv[1])
staging = pathlib.Path(sys.argv[2])
final = pathlib.Path(sys.argv[3])
if staging.parent != parent or final.parent != parent:
    raise SystemExit("artifact staging/final directory escaped the bound parent")
if final.exists() or final.is_symlink():
    raise SystemExit("formal artifact directory appeared before atomic publication")
parent_metadata = parent.lstat()
staging_metadata = staging.lstat()
if not stat.S_ISDIR(parent_metadata.st_mode):
    raise SystemExit("artifact parent is not a physical directory")
if not stat.S_ISDIR(staging_metadata.st_mode) or stat.S_IMODE(staging_metadata.st_mode) != 0o700:
    raise SystemExit("artifact staging identity/mode drifted")
entries = list(os.scandir(staging))
if not entries:
    raise SystemExit("artifact staging directory is empty")
for entry in entries:
    metadata = entry.stat(follow_symlinks=False)
    if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise SystemExit(f"staged artifact is not a mode-0600 regular file: {entry.name}")
    if metadata.st_nlink != 1:
        raise SystemExit(f"staged artifact has unexpected hard links: {entry.name}")
    descriptor = os.open(entry.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise SystemExit(f"staged artifact changed during publication: {entry.name}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
staging_fd = os.open(staging, os.O_RDONLY | os.O_DIRECTORY)
parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
try:
    os.fsync(staging_fd)
    libc = ctypes.CDLL(None, use_errno=True)
    renamex_np = libc.renamex_np
    renamex_np.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    renamex_np.restype = ctypes.c_int
    if renamex_np(os.fsencode(staging), os.fsencode(final), 0x00000004) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(final))
    os.fsync(parent_fd)
finally:
    os.close(staging_fd)
    os.close(parent_fd)
final_metadata = final.lstat()
if not stat.S_ISDIR(final_metadata.st_mode) or stat.S_IMODE(final_metadata.st_mode) != 0o700:
    raise SystemExit("atomically published artifact directory identity/mode drifted")
PY
  artifacts_dir=$artifacts_final_dir
  artifacts_staging_dir=''
}

quarantine_artifact_staging() {
  local failure_code=$1
  [[ -n "$artifacts_staging_dir" && -d "$artifacts_staging_dir" ]] || return 0
  local quarantine_nonce
  quarantine_nonce=$("$openssl_bin" rand -hex 16) || return 74
  artifacts_quarantine_dir="$artifacts_parent_dir/.$("$basename_bin" "$artifacts_final_dir").quarantine.$quarantine_nonce"
  "$python_bin" - \
    "$artifacts_parent_dir" "$artifacts_staging_dir" "$artifacts_quarantine_dir" "$failure_code" <<'PY' || return 74
import ctypes
import json
import os
import pathlib
import sys

parent = pathlib.Path(sys.argv[1])
staging = pathlib.Path(sys.argv[2])
quarantine = pathlib.Path(sys.argv[3])
failure_code = int(sys.argv[4])
if staging.parent != parent or quarantine.parent != parent or quarantine.exists():
    raise SystemExit("artifact quarantine authority is invalid")
tombstone = staging / "FAILURE.json"
fd = os.open(tombstone, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "wb") as output:
    output.write(json.dumps({
        "schema_version": 1,
        "qualification_failed": True,
        "exit_code": failure_code,
        "promotable": False,
    }, separators=(",", ":"), sort_keys=True).encode())
    output.write(b"\n")
    output.flush()
    os.fsync(output.fileno())
staging_fd = os.open(staging, os.O_RDONLY | os.O_DIRECTORY)
parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
try:
    os.fsync(staging_fd)
    libc = ctypes.CDLL(None, use_errno=True)
    renamex_np = libc.renamex_np
    renamex_np.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    renamex_np.restype = ctypes.c_int
    if renamex_np(os.fsencode(staging), os.fsencode(quarantine), 0x00000004) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(quarantine))
    os.fsync(parent_fd)
finally:
    os.close(staging_fd)
    os.close(parent_fd)
PY
  artifacts_staging_dir=''
  artifacts_dir=''
}

write_artifact_set() {
  local evidence_directory=$1
  local output_path=$2
  "$python_bin" - "$evidence_directory" "$output_path" <<'PY'
import hashlib
import json
import os
import pathlib
import stat
import sys

root = pathlib.Path(sys.argv[1])
output_path = pathlib.Path(sys.argv[2])
names = [
    "synapse.log",
    "synapse-loopback-proxy.py",
    "synapse-loopback-proxy-ready.json",
    "synapse-loopback-proxy.log",
    "synapse-loopback-proxy.pid",
    "fixture-manifest.json",
    "test.log",
    "completion.json",
    "agentd-build.jsonl",
    "matrixd-build.jsonl",
    "test-build.jsonl",
    "cargo-dependency-seed-ledger.json",
    "host-tool-ledger.json",
    "rust-tool-ledger.json",
    "runner-control-tool-ledger.json",
    "runner-control-static-scan.json",
    "bash-version.txt",
    "process-identity-ledger.json",
    "apple-build-input-ledger.json",
    "xcodebuild-version.txt",
    "source-status.porcelain",
    "source-status.final.porcelain",
    "rustc-vv.txt",
    "rustc-vv.final.txt",
]
files = []
for name in names:
    path = root / name
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise SystemExit(f"artifact is not a mode-0600 regular file: {name}")
    files.append({
        "path": name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "mode": "0600",
        "bytes": metadata.st_size,
    })
payload = {
    "schema_version": 1,
    "authority": "run-hermetic-synapse.sh",
    "files": files,
}
if output_path.exists():
    raise SystemExit("artifact-set source already exists")
fd = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "wb") as output:
    output.write(json.dumps(payload, indent=2, sort_keys=True).encode("utf-8"))
    output.write(b"\n")
    output.flush()
    os.fsync(output.fileno())
PY
}

docker_names() {
  local resource_type=$1
  case "$resource_type" in
    container) "$docker_bin" container ls -a --format '{{.Names}}' ;;
    network) "$docker_bin" network ls --format '{{.Name}}' ;;
    volume) "$docker_bin" volume ls --format '{{.Name}}' ;;
    *) return 64 ;;
  esac
}

docker_resource_exists() {
  local resource_type=$1
  local resource_name=$2
  local names
  names=$(docker_names "$resource_type") || return 70
  while IFS= read -r candidate_name; do
    [[ "$candidate_name" == "$resource_name" ]] && return 0
  done <<<"$names"
  return 1
}

stop_loopback_proxy() {
  local stop_error=0
  local proxy_identity=''
  local proxy_wait_rc=0
  local wait_attempt=1
  local stopped_proxy_pid="$proxy_pid"
  if [[ -n "$proxy_pid" ]]; then
    [[ "$proxy_pid" =~ ^[0-9]+$ && "$proxy_pid" -gt 0 ]] || {
      echo 'loopback proxy PID is invalid' >&2
      stop_error=1
    }
    if ((stop_error == 0)); then
      proxy_identity=$("$ps_bin" -p "$proxy_pid" -o command= 2>/dev/null || true)
      if [[ -n "$proxy_identity" && "$proxy_identity" != *"$proxy_script"* ]]; then
        echo 'loopback proxy PID identity changed before shutdown' >&2
        stop_error=1
      fi
    fi
    if ((stop_error == 0)); then
      set +e
      "$kill_bin" -TERM "$proxy_pid" >/dev/null 2>&1
      set -e
      while ((wait_attempt <= 120)); do
        set +e
        "$kill_bin" -0 "$proxy_pid" >/dev/null 2>&1
        local kill_rc=$?
        set -e
        ((kill_rc != 0)) && break
        "$sleep_bin" 0.1
        ((wait_attempt += 1))
      done
      set +e
      "$kill_bin" -0 "$proxy_pid" >/dev/null 2>&1
      kill_rc=$?
      set -e
      if ((kill_rc == 0)); then
        echo 'loopback proxy survived graceful shutdown; forcing termination' >&2
        set +e
        "$kill_bin" -KILL "$proxy_pid" >/dev/null 2>&1
        wait "$proxy_pid"
        proxy_wait_rc=$?
        set -e
        stop_error=1
      else
        set +e
        wait "$proxy_pid"
        proxy_wait_rc=$?
        set -e
        if ((proxy_wait_rc != 0)); then
          echo "loopback proxy exited with status $proxy_wait_rc" >&2
          stop_error=1
        fi
      fi
      proxy_identity=$("$ps_bin" -p "$proxy_pid" -o pid= 2>/dev/null || true)
      if [[ -n "${proxy_identity//[[:space:]]/}" ]]; then
        echo 'loopback proxy PID remained visible after shutdown' >&2
        stop_error=1
      fi
    fi
    proxy_pid=''
  fi
  if [[ -f "$proxy_pid_file" ]]; then
    [[ "$("$stat_bin" -f '%Lp' "$proxy_pid_file")" == 600 ]] || {
      echo 'loopback proxy PID evidence has unsafe mode' >&2
      stop_error=1
    }
    if [[ -n "$stopped_proxy_pid" ]] \
      && [[ "$("$tr_bin" -d '\r\n' <"$proxy_pid_file")" != "$stopped_proxy_pid" ]]; then
      echo 'loopback proxy PID evidence changed before shutdown' >&2
      stop_error=1
    fi
  fi
  return "$stop_error"
}

cleanup_fixture() {
  local fixture_rc=$1
  local cleanup_error=0
  local fixture_container_name
  local synapse_log="$fixture_root/synapse.log"
  local artifact_set_source="$fixture_root/artifact-set.generated.json"
  trap - EXIT INT TERM

  if ! stop_loopback_proxy; then
    echo 'failed to prove loopback proxy shutdown' >&2
    cleanup_error=1
  fi

  if docker_resource_exists container "$container_name"; then
    if [[ -n "$artifacts_dir" ]]; then
      if ! "$docker_bin" logs "$container_name" >"$synapse_log" 2>&1; then
        echo 'failed to capture Synapse logs before cleanup' >&2
        cleanup_error=1
      fi
    fi
  elif [[ $? -ne 1 ]]; then
    echo 'failed to enumerate Docker containers during cleanup' >&2
    cleanup_error=1
  fi

  for fixture_container_name in \
    "$container_name" \
    "$generate_container_name" \
    "$config_container_name" \
    "$digest_container_name"; do
    if docker_resource_exists container "$fixture_container_name"; then
      if ! "$docker_bin" rm -f "$fixture_container_name" >/dev/null; then
        echo "failed to remove fixture container $fixture_container_name" >&2
        cleanup_error=1
      fi
    elif [[ $? -ne 1 ]]; then
      echo 'failed to enumerate Docker containers during cleanup' >&2
      cleanup_error=1
    fi
    if docker_resource_exists container "$fixture_container_name"; then
      echo "fixture container survived cleanup: $fixture_container_name" >&2
      cleanup_error=1
    elif [[ $? -ne 1 ]]; then
      echo 'failed to verify Docker container cleanup' >&2
      cleanup_error=1
    fi
  done

  if docker_resource_exists network "$network_name"; then
    if ! "$docker_bin" network rm "$network_name" >/dev/null; then
      echo "failed to remove fixture network $network_name" >&2
      cleanup_error=1
    fi
  elif [[ $? -ne 1 ]]; then
    echo 'failed to enumerate Docker networks during cleanup' >&2
    cleanup_error=1
  fi
  if docker_resource_exists network "$network_name"; then
    echo "fixture network survived cleanup: $network_name" >&2
    cleanup_error=1
  elif [[ $? -ne 1 ]]; then
    echo 'failed to verify Docker network cleanup' >&2
    cleanup_error=1
  fi

  if docker_resource_exists volume "$volume_name"; then
    if ! "$docker_bin" volume rm "$volume_name" >/dev/null; then
      echo "failed to remove fixture volume $volume_name" >&2
      cleanup_error=1
    fi
  elif [[ $? -ne 1 ]]; then
    echo 'failed to enumerate Docker volumes during cleanup' >&2
    cleanup_error=1
  fi
  if docker_resource_exists volume "$volume_name"; then
    echo "fixture volume survived cleanup: $volume_name" >&2
    cleanup_error=1
  elif [[ $? -ne 1 ]]; then
    echo 'failed to verify Docker volume cleanup' >&2
    cleanup_error=1
  fi

  if ((fixture_rc == 0)); then
    if [[ -e "$credentials_directory" ]]; then
      echo 'qualification capability directory survived the product test' >&2
      cleanup_error=1
    fi
    if [[ ! -d "$runtime_tmp_root" \
      || -n "$("$find_bin" "$runtime_tmp_root" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
      echo 'qualification runtime root was not explicitly emptied' >&2
      cleanup_error=1
    fi
    if ((cleanup_error == 0)) && ! verify_final_provenance; then
      echo 'post-cleanup candidate provenance revalidation failed' >&2
      cleanup_error=1
    fi
  fi

  # No durable artifact leaves the private fixture root until every runner
  # control executable and every source/build/SDK authority has been
  # re-resolved and byte-revalidated after product and Docker teardown.
  if ((fixture_rc == 0 && cleanup_error == 0)); then
    if ! verify_publication_provenance; then
      echo 'final publication provenance revalidation failed' >&2
      cleanup_error=1
    fi
  fi

  if [[ -n "$artifacts_dir" && $fixture_rc -eq 0 && $cleanup_error -eq 0 ]]; then
    if [[ ! -f "$synapse_log" ]]; then
      echo 'successful qualification omitted the Synapse log' >&2
      cleanup_error=1
    elif ! durable_install_file "$synapse_log" "$artifacts_dir/synapse.log" 600; then
      echo 'failed to persist Synapse logs durably' >&2
      cleanup_error=1
    fi
  fi
  if [[ -n "$artifacts_dir" && $fixture_rc -eq 0 && $cleanup_error -eq 0 ]]; then
    for proxy_artifact in \
      synapse-loopback-proxy.py \
      synapse-loopback-proxy-ready.json \
      synapse-loopback-proxy.log \
      synapse-loopback-proxy.pid; do
      if [[ ! -f "$fixture_root/$proxy_artifact" ]] \
        || [[ "$("$stat_bin" -f '%Lp' "$fixture_root/$proxy_artifact")" != 600 ]]; then
        echo "successful qualification omitted or weakened proxy evidence: $proxy_artifact" >&2
        cleanup_error=1
      elif ! durable_install_file \
        "$fixture_root/$proxy_artifact" "$artifacts_dir/$proxy_artifact" 600; then
        echo "failed to persist proxy evidence $proxy_artifact durably" >&2
        cleanup_error=1
      fi
    done
  fi

  if [[ -n "$artifacts_dir" && $fixture_rc -eq 0 && $cleanup_error -eq 0 \
    && -f "$fixture_manifest" ]]; then
    if ! "$jq_bin" -e \
      'has("agent_a_password") == false
        and has("agent_b_password") == false
        and has("human_password") == false' \
      "$fixture_manifest" >/dev/null; then
      echo 'credential-free fixture manifest unexpectedly contains a password' >&2
      cleanup_error=1
    elif ! durable_install_file \
      "$fixture_manifest" "$artifacts_dir/fixture-manifest.json" 600; then
      echo 'failed to persist the credential-free fixture manifest durably' >&2
      cleanup_error=1
    fi
  elif [[ -n "$artifacts_dir" && $fixture_rc -eq 0 && $cleanup_error -eq 0 ]]; then
    echo 'successful qualification omitted the fixture manifest' >&2
    cleanup_error=1
  fi
  if [[ -n "$artifacts_dir" && $fixture_rc -eq 0 && $cleanup_error -eq 0 \
    && -f "$fixture_root/test.log" ]]; then
    if ! durable_install_file "$fixture_root/test.log" "$artifacts_dir/test.log" 600; then
      echo 'failed to persist the qualification log durably' >&2
      cleanup_error=1
    fi
  elif [[ -n "$artifacts_dir" && $fixture_rc -eq 0 && $cleanup_error -eq 0 ]]; then
    echo 'successful qualification omitted the test log' >&2
    cleanup_error=1
  fi
  if [[ -n "$artifacts_dir" && $fixture_rc -eq 0 && $cleanup_error -eq 0 \
    && -f "$fixture_root/completion/completion.json" ]]; then
    if ! durable_install_file \
      "$fixture_root/completion/completion.json" "$artifacts_dir/completion.json" 600; then
      echo 'failed to persist the completion receipt durably' >&2
      cleanup_error=1
    fi
  elif [[ -n "$artifacts_dir" && $fixture_rc -eq 0 && $cleanup_error -eq 0 ]]; then
    echo 'successful qualification omitted the completion receipt' >&2
    cleanup_error=1
  fi
  if [[ -n "$artifacts_dir" && $fixture_rc -eq 0 && $cleanup_error -eq 0 ]]; then
    for evidence_name in \
      agentd-build.jsonl \
      matrixd-build.jsonl \
      test-build.jsonl \
      cargo-dependency-seed-ledger.json \
      host-tool-ledger.json \
      rust-tool-ledger.json \
      runner-control-tool-ledger.json \
      runner-control-static-scan.json \
      bash-version.txt \
      process-identity-ledger.json \
      apple-build-input-ledger.json \
      xcodebuild-version.txt \
      source-status.porcelain \
      source-status.final.porcelain \
      rustc-vv.txt \
      rustc-vv.final.txt; do
      if [[ -f "$fixture_root/$evidence_name" ]]; then
        if ! durable_install_file \
          "$fixture_root/$evidence_name" "$artifacts_dir/$evidence_name" 600; then
          echo "failed to persist qualification evidence $evidence_name durably" >&2
          cleanup_error=1
        fi
      else
        echo "successful qualification omitted evidence $evidence_name" >&2
        cleanup_error=1
      fi
    done
  fi

  local runner_evidence_source=''
  if [[ -n "$artifacts_dir" && $fixture_rc -eq 0 && $cleanup_error -eq 0 ]]; then
    for required_artifact in \
      synapse.log \
      synapse-loopback-proxy.py \
      synapse-loopback-proxy-ready.json \
      synapse-loopback-proxy.log \
      synapse-loopback-proxy.pid \
      fixture-manifest.json \
      test.log \
      completion.json \
      agentd-build.jsonl \
      matrixd-build.jsonl \
      test-build.jsonl \
      cargo-dependency-seed-ledger.json \
      host-tool-ledger.json \
      rust-tool-ledger.json \
      runner-control-tool-ledger.json \
      runner-control-static-scan.json \
      bash-version.txt \
      process-identity-ledger.json \
      apple-build-input-ledger.json \
      xcodebuild-version.txt \
      source-status.porcelain \
      source-status.final.porcelain \
      rustc-vv.txt \
      rustc-vv.final.txt; do
      if [[ ! -f "$artifacts_dir/$required_artifact" \
        || "$("$stat_bin" -f '%Lp' "$artifacts_dir/$required_artifact")" != 600 ]]; then
        echo "durable qualification artifact is missing or has unsafe mode: $required_artifact" >&2
        cleanup_error=1
      fi
    done
  fi
  if [[ -n "$artifacts_dir" && $fixture_rc -eq 0 && $cleanup_error -eq 0 ]]; then
    if ! write_artifact_set "$artifacts_dir" "$artifact_set_source"; then
      echo 'failed to generate the qualification artifact-set manifest' >&2
      cleanup_error=1
    elif ! durable_install_file \
      "$artifact_set_source" "$artifacts_dir/artifact-set.json" 600; then
      echo 'failed to persist the qualification artifact-set manifest' >&2
      cleanup_error=1
    fi
  fi
  if [[ -n "$artifacts_dir" && $fixture_rc -eq 0 && $cleanup_error -eq 0 ]]; then
    runner_evidence_source="$artifacts_dir/.runner-evidence.generated.json"
    exact_candidate_evidence=false
    [[ "$source_mode" == "$EXACT_SOURCE_MODE" ]] && exact_candidate_evidence=true
    if ! "$jq_bin" -n \
      --arg qualification_mode "$source_mode" \
      --arg candidate_sha "$candidate_sha" \
      --arg candidate_tree_sha "$candidate_tree_sha" \
      --arg fixture_manifest_sha256 "$fixture_manifest_sha256" \
      --arg artifact_set_sha256 "$(sha256_file "$artifacts_dir/artifact-set.json")" \
      --arg completion_sha256 "$(sha256_file "$artifacts_dir/completion.json")" \
      --arg test_log_sha256 "$(sha256_file "$artifacts_dir/test.log")" \
      --arg synapse_log_sha256 "$(sha256_file "$artifacts_dir/synapse.log")" \
      --arg synapse_transport "docker-exec-loopback-proxy-v1" \
      --arg synapse_proxy_source_sha256 "$proxy_source_sha256" \
      --arg synapse_proxy_ready_sha256 "$proxy_ready_sha256" \
      --arg agentd_sha256 "$agentd_sha256" \
      --arg matrixd_sha256 "$matrixd_sha256" \
      --arg test_binary_sha256 "$test_binary_sha256" \
      --arg runner_sha256 "$runner_sha256" \
      --arg cargo_seed_ledger_sha256 "$cargo_seed_manifest_sha256" \
      --arg host_tool_ledger_sha256 "$host_tool_ledger_sha256" \
      --arg rust_tool_ledger_sha256 "$rust_tool_ledger_sha256" \
      --arg runner_control_tool_ledger_sha256 "$runner_control_tool_ledger_sha256" \
      --arg runner_control_static_scan_sha256 "$runner_control_static_scan_sha256" \
      --arg bash_command_sha256 "$bash_command_sha256" \
      --arg bash_version_sha256 "$bash_version_sha256" \
      --arg process_identity_ledger_sha256 "$(sha256_file "$process_identity_ledger")" \
      --arg apple_build_input_ledger_sha256 "$apple_build_input_ledger_sha256" \
      --argjson release_copy_observation_count "$release_copy_observation_count" \
      --argjson exact_candidate_evidence "$exact_candidate_evidence" \
      '{
        schema_version: 3,
        authority: "run-hermetic-synapse.sh",
        qualification_mode: $qualification_mode,
        candidate_sha: $candidate_sha,
        candidate_tree_sha: $candidate_tree_sha,
        fixture_manifest_sha256: $fixture_manifest_sha256,
        artifact_set_sha256: $artifact_set_sha256,
        completion_sha256: $completion_sha256,
        test_log_sha256: $test_log_sha256,
        synapse_log_sha256: $synapse_log_sha256,
        synapse_transport: $synapse_transport,
        synapse_proxy_source_sha256: $synapse_proxy_source_sha256,
        synapse_proxy_ready_sha256: $synapse_proxy_ready_sha256,
        agentd_sha256: $agentd_sha256,
        matrixd_sha256: $matrixd_sha256,
        test_binary_sha256: $test_binary_sha256,
        runner_sha256: $runner_sha256,
        cargo_dependency_seed_ledger_sha256: $cargo_seed_ledger_sha256,
        host_tool_ledger_sha256: $host_tool_ledger_sha256,
        rust_tool_ledger_sha256: $rust_tool_ledger_sha256,
        runner_control_tool_ledger_sha256: $runner_control_tool_ledger_sha256,
        runner_control_static_scan_sha256: $runner_control_static_scan_sha256,
        bash_command_sha256: $bash_command_sha256,
        bash_version_sha256: $bash_version_sha256,
        process_identity_ledger_sha256: $process_identity_ledger_sha256,
        explicit_process_shutdown_completed: true,
        all_historical_product_pids_absent: true,
        loopback_proxy_shutdown_completed: true,
        loopback_proxy_pid_absent: true,
        runner_control_static_scan_passed: true,
        apple_build_input_ledger_sha256: $apple_build_input_ledger_sha256,
        release_copy_observation_count: $release_copy_observation_count,
        release_copy_identity_rechecked_at_lifecycle_boundaries: true,
        release_execve_atomic_binding: false,
        exact_candidate_evidence: $exact_candidate_evidence,
        test_assertions_passed: true,
        docker_resources_removed: true,
        runtime_root_removed: true,
        credential_capabilities_removed: true,
        private_fixture_root_removed: true,
        durable_artifacts_verified: true,
        promotion: false,
        operator_acceptance: false
      }' >"$runner_evidence_source"; then
      echo 'failed to prepare final runner evidence' >&2
      cleanup_error=1
    else
      "$chmod_bin" 600 "$runner_evidence_source"
    fi
  fi

  case "$fixture_root" in
    "$fixture_tmp_base"/r4.*)
      if ! make_runtime_tree_removable "$runtime_tmp_root"; then
        echo 'failed to make the private runtime tree removable' >&2
        cleanup_error=1
      fi
      if ! "$rm_bin" -rf -- "$fixture_root" || [[ -e "$fixture_root" ]]; then
        echo 'failed to remove the qualification fixture root' >&2
        cleanup_error=1
      fi
      ;;
    *)
      echo 'refusing to remove unexpected fixture directory' >&2
      cleanup_error=1
      ;;
  esac
  if [[ -n "$runner_evidence_source" && $fixture_rc -eq 0 && $cleanup_error -eq 0 ]]; then
    if ! durable_install_file \
      "$runner_evidence_source" "$artifacts_dir/runner-evidence.json" 600; then
      echo 'failed to publish final runner evidence durably' >&2
      cleanup_error=1
    else
      "$rm_bin" -f -- "$runner_evidence_source"
      if ! publish_artifact_staging; then
        echo 'failed to atomically publish the complete qualification evidence directory' >&2
        cleanup_error=1
      else
        echo "R4_DYNAMIC_EVIDENCE qualification_mode=$source_mode exact_candidate_evidence=$([[ "$source_mode" == "$EXACT_SOURCE_MODE" ]] && echo PASS || echo FAIL_CLOSED) candidate_sha=$candidate_sha candidate_tree_sha=$candidate_tree_sha artifact_set_sha256=$(sha256_file "$artifacts_final_dir/artifact-set.json") runner_evidence_sha256=$(sha256_file "$artifacts_final_dir/runner-evidence.json") promotion=false operator_acceptance=false"
      fi
    fi
  elif [[ -n "$runner_evidence_source" ]]; then
    "$rm_bin" -f -- "$runner_evidence_source"
  fi
  if ((cleanup_error != 0 && fixture_rc == 0)); then
    fixture_rc=74
  fi
  if [[ -n "$artifacts_staging_dir" && -d "$artifacts_staging_dir" ]]; then
    if ! quarantine_artifact_staging "$fixture_rc"; then
      echo 'failed to quarantine incomplete qualification evidence staging' >&2
      ((fixture_rc == 0)) && fixture_rc=74
    fi
  fi
  exit "$fixture_rc"
}
trap 'cleanup_fixture $?' EXIT
trap 'cleanup_fixture 130' INT
trap 'cleanup_fixture 143' TERM
initialize_artifact_staging

docker_start_container() {
  local fixture_container_name=$1
  "$docker_bin" start "$fixture_container_name" >/dev/null
}

docker_wait_success() {
  local fixture_container_name=$1
  local container_state=''
  local container_exit_code=''
  local _wait_attempt=1
  while ((_wait_attempt <= 300)); do
    container_state=$("$docker_bin" container inspect \
      --format '{{.State.Status}}' "$fixture_container_name")
    if [[ "$container_state" == exited || "$container_state" == dead ]]; then
      container_exit_code=$("$docker_bin" container inspect \
        --format '{{.State.ExitCode}}' "$fixture_container_name")
      [[ "$container_state" == exited && "$container_exit_code" == 0 ]] || {
        "$docker_bin" logs "$fixture_container_name" >&2 || true
        echo "$fixture_container_name failed with state=$container_state exit=$container_exit_code" >&2
        return 70
      }
      return 0
    fi
    "$sleep_bin" 0.1
    ((_wait_attempt += 1))
  done
  echo "$fixture_container_name did not stop before the bounded deadline" >&2
  return 70
}

assert_internal_synapse_transport() {
  "$jq_bin" -e \
    --arg network_name "$network_name" \
    --arg container_name "$container_name" \
    'length == 1
      and .[0].Name == $network_name
      and .[0].Driver == "bridge"
      and .[0].Internal == true
      and ([.[0].Containers[].Name] | sort_by(.)) == [$container_name]' \
    <("$docker_bin" network inspect "$network_name") >/dev/null || {
      echo 'Synapse Docker network is not the expected internal bridge' >&2
      return 65
    }
  "$jq_bin" -e \
    --arg network_name "$network_name" \
    '(.[0]
      | (.HostConfig.NetworkMode == $network_name)
      and ((.HostConfig.PortBindings // {}) == {})
      and all((.NetworkSettings.Ports // {})[]?;
        . == null or (type == "array" and length == 0))
      and ((.NetworkSettings.Networks | keys) == [$network_name]))' \
    <("$docker_bin" container inspect "$container_name") >/dev/null || {
      echo 'Synapse container has an unexpected network or published port' >&2
      return 65
    }
}

start_loopback_proxy() {
  install_loopback_proxy_source || return $?
  "$rm_bin" -f -- "$proxy_ready_file" "$proxy_pid_file" "$proxy_log"
  "$python_bin" "$proxy_script" \
    --docker "$docker_bin" \
    --container "$container_name" \
    --ready "$proxy_ready_file" \
    >"$proxy_log" 2>&1 &
  proxy_pid=$!
  printf '%s\n' "$proxy_pid" >"$proxy_pid_file"
  "$chmod_bin" 600 "$proxy_pid_file"
  [[ "$proxy_pid" =~ ^[0-9]+$ && "$proxy_pid" -gt 0 ]] || {
    echo 'loopback proxy did not produce a valid PID' >&2
    return 70
  }
  [[ "$("$tr_bin" -d '\r\n' <"$proxy_pid_file")" == "$proxy_pid" ]] || {
    echo 'loopback proxy PID evidence did not bind to the launched process' >&2
    return 65
  }
  local proxy_identity=''
  proxy_identity=$("$ps_bin" -p "$proxy_pid" -o command= 2>/dev/null || true)
  [[ "$proxy_identity" == *"$proxy_script"* ]] || {
    echo 'loopback proxy PID identity did not bind to the checked-in source' >&2
    return 65
  }
  local wait_attempt=1
  while ((wait_attempt <= 120)); do
    if [[ -f "$proxy_ready_file" ]]; then
      break
    fi
    set +e
    "$kill_bin" -0 "$proxy_pid" >/dev/null 2>&1
    local kill_rc=$?
    set -e
    ((kill_rc != 0)) && {
      echo 'loopback proxy exited before publishing its ready file' >&2
      return 70
    }
    "$sleep_bin" 0.1
    ((wait_attempt += 1))
  done
  [[ -f "$proxy_ready_file" ]] || {
    echo 'loopback proxy did not publish its ready file before the bounded deadline' >&2
    return 70
  }
  "$jq_bin" -e \
    --arg transport 'docker-exec-loopback-proxy-v1' \
    --arg container_name "$container_name" \
    --argjson proxy_pid "$proxy_pid" \
    '.schema_version == 1
      and .transport == $transport
      and .host == "127.0.0.1"
      and .container == $container_name
      and .target == "127.0.0.1:8008"
      and .pid == $proxy_pid
      and (.port | type == "number" and . >= 1024 and . <= 65535)' \
    "$proxy_ready_file" >/dev/null || {
      echo 'loopback proxy ready evidence failed closed validation' >&2
      return 65
    }
  proxy_port=$("$jq_bin" -er '.port | select(type == "number" and . >= 1024 and . <= 65535)' "$proxy_ready_file") || return 65
  proxy_ready_sha256=$(sha256_file "$proxy_ready_file")
  [[ "$("$stat_bin" -f '%Lp' "$proxy_ready_file")" == 600 \
    && "$("$stat_bin" -f '%Lp' "$proxy_log")" == 600 \
    && "$("$stat_bin" -f '%Lp' "$proxy_pid_file")" == 600 ]] || {
    echo 'loopback proxy evidence file mode is not 0600' >&2
    return 65
  }
  [[ "$proxy_source_sha256" == "$(sha256_file "$proxy_script")" ]] || {
    echo 'loopback proxy source digest changed after launch' >&2
    return 65
  }
}

"$docker_bin" version >/dev/null
image_id=$("$docker_bin" image inspect --format '{{.Id}}' "$PINNED_SYNAPSE_IMAGE") || {
  echo 'pinned Synapse image is not materialized locally; qualification forbids pull' >&2
  exit 69
}
[[ "$image_id" == "$PINNED_IMAGE_ID" ]] || {
  echo 'materialized Synapse image ID does not match the qualified platform image' >&2
  exit 65
}
image_version=$("$docker_bin" image inspect \
  --format '{{index .Config.Labels "org.opencontainers.image.version"}}' \
  "$PINNED_SYNAPSE_IMAGE")
image_git_sha=$("$docker_bin" image inspect \
  --format '{{index .Config.Labels "gitsha1"}}' \
  "$PINNED_SYNAPSE_IMAGE")
[[ "$image_version" == "$PINNED_SYNAPSE_VERSION" ]] || {
  echo 'Synapse OCI version label mismatch' >&2
  exit 65
}
[[ "$image_git_sha" == "$PINNED_SYNAPSE_GIT_SHA" ]] || {
  echo 'Synapse OCI revision label mismatch' >&2
  exit 65
}

echo "R4_FIXTURE image_ref=$PINNED_SYNAPSE_IMAGE image_id=$image_id version=$image_version git_sha=$image_git_sha"
"$docker_bin" volume create "$volume_name" >/dev/null
"$docker_bin" create --pull=never --network none \
  --name "$generate_container_name" \
  -e SYNAPSE_SERVER_NAME=localhost \
  -e SYNAPSE_REPORT_STATS=no \
  -v "$volume_name:/data" \
  "$PINNED_SYNAPSE_IMAGE" generate >/dev/null
docker_start_container "$generate_container_name"
docker_wait_success "$generate_container_name"
"$docker_bin" rm "$generate_container_name" >/dev/null

"$docker_bin" create --pull=never --network none \
  --name "$config_container_name" \
  --entrypoint python3 \
  -v "$volume_name:/data" \
  "$PINNED_SYNAPSE_IMAGE" -c '
import pathlib, yaml
config_path = pathlib.Path("/data/homeserver.yaml")
config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
assert config.get("registration_shared_secret")
config.update({
    "allow_public_rooms_over_federation": False,
    "allow_public_rooms_without_auth": False,
    "enable_metrics": False,
    "enable_registration": False,
    "enable_registration_without_verification": False,
    "federation_domain_whitelist": {},
    "report_stats": False,
    "suppress_key_server_warning": True,
    "trusted_key_servers": [],
})
config_path.write_text(yaml.safe_dump(config, sort_keys=True), encoding="utf-8")
' >/dev/null
docker_start_container "$config_container_name"
docker_wait_success "$config_container_name"
"$docker_bin" rm "$config_container_name" >/dev/null

"$docker_bin" create --pull=never --network none \
  --name "$digest_container_name" \
  --entrypoint python3 \
  -v "$volume_name:/data:ro" \
  "$PINNED_SYNAPSE_IMAGE" -c '
import hashlib, pathlib
print(hashlib.sha256(pathlib.Path("/data/homeserver.yaml").read_bytes()).hexdigest())
' >/dev/null
docker_start_container "$digest_container_name"
docker_wait_success "$digest_container_name"
config_sha256=$("$docker_bin" logs "$digest_container_name" 2>/dev/null | "$tr_bin" -d '\r\n')
[[ "$config_sha256" =~ ^[0-9a-f]{64}$ ]] || {
  echo 'generated Synapse config digest is invalid' >&2
  exit 65
}
"$docker_bin" rm "$digest_container_name" >/dev/null
"$docker_bin" network create --internal "$network_name" >/dev/null
"$docker_bin" create --pull=never \
  --name "$container_name" \
  --network "$network_name" \
  --security-opt no-new-privileges \
  -v "$volume_name:/data" \
  "$PINNED_SYNAPSE_IMAGE" >/dev/null
docker_start_container "$container_name"
assert_internal_synapse_transport
start_loopback_proxy
fixture_port=$proxy_port
_attempt=1
while ((_attempt <= 120)); do
  if "$curl_bin" --fail --silent --show-error \
    "http://127.0.0.1:$fixture_port/_matrix/client/versions" >/dev/null 2>&1; then
    break
  fi
  "$sleep_bin" 0.25
  ((_attempt += 1))
done
"$curl_bin" --fail --silent --show-error \
  "http://127.0.0.1:$fixture_port/_matrix/client/versions" >/dev/null || {
  echo 'Synapse did not become ready through the loopback proxy before the bounded deadline' >&2
  exit 70
}

human_password=$("$openssl_bin" rand -hex 32)
agent_a_password=$("$openssl_bin" rand -hex 32)
agent_b_password=$("$openssl_bin" rand -hex 32)
write_secret_capability() {
  local destination_path=$1
  local secret_value=$2
  [[ "$destination_path" == "$credentials_directory"/* ]] || return 65
  [[ ! -e "$destination_path" ]] || return 65
  printf '%s\n' "$secret_value" >"$destination_path"
  "$chmod_bin" 600 "$destination_path"
}
write_secret_capability "$credentials_directory/human-password" "$human_password"
write_secret_capability "$credentials_directory/agent-a-password" "$agent_a_password"
write_secret_capability "$credentials_directory/agent-b-password" "$agent_b_password"
register_user() {
  local registration_user=$1
  local registration_password=$2
  # The inner shell intentionally expands its own private password-file
  # variable; no credential is placed in docker exec's argv.
  # shellcheck disable=SC2016
  # RUNNER_CONTROL_SCAN_SKIP_BEGIN: commands execute inside the pinned OCI image.
  printf '%s\n' "$registration_password" | \
    "$docker_bin" exec -i "$container_name" sh -ceu '
      for image_tool in chmod cat mktemp register_new_matrix_user rm; do
        command -v "$image_tool" >/dev/null
      done
      chmod_command=$(command -v chmod)
      password_file=$(mktemp)
      trap '\''rm -f -- "$password_file"'\'' EXIT
      "$chmod_command" 600 "$password_file"
      cat >"$password_file"
      register_new_matrix_user \
        --config /data/homeserver.yaml \
        --user "$1" \
        --password-file "$password_file" \
        --no-admin \
        http://127.0.0.1:8008
    ' sh "$registration_user" >"$fixture_root/register-$registration_user.log" 2>&1
  # RUNNER_CONTROL_SCAN_SKIP_END
}
register_user hepta-human "$human_password"
register_user hepta-agent-a "$agent_a_password"
register_user hepta-agent-b "$agent_b_password"

runtime_synapse_version=$("$docker_bin" exec "$container_name" python3 -c \
  'import importlib.metadata; print(importlib.metadata.version("matrix-synapse"))')
[[ "$runtime_synapse_version" == "$PINNED_SYNAPSE_VERSION" ]] || {
  echo 'running Synapse package version mismatch' >&2
  exit 65
}

generated_manifest="$fixture_root/fixture-manifest.generated.json"
"$jq_bin" -n \
  --arg qualification_mode "$source_mode" \
  --arg source_root "$source_root" \
  --arg candidate_sha "$candidate_sha" \
  --arg candidate_tree_sha "$candidate_tree_sha" \
  --arg source_status_sha256 "$source_status_sha256" \
  --arg cargo_lock_sha256 "$cargo_lock_sha256" \
  --arg workspace_manifest_sha256 "$workspace_manifest_sha256" \
  --arg cargo_config_sha256 "$cargo_config_sha256" \
  --arg agentd_manifest_sha256 "$agentd_manifest_sha256" \
  --arg matrixd_manifest_sha256 "$matrixd_manifest_sha256" \
  --arg matrix_sdk_manifest_sha256 "$matrix_sdk_manifest_sha256" \
  --arg rust_toolchain_manifest_sha256 "$rust_toolchain_manifest_sha256" \
  --arg rust_toolchain_channel "$rust_toolchain_channel" \
  --arg rustc_release "$rustc_release" \
  --arg rustc_commit "$rustc_commit" \
  --arg rustc_host "$rustc_host" \
  --arg target_triple "$target_triple" \
  --arg rustc_command "$rustc_command" \
  --arg cargo_command "$cargo_command" \
  --arg rustdoc_command "$rustdoc_command" \
  --arg rustc_command_sha256 "$rustc_command_sha256" \
  --arg cargo_command_sha256 "$cargo_command_sha256" \
  --arg rustdoc_command_sha256 "$rustdoc_command_sha256" \
  --arg rustc_verbose_sha256 "$rustc_verbose_sha256" \
  --arg cargo_version "$cargo_version" \
  --arg qualification_cargo_home "$qualification_cargo_home" \
  --arg cargo_seed_ledger "$cargo_seed_ledger" \
  --arg cargo_seed_manifest_sha256 "$cargo_seed_manifest_sha256" \
  --argjson cargo_seed_file_count "$cargo_seed_file_count" \
  --argjson cargo_git_database_count "$cargo_git_database_count" \
  --arg product_build_target "$product_build_target" \
  --arg test_build_target "$test_build_target" \
  --arg build_path "$build_path" \
  --arg rust_tool_bin "$rust_tool_bin" \
  --arg rust_tool_ledger "$rust_tool_ledger" \
  --arg rust_tool_ledger_sha256 "$rust_tool_ledger_sha256" \
  --arg host_tool_bin "$host_tool_bin" \
  --arg host_tool_ledger "$host_tool_ledger" \
  --arg host_tool_ledger_sha256 "$host_tool_ledger_sha256" \
  --arg runner_control_tool_ledger "$runner_control_tool_ledger" \
  --arg runner_control_tool_ledger_sha256 "$runner_control_tool_ledger_sha256" \
  --arg runner_control_static_scan "$runner_control_static_scan" \
  --arg runner_control_static_scan_sha256 "$runner_control_static_scan_sha256" \
  --arg bash_command "$bash_bin" \
  --arg bash_command_sha256 "$bash_command_sha256" \
  --arg bash_version "$bash_version" \
  --arg bash_version_file "$bash_version_file" \
  --arg bash_version_sha256 "$bash_version_sha256" \
  --arg process_identity_ledger "$process_identity_ledger" \
  --arg target_linker_environment_key "$target_linker_environment_key" \
  --arg xcrun_command "$xcrun_command" \
  --arg xcrun_command_sha256 "$xcrun_command_sha256" \
  --arg xcodebuild_command "$xcodebuild_command" \
  --arg xcodebuild_command_sha256 "$xcodebuild_command_sha256" \
  --arg xcodebuild_version_file "$xcodebuild_version_file" \
  --arg xcodebuild_version_sha256 "$xcodebuild_version_sha256" \
  --arg clang_command "$clang_command" \
  --arg clang_command_sha256 "$clang_command_sha256" \
  --arg clangxx_command "$clangxx_command" \
  --arg clangxx_command_sha256 "$clangxx_command_sha256" \
  --arg linker_command "$linker_command" \
  --arg linker_command_sha256 "$linker_command_sha256" \
  --arg ar_command "$ar_command" \
  --arg ar_command_sha256 "$ar_command_sha256" \
  --arg ranlib_command "$ranlib_command" \
  --arg ranlib_command_sha256 "$ranlib_command_sha256" \
  --arg developer_dir "$developer_dir" \
  --arg macos_sdk_path "$macos_sdk_path" \
  --arg macos_sdk_version "$macos_sdk_version" \
  --arg macos_sdk_build_version "$macos_sdk_build_version" \
  --arg macos_sdk_settings_sha256 "$macos_sdk_settings_sha256" \
  --arg clang_resource_dir "$clang_resource_dir" \
  --arg apple_build_input_ledger "$apple_build_input_ledger" \
  --arg apple_build_input_ledger_sha256 "$apple_build_input_ledger_sha256" \
  --argjson apple_build_input_entry_count "$apple_build_input_entry_count" \
  --arg homeserver "http://127.0.0.1:$fixture_port" \
  --arg synapse_transport "docker-exec-loopback-proxy-v1" \
  --arg synapse_network_mode "internal" \
  --argjson synapse_network_internal true \
  --argjson synapse_docker_port_published false \
  --arg synapse_proxy_source "$proxy_script" \
  --arg synapse_proxy_source_sha256 "$proxy_source_sha256" \
  --arg synapse_proxy_ready "$proxy_ready_file" \
  --arg synapse_proxy_ready_sha256 "$proxy_ready_sha256" \
  --argjson synapse_proxy_port "$proxy_port" \
  --argjson synapse_proxy_pid "$proxy_pid" \
  --arg agentd_binary "$agentd_bin" \
  --arg matrixd_binary "$matrixd_bin" \
  --arg test_binary "$test_bin" \
  --arg runner_path "$runner_path" \
  --arg agentd_sha256 "$agentd_sha256" \
  --arg matrixd_sha256 "$matrixd_sha256" \
  --arg test_binary_sha256 "$test_binary_sha256" \
  --arg runner_sha256 "$runner_sha256" \
  --arg agentd_build_json "$agentd_build_json" \
  --arg matrixd_build_json "$matrixd_build_json" \
  --arg test_build_json "$test_build_json" \
  --arg agentd_build_json_sha256 "$agentd_build_json_sha256" \
  --arg matrixd_build_json_sha256 "$matrixd_build_json_sha256" \
  --arg test_build_json_sha256 "$test_build_json_sha256" \
  --arg credentials_directory "$credentials_directory" \
  --arg runtime_tmp_root "$runtime_tmp_root" \
  --arg synapse_image_ref "$PINNED_SYNAPSE_IMAGE" \
  --arg synapse_image_id "$image_id" \
  --arg synapse_version "$runtime_synapse_version" \
  --arg synapse_git_sha "$image_git_sha" \
  --arg homeserver_config_sha256 "$config_sha256" \
  --argjson source_clean "$source_clean" \
  '{
    schema_version: 8,
    qualification_mode: $qualification_mode,
    source_root: $source_root,
    candidate_sha: $candidate_sha,
    candidate_tree_sha: $candidate_tree_sha,
    source_clean: $source_clean,
    source_status_sha256: $source_status_sha256,
    cargo_lock_sha256: $cargo_lock_sha256,
    workspace_manifest_sha256: $workspace_manifest_sha256,
    cargo_config_sha256: $cargo_config_sha256,
    agentd_manifest_sha256: $agentd_manifest_sha256,
    matrixd_manifest_sha256: $matrixd_manifest_sha256,
    matrix_sdk_manifest_sha256: $matrix_sdk_manifest_sha256,
    rust_toolchain_manifest_sha256: $rust_toolchain_manifest_sha256,
    rust_toolchain_channel: $rust_toolchain_channel,
    rustc_release: $rustc_release,
    rustc_commit: $rustc_commit,
    rustc_host: $rustc_host,
    target_triple: $target_triple,
    rustc_command: $rustc_command,
    cargo_command: $cargo_command,
    rustdoc_command: $rustdoc_command,
    rustc_command_sha256: $rustc_command_sha256,
    cargo_command_sha256: $cargo_command_sha256,
    rustdoc_command_sha256: $rustdoc_command_sha256,
    rustc_verbose_sha256: $rustc_verbose_sha256,
    cargo_version: $cargo_version,
    build_allowlisted_environment: true,
    build_locked: true,
    build_offline: true,
    inherited_rustflags: false,
    cargo_home: $qualification_cargo_home,
    cargo_home_config_absent: true,
    cargo_home_credentials_absent: true,
    cargo_dependency_seed_excludes_unpacked_sources: true,
    cargo_dependency_seed_ledger: $cargo_seed_ledger,
    cargo_dependency_seed_manifest_sha256: $cargo_seed_manifest_sha256,
    cargo_dependency_seed_file_count: $cargo_seed_file_count,
    cargo_git_database_count: $cargo_git_database_count,
    cargo_git_databases_local_repacked_and_fscked: true,
    cargo_git_external_object_authority_absent: true,
    product_build_target_directory: $product_build_target,
    test_build_target_directory: $test_build_target,
    product_and_test_targets_isolated: true,
    build_path: $build_path,
    inherited_build_path: false,
    rust_tool_bin: $rust_tool_bin,
    rust_tool_ledger: $rust_tool_ledger,
    rust_tool_ledger_sha256: $rust_tool_ledger_sha256,
    private_rust_tool_path_only: true,
    host_tool_bin: $host_tool_bin,
    host_tool_ledger: $host_tool_ledger,
    host_tool_ledger_sha256: $host_tool_ledger_sha256,
    runner_control_tool_ledger: $runner_control_tool_ledger,
    runner_control_tool_ledger_sha256: $runner_control_tool_ledger_sha256,
    runner_control_static_scan: $runner_control_static_scan,
    runner_control_static_scan_sha256: $runner_control_static_scan_sha256,
    runner_control_static_scan_passed: true,
    runner_control_tools_absolute: true,
    bash_command: $bash_command,
    bash_command_sha256: $bash_command_sha256,
    bash_version: $bash_version,
    bash_version_file: $bash_version_file,
    bash_version_sha256: $bash_version_sha256,
    process_identity_ledger: $process_identity_ledger,
    process_identity_ledger_required: true,
    macos_host_toolchain_bounded: true,
    host_toolchain_hermetic: false,
    target_linker_environment_key: $target_linker_environment_key,
    xcrun_command: $xcrun_command,
    xcrun_command_sha256: $xcrun_command_sha256,
    xcodebuild_command: $xcodebuild_command,
    xcodebuild_command_sha256: $xcodebuild_command_sha256,
    xcodebuild_version_file: $xcodebuild_version_file,
    xcodebuild_version_sha256: $xcodebuild_version_sha256,
    clang_command: $clang_command,
    clang_command_sha256: $clang_command_sha256,
    clangxx_command: $clangxx_command,
    clangxx_command_sha256: $clangxx_command_sha256,
    linker_command: $linker_command,
    linker_command_sha256: $linker_command_sha256,
    ar_command: $ar_command,
    ar_command_sha256: $ar_command_sha256,
    ranlib_command: $ranlib_command,
    ranlib_command_sha256: $ranlib_command_sha256,
    developer_dir: $developer_dir,
    macos_sdk_path: $macos_sdk_path,
    macos_sdk_version: $macos_sdk_version,
    macos_sdk_build_version: $macos_sdk_build_version,
    macos_sdk_settings_sha256: $macos_sdk_settings_sha256,
    clang_resource_dir: $clang_resource_dir,
    apple_build_input_ledger: $apple_build_input_ledger,
    apple_build_input_ledger_sha256: $apple_build_input_ledger_sha256,
    apple_build_input_entry_count: $apple_build_input_entry_count,
    apple_build_input_complete_tree_manifest: true,
    agentd_profile: "dev",
    matrixd_profile: "dev",
    test_profile: "test",
    agentd_default_features: true,
    matrixd_default_features: true,
    test_default_features: true,
    agentd_features: [],
    matrixd_features: ["real-synapse-e2e"],
    matrix_sdk_features: ["qualification-failpoints"],
    test_features: ["real-synapse-e2e"],
    homeserver: $homeserver,
    synapse_transport: $synapse_transport,
    synapse_network_mode: $synapse_network_mode,
    synapse_network_internal: $synapse_network_internal,
    synapse_docker_port_published: $synapse_docker_port_published,
    synapse_proxy_source: $synapse_proxy_source,
    synapse_proxy_source_sha256: $synapse_proxy_source_sha256,
    synapse_proxy_ready: $synapse_proxy_ready,
    synapse_proxy_ready_sha256: $synapse_proxy_ready_sha256,
    synapse_proxy_port: $synapse_proxy_port,
    synapse_proxy_pid: $synapse_proxy_pid,
    agentd_binary: $agentd_binary,
    matrixd_binary: $matrixd_binary,
    test_binary: $test_binary,
    runner_path: $runner_path,
    agentd_sha256: $agentd_sha256,
    matrixd_sha256: $matrixd_sha256,
    test_binary_sha256: $test_binary_sha256,
    runner_sha256: $runner_sha256,
    agentd_build_json: $agentd_build_json,
    matrixd_build_json: $matrixd_build_json,
    test_build_json: $test_build_json,
    agentd_build_json_sha256: $agentd_build_json_sha256,
    matrixd_build_json_sha256: $matrixd_build_json_sha256,
    test_build_json_sha256: $test_build_json_sha256,
    agentd_cargo_arguments: ["build", "--locked", "--offline", "--target", $target_triple, "--profile", "dev", "-p", "codex-hepta-agentd", "--bin", "codex-hepta-agentd"],
    matrixd_cargo_arguments: ["build", "--locked", "--offline", "--target", $target_triple, "--profile", "dev", "-p", "codex-hepta-matrixd", "--features", "real-synapse-e2e", "--bin", "codex-hepta-matrixd"],
    test_cargo_arguments: ["test", "--locked", "--offline", "--target", $target_triple, "--profile", "test", "-p", "codex-hepta-matrixd", "--features", "real-synapse-e2e", "--test", "real_synapse_e2e", "--no-run"],
    credentials_directory: $credentials_directory,
    runtime_tmp_root: $runtime_tmp_root,
    synapse_image_ref: $synapse_image_ref,
    synapse_image_id: $synapse_image_id,
    synapse_version: $synapse_version,
    synapse_git_sha: $synapse_git_sha,
    homeserver_config_sha256: $homeserver_config_sha256
  }' >"$generated_manifest"
durable_install_file "$generated_manifest" "$fixture_manifest" 600
"$rm_bin" -f -- "$generated_manifest"
fixture_manifest_sha256=$(sha256_file "$fixture_manifest")
unset human_password agent_a_password agent_b_password

resolve_host_tool_path() {
  local raw_path=$1
  "$python_bin" - "$raw_path" <<'PY'
import os
import pathlib
import stat
import sys

resolved = pathlib.Path(sys.argv[1]).resolve(strict=True)
metadata = resolved.stat()
if not stat.S_ISREG(metadata.st_mode) or not os.access(resolved, os.X_OK):
    raise SystemExit("xcrun tool did not resolve to a regular executable")
print(resolved)
PY
}

verify_provenance_snapshot() {
  local final_status_file=$1
  local final_rustc_file=$2
  local final_candidate_sha
  local final_candidate_tree_sha
  final_candidate_sha=$("${runner_git[@]}" -C "$source_root" rev-parse --verify HEAD) || return 65
  final_candidate_tree_sha=$("${runner_git[@]}" -C "$source_root" rev-parse --verify 'HEAD^{tree}') || return 65
  [[ "$final_candidate_sha" == "$candidate_sha" \
    && "$final_candidate_tree_sha" == "$candidate_tree_sha" ]] || {
    echo 'candidate HEAD/tree changed during qualification' >&2
    return 65
  }
  "${runner_git[@]}" -C "$source_root" status \
    --porcelain=v1 --untracked-files=all --ignored=matching >"$final_status_file" || return 65
  [[ "$(sha256_file "$final_status_file")" == "$source_status_sha256" ]] || {
    echo 'candidate worktree content/status changed during qualification' >&2
    return 65
  }
  [[ "$(sha256_file "$cargo_lock")" == "$cargo_lock_sha256" \
    && "$(sha256_file "$workspace_manifest")" == "$workspace_manifest_sha256" \
    && "$(sha256_file "$cargo_config")" == "$cargo_config_sha256" \
    && "$(sha256_file "$agentd_manifest")" == "$agentd_manifest_sha256" \
    && "$(sha256_file "$matrixd_manifest")" == "$matrixd_manifest_sha256" \
    && "$(sha256_file "$matrix_sdk_manifest")" == "$matrix_sdk_manifest_sha256" \
    && "$(sha256_file "$rust_toolchain_manifest")" == "$rust_toolchain_manifest_sha256" ]] || {
    echo 'candidate build manifest changed during qualification' >&2
    return 65
  }
  "$rustc_command" -Vv >"$final_rustc_file" || return 65
  [[ "$(sha256_file "$final_rustc_file")" == "$rustc_verbose_sha256" \
    && "$("$cargo_command" -V)" == "$cargo_version" \
    && "$(sha256_file "$rustc_command")" == "$rustc_command_sha256" \
    && "$(sha256_file "$cargo_command")" == "$cargo_command_sha256" \
    && "$(sha256_file "$rustdoc_command")" == "$rustdoc_command_sha256" ]] || {
    echo 'Rust/Cargo toolchain changed during qualification' >&2
    return 65
  }
  [[ "$(sha256_file "$agentd_build_json")" == "$agentd_build_json_sha256" \
    && "$(sha256_file "$matrixd_build_json")" == "$matrixd_build_json_sha256" \
    && "$(sha256_file "$test_build_json")" == "$test_build_json_sha256" \
    && "$(sha256_file "$agentd_bin")" == "$agentd_sha256" \
    && "$(sha256_file "$matrixd_bin")" == "$matrixd_sha256" \
    && "$(sha256_file "$test_bin")" == "$test_binary_sha256" \
    && "$(sha256_file "$runner_path")" == "$runner_sha256" \
    && "$(sha256_file "$fixture_manifest")" == "$fixture_manifest_sha256" \
    && "$(sha256_file "$proxy_source_path")" == "$proxy_source_sha256" \
    && "$(sha256_file "$proxy_script")" == "$proxy_source_sha256" \
    && "$(sha256_file "$proxy_ready_file")" == "$proxy_ready_sha256" ]] || {
    echo 'candidate build artifact/provenance changed during qualification' >&2
    return 65
  }
  local final_cargo_seed_ledger="$fixture_root/cargo-dependency-seed-ledger.final.json"
  local final_host_tool_ledger="$fixture_root/host-tool-ledger.final.json"
  local final_rust_tool_ledger="$fixture_root/rust-tool-ledger.final.json"
  local final_runner_control_tool_ledger="$fixture_root/runner-control-tool-ledger.final.json"
  local final_runner_control_static_scan="$fixture_root/runner-control-static-scan.final.json"
  local final_apple_build_input_ledger="$fixture_root/apple-build-input-ledger.final.json"
  local final_xcodebuild_version_file="$fixture_root/xcodebuild-version.final.txt"
  local final_bash_version_file="$fixture_root/bash-version.final.txt"
  "$rm_bin" -f -- \
    "$final_cargo_seed_ledger" \
    "$final_host_tool_ledger" \
    "$final_rust_tool_ledger" \
    "$final_runner_control_tool_ledger" \
    "$final_runner_control_static_scan" \
    "$final_apple_build_input_ledger" \
    "$final_xcodebuild_version_file" \
    "$final_bash_version_file"
  write_cargo_seed_ledger "$final_cargo_seed_ledger" || return 65
  if ! "$cmp_bin" -s "$cargo_seed_ledger" "$final_cargo_seed_ledger"; then
    echo 'sanitized Cargo dependency seed changed or gained a non-regular entry during qualification' >&2
    return 65
  fi
  "$rm_bin" -f -- "$final_cargo_seed_ledger"
  write_link_tool_ledger "$host_tool_bin" "$final_host_tool_ledger" || return 65
  if ! "$cmp_bin" -s "$host_tool_ledger" "$final_host_tool_ledger"; then
    echo 'bounded host tool allowlist changed during qualification' >&2
    return 65
  fi
  "$rm_bin" -f -- "$final_host_tool_ledger"
  write_link_tool_ledger "$rust_tool_bin" "$final_rust_tool_ledger" || return 65
  if ! "$cmp_bin" -s "$rust_tool_ledger" "$final_rust_tool_ledger"; then
    echo 'private Rust tool allowlist changed during qualification' >&2
    return 65
  fi
  "$rm_bin" -f -- "$final_rust_tool_ledger"
  write_runner_control_tool_ledger "$final_runner_control_tool_ledger" || return 65
  if ! "$cmp_bin" -s "$runner_control_tool_ledger" "$final_runner_control_tool_ledger"; then
    echo 'runner control tool authority changed during qualification' >&2
    return 65
  fi
  "$rm_bin" -f -- "$final_runner_control_tool_ledger"
  write_runner_control_static_scan "$final_runner_control_static_scan" || return 65
  if ! "$cmp_bin" -s "$runner_control_static_scan" "$final_runner_control_static_scan"; then
    echo 'runner control static scan authority changed during qualification' >&2
    return 65
  fi
  "$rm_bin" -f -- "$final_runner_control_static_scan"
  write_apple_build_input_ledger "$final_apple_build_input_ledger" || return 65
  if ! "$cmp_bin" -s "$apple_build_input_ledger" "$final_apple_build_input_ledger"; then
    echo 'Apple SDK/clang resource content changed during qualification' >&2
    return 65
  fi
  "$rm_bin" -f -- "$final_apple_build_input_ledger"
  "$xcodebuild_command" -version >"$final_xcodebuild_version_file" || return 65
  if ! "$cmp_bin" -s "$xcodebuild_version_file" "$final_xcodebuild_version_file"; then
    echo 'Xcode version/build identity changed during qualification' >&2
    return 65
  fi
  "$rm_bin" -f -- "$final_xcodebuild_version_file"
  "$bash_bin" --version | "$head_bin" -n 1 >"$final_bash_version_file" || return 65
  if ! "$cmp_bin" -s "$bash_version_file" "$final_bash_version_file"; then
    echo 'canonical Bash version identity changed during qualification' >&2
    return 65
  fi
  "$rm_bin" -f -- "$final_bash_version_file"
  local final_xcodebuild_command
  local final_clang_command
  local final_clangxx_command
  local final_linker_command
  local final_ar_command
  local final_ranlib_command
  final_xcodebuild_command=$(resolve_host_tool_path "$("$xcrun_command" --find xcodebuild)") || return 65
  final_clang_command=$(resolve_host_tool_path "$("$xcrun_command" --sdk macosx --find clang)") || return 65
  final_clangxx_command=$(resolve_host_tool_path "$("$xcrun_command" --sdk macosx --find clang++)") || return 65
  final_linker_command=$(resolve_host_tool_path "$("$xcrun_command" --sdk macosx --find ld)") || return 65
  final_ar_command=$(resolve_host_tool_path "$("$xcrun_command" --sdk macosx --find ar)") || return 65
  final_ranlib_command=$(resolve_host_tool_path "$("$xcrun_command" --sdk macosx --find ranlib)") || return 65
  [[ "$(sha256_file "$cargo_seed_ledger")" == "$cargo_seed_manifest_sha256" \
    && "$(sha256_file "$host_tool_ledger")" == "$host_tool_ledger_sha256" \
    && "$(sha256_file "$rust_tool_ledger")" == "$rust_tool_ledger_sha256" \
    && "$(sha256_file "$runner_control_tool_ledger")" == "$runner_control_tool_ledger_sha256" \
    && "$(sha256_file "$runner_control_static_scan")" == "$runner_control_static_scan_sha256" \
    && "$(sha256_file "$bash_bin")" == "$bash_command_sha256" \
    && "$(sha256_file "$bash_version_file")" == "$bash_version_sha256" \
    && "$(sha256_file "$apple_build_input_ledger")" == "$apple_build_input_ledger_sha256" \
    && "$(sha256_file "$xcodebuild_command")" == "$xcodebuild_command_sha256" \
    && "$(sha256_file "$xcodebuild_version_file")" == "$xcodebuild_version_sha256" \
    && "$build_path" == "$rust_tool_bin:$host_tool_bin" \
    && "$(sha256_file "$xcrun_command")" == "$xcrun_command_sha256" \
    && "$(sha256_file "$clang_command")" == "$clang_command_sha256" \
    && "$(sha256_file "$clangxx_command")" == "$clangxx_command_sha256" \
    && "$(sha256_file "$linker_command")" == "$linker_command_sha256" \
    && "$(sha256_file "$ar_command")" == "$ar_command_sha256" \
    && "$(sha256_file "$ranlib_command")" == "$ranlib_command_sha256" \
    && "$(sha256_file "$macos_sdk_settings")" == "$macos_sdk_settings_sha256" \
    && "$("$xcrun_command" --sdk macosx --show-sdk-version)" == "$macos_sdk_version" \
    && "$("$xcrun_command" --sdk macosx --show-sdk-build-version)" == "$macos_sdk_build_version" \
    && "$final_xcodebuild_command" == "$xcodebuild_command" \
    && "$final_clang_command" == "$clang_command" \
    && "$final_clangxx_command" == "$clangxx_command" \
    && "$final_linker_command" == "$linker_command" \
    && "$final_ar_command" == "$ar_command" \
    && "$final_ranlib_command" == "$ranlib_command" \
    && "$("$clang_command" -print-resource-dir)" == "$clang_resource_dir" ]] || {
    echo 'bounded Mac host toolchain or SDK identity changed during qualification' >&2
    return 65
  }
  for inherited_cargo_config in \
    "$qualification_cargo_home/config" \
    "$qualification_cargo_home/config.toml" \
    "$qualification_cargo_home/credentials" \
    "$qualification_cargo_home/credentials.toml"; do
    if [[ -e "$inherited_cargo_config" || -L "$inherited_cargo_config" ]]; then
      echo 'Cargo home configuration appeared during qualification' >&2
      return 65
    fi
  done
  verify_bound_cargo_configs || return 65
  [[ "$agentd_bin" == "$product_build_target"/* \
    && "$matrixd_bin" == "$product_build_target"/* \
    && "$test_bin" == "$test_build_target"/* ]] || {
    echo 'candidate executable escaped the isolated build target' >&2
    return 65
  }
}

verify_final_provenance() {
  verify_provenance_snapshot \
    "$fixture_root/source-status.final.porcelain" \
    "$fixture_root/rustc-vv.final.txt"
}

verify_publication_provenance() {
  local publication_status="$fixture_root/source-status.publication.porcelain"
  local publication_rustc="$fixture_root/rustc-vv.publication.txt"
  "$rm_bin" -f -- "$publication_status" "$publication_rustc"
  verify_provenance_snapshot "$publication_status" "$publication_rustc" || return 65
  [[ "$(sha256_file "$publication_status")" \
      == "$(sha256_file "$fixture_root/source-status.final.porcelain")" \
    && "$(sha256_file "$publication_rustc")" \
      == "$(sha256_file "$fixture_root/rustc-vv.final.txt")" ]] || {
    echo 'publication provenance disagreed with the post-cleanup snapshot' >&2
    return 65
  }
  "$rm_bin" -f -- "$publication_status" "$publication_rustc"
}

echo "R4_FIXTURE homeserver=http://127.0.0.1:$fixture_port transport=docker-exec-loopback-proxy-v1 network=internal docker_port_published=false proxy_port=$proxy_port proxy_pid=$proxy_pid config_sha256=$config_sha256 manifest_mode=0600"
completion_directory="$fixture_root/completion"
"$mkdir_bin" "$completion_directory"
"$chmod_bin" 700 "$completion_directory"
completion_nonce=$("$openssl_bin" rand -hex 32)
[[ "$completion_nonce" =~ ^[0-9a-f]{64}$ ]] || {
  echo 'completion nonce generation failed' >&2
  exit 65
}
completion_nonce_file="$credentials_directory/completion-nonce"
write_secret_capability "$completion_nonce_file" "$completion_nonce"
test_environment=(
  "$env_bin" -i
  "PATH=$build_path"
  "HOME=$test_home"
  "TMPDIR=$runtime_tmp_root"
  'LANG=C'
  'LC_ALL=C'
  'RUST_BACKTRACE=1'
  "HEPTA_R4_FIXTURE_MANIFEST=$fixture_manifest"
  "HEPTA_R4_COMPLETION_DIRECTORY=$completion_directory"
  "HEPTA_R4_COMPLETION_NONCE_FILE=$completion_nonce_file"
)
set +e
"${test_environment[@]}" "$test_bin" \
  "$QUALIFICATION_TEST_NAME" --exact --test-threads=1 --nocapture 2>&1 \
  | "$tee_bin" "$fixture_root/test.log"
pipeline_status=("${PIPESTATUS[@]}")
set -e
test_rc=${pipeline_status[0]}
tee_rc=${pipeline_status[1]}
if ((tee_rc != 0)); then
  echo "qualification log tee failed with exit $tee_rc" >&2
  ((test_rc == 0)) && test_rc=74
fi

if ((test_rc == 0)); then
  shopt -s nullglob
  completion_entries=(
    "$completion_directory"/*
    "$completion_directory"/.[!.]*
    "$completion_directory"/..?*
  )
  shopt -u nullglob
  [[ ${#completion_entries[@]} -eq 1 \
    && "${completion_entries[0]}" == "$completion_directory/completion.json" \
    && -f "${completion_entries[0]}" \
    && "$("$stat_bin" -f '%Lp' "${completion_entries[0]}")" == 600 ]] || {
    echo 'qualification test did not emit exactly one mode-0600 completion.json receipt' >&2
    test_rc=65
  }
fi
if ((test_rc == 0)); then
  completion_receipt_nonce=''
  completion_receipt_nonce=$("$jq_bin" -er \
    '.nonce | select(type == "string")' \
    "$completion_directory/completion.json") || {
      echo 'qualification completion receipt omitted its nonce' >&2
      test_rc=65
    }
fi
if ((test_rc == 0)) && [[ "$completion_receipt_nonce" != "$completion_nonce" ]]; then
  echo 'qualification completion receipt nonce did not match the private capability' >&2
  test_rc=65
fi
if ((test_rc == 0)); then
  "$jq_bin" -e \
    --slurpfile process_ledger "$process_identity_ledger" \
    --arg qualification_mode "$source_mode" \
    --arg candidate_sha "$candidate_sha" \
    --arg candidate_tree_sha "$candidate_tree_sha" \
    --arg test_name "$QUALIFICATION_TEST_NAME" \
    --arg paired_release_id "$PAIRED_RELEASE_ID" \
    --argjson source_clean "$source_clean" \
    '.schema_version == 2
      and .test_name == $test_name
      and (.nonce | type == "string" and test("^[0-9a-f]{64}$"))
      and .qualification_mode == $qualification_mode
      and .candidate_sha == $candidate_sha
      and .candidate_tree_sha == $candidate_tree_sha
      and .source_clean == $source_clean
      and .test_assertions_passed == true
      and .runner_revalidation_required == true
      and .runtime_root_removed == true
      and .credential_capabilities_removed == true
      and .promotable == false
      and .wire_put_attempts == 2
      and .agent_a_provider_requests == 5
      and .agent_b_provider_requests == 3
      and .release_copy_identity_rechecked_at_lifecycle_boundaries == true
      and .release_execve_atomic_binding == false
      and .explicit_product_shutdown_completed == true
      and .all_historical_product_pids_absent == true
      and (.process_history | type == "array" and length >= 4)
      and .process_history == $process_ledger[0].history
      and (.release_copy_observations | type == "array" and length >= 13)
      and ([.release_copy_observations[].identity] | unique | length == 1)
      and ([.release_copy_observations[].stage] | index("network_respawn_before_disconnect") != null)
      and ([.release_copy_observations[].stage] | index("network_respawn_before_ready") != null)
      and ([.release_copy_observations[].stage] | index("network_respawn_after_ready") != null)
      and ([.release_copy_observations[].stage] | index("sidecar_respawn_before_sigkill") != null)
      and ([.release_copy_observations[].stage] | index("sidecar_respawn_before_ready") != null)
      and ([.release_copy_observations[].stage] | index("sidecar_respawn_after_ready") != null)
      and ([.release_copy_observations[].stage] | index("supervisor_restart_before") != null)
      and ([.release_copy_observations[].stage] | index("supervisor_restart_after_ready") != null)
      and all(.release_copy_observations[];
        (.stage | type == "string" and length > 0)
        and (.agent_id | type == "string" and length > 0)
        and ((.agent_pid == null) or (.agent_pid | type == "number" and . > 0))
        and ((.matrix_pid == null) or (.matrix_pid | type == "number" and . > 0))
        and ((.spawn_generation == null) or (.spawn_generation | type == "number" and . > 0))
        and .identity.release_id == $paired_release_id
        and all([.identity.agentd, .identity.matrixd][];
          (.path | type == "string" and startswith("/"))
          and (.device_id | type == "number" and . > 0)
          and (.inode | type == "number" and . > 0)
          and (.size_bytes | type == "number" and . > 0)
          and (.sha256 | type == "string" and test("^[0-9a-f]{64}$"))))
      and (.stable_txn_id | type == "string" and length > 0)
      and (.synapse_event_id | type == "string" and length > 0)
      and (.expected_put_target | test("^/_matrix/client/v3/rooms/[^/]+/send/m[.]room[.]encrypted/[^/]+$"))' \
    "$completion_directory/completion.json" >/dev/null || {
      echo 'qualification completion receipt failed nonce/identity/evidence validation' >&2
      test_rc=65
    }
fi
if ((test_rc == 0)); then
  release_copy_observation_count=$("$jq_bin" -er \
    '.release_copy_observations | length | select(. >= 13)' \
    "$completion_directory/completion.json") || {
      echo 'qualification completion receipt omitted lifecycle release observations' >&2
      test_rc=65
    }
fi
if ((test_rc == 0)); then
  "$jq_bin" -e \
    '.schema_version == 1
      and .explicit_shutdown_completed == true
      and .all_historical_pids_absent == true
      and (.active | type == "array" and length == 0)
      and (.history | type == "array" and length >= 4)
      and all(.history[];
        (.agent_id | type == "string" and length > 0)
        and (.plane == "agent" or .plane == "matrix")
        and (.pid | type == "number" and . > 0)
        and (.driver_incarnation | type == "string" and length > 0)
        and ((.plane == "agent" and .protocol_incarnation == null)
          or (.plane == "matrix"
            and (.protocol_incarnation | type == "string" and length > 0)))
        and (.spawn_generation | type == "number" and . > 0)
        and (.first_seen_stage | type == "string" and length > 0)
        and (.last_seen_stage | type == "string" and length > 0))' \
    "$process_identity_ledger" >/dev/null || {
      echo 'product PID/incarnation ledger did not prove explicit shutdown' >&2
      test_rc=65
    }
fi
if ((test_rc == 0)); then
  while IFS= read -r historical_pid; do
    [[ "$historical_pid" =~ ^[0-9]+$ && "$historical_pid" -gt 0 ]] || {
      echo 'product PID ledger contains an invalid PID' >&2
      test_rc=65
      break
    }
    set +e
    "$kill_bin" -0 "$historical_pid" >/dev/null 2>&1
    pid_kill_rc=$?
    pid_ps_output=$("$ps_bin" -p "$historical_pid" -o pid= 2>/dev/null)
    pid_ps_rc=$?
    set -e
    pid_ps_output=${pid_ps_output//[[:space:]]/}
    if ((pid_kill_rc == 0)) \
      || [[ "$pid_ps_output" == "$historical_pid" ]] \
      || ! { ((pid_ps_rc == 1)) && [[ -z "$pid_ps_output" ]]; }; then
      echo "historical product PID $historical_pid is alive or its identity is ambiguous" >&2
      test_rc=65
      break
    fi
  done < <("$jq_bin" -er '.history | map(.pid) | unique[]' "$process_identity_ledger")
fi
exit "$test_rc"
