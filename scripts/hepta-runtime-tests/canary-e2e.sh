#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: canary-e2e.sh --binary PATH [--source-state-root DIR] [--target-manifest PATH --snapshot-receipt PATH] [--output-receipt PATH --output-soak-receipt PATH]" >&2
  exit 64
}

binary=""
source_state_root=""
output_receipt=""
output_soak_receipt=""
target_manifest=""
snapshot_receipt=""
while (( $# > 0 )); do
  case "$1" in
    --binary) shift; [[ $# -gt 0 ]] || usage; binary="$1" ;;
    --source-state-root) shift; [[ $# -gt 0 ]] || usage; source_state_root="$1" ;;
    --output-receipt) shift; [[ $# -gt 0 ]] || usage; output_receipt="$1" ;;
    --output-soak-receipt) shift; [[ $# -gt 0 ]] || usage; output_soak_receipt="$1" ;;
    --target-manifest) shift; [[ $# -gt 0 ]] || usage; target_manifest="$1" ;;
    --snapshot-receipt) shift; [[ $# -gt 0 ]] || usage; snapshot_receipt="$1" ;;
    *) usage ;;
  esac
  shift
done
[[ ( -z "$output_receipt" && -z "$output_soak_receipt" ) \
  || ( -n "$output_receipt" && -n "$output_soak_receipt" ) ]] || usage
[[ ( -z "$target_manifest" && -z "$snapshot_receipt" ) \
  || ( -n "$target_manifest" && -n "$snapshot_receipt" && -n "$source_state_root" ) ]] || usage
[[ -z "$output_receipt" || -n "$target_manifest" ]] || {
  echo "persisted canary evidence requires an exact target manifest and snapshot receipt" >&2
  exit 1
}
[[ -x "$binary" && -f "$binary" && ! -L "$binary" ]] || usage
binary="$(realpath "$binary")"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
source_tree="$(cd "$script_dir/.." && pwd -P)"
git -C "$source_tree" diff --quiet --ignore-submodules -- \
  && git -C "$source_tree" diff --cached --quiet --ignore-submodules -- \
  && [[ -z "$(git -C "$source_tree" ls-files --others --exclude-standard)" ]] || {
    echo "canary source worktree must be clean so evidence cannot attribute dirty bytes to HEAD" >&2
    exit 1
  }
source_commit="$(git -C "$source_tree" rev-parse --verify 'HEAD^{commit}')"
[[ "$source_commit" =~ ^[0-9a-f]{40}$ ]] || {
  echo "canary source commit is not an exact Git object ID" >&2
  exit 1
}
if [[ -n "$source_state_root" ]]; then
  source_state_root="$(realpath "$source_state_root")"
  [[ "$source_state_root" == /* && "$source_state_root" != "/" ]] || usage
fi
target_manifest_sha=""
snapshot_receipt_sha=""
snapshot_schema=""
snapshot_profile=""
snapshot_mode_profile=""
snapshot_acl_profile=""
snapshot_id=""
snapshot_source_identity_sha=""
snapshot_portable_payload_sha=""
snapshot_original_mode_sha=""
snapshot_top_level_sha=""
snapshot_sidecar_sha=""
snapshot_key_sha=""
snapshot_hardlink_sha=""
snapshot_acl_sha=""
snapshot_predecessor_receipt=""
snapshot_predecessor_sha=""
snapshot_predecessor_plan_sha=""
snapshot_predecessor_sequence=""
snapshot_writer_barrier='null'
if [[ -n "$target_manifest" ]]; then
  target_manifest="$(realpath "$target_manifest")"
  snapshot_receipt="$(realpath "$snapshot_receipt")"
  target_release="$(dirname "$target_manifest")"
  [[ "$(jq -r '.watchdog.verify_tool' "$target_manifest")" == "scripts/hepta-immutable-release-tree" ]] || {
    echo "target manifest declares an unsupported verifier" >&2
    exit 1
  }
  "$target_release/scripts/hepta-immutable-release-tree" verify --manifest "$target_manifest" >/dev/null
  "$target_release/scripts/hepta-state-snapshot" verify --receipt "$snapshot_receipt" >/dev/null
  "$target_release/scripts/hepta-state-snapshot" verify-source --receipt "$snapshot_receipt" >/dev/null
  [[ "$(jq -r '.artifact.sha256' "$target_manifest")" == "$(shasum -a 256 "$binary" | awk '{print $1}')" \
    && "$(jq -r '.source.commit' "$target_manifest")" == "$source_commit" \
    && "$(jq -r '.runtime.state_root' "$target_manifest")" == "$source_state_root" \
    && "$(jq -r '.destination_state_root' "$snapshot_receipt")" == "$source_state_root" ]] || {
    echo "target manifest, binary, source commit, and snapshot are not one exact canary candidate" >&2
    exit 1
  }
  target_manifest_sha="$(shasum -a 256 "$target_manifest" | awk '{print $1}')"
  snapshot_receipt_sha="$(shasum -a 256 "$snapshot_receipt" | awk '{print $1}')"
  snapshot_schema="$(jq -r '.schema' "$snapshot_receipt")"
  snapshot_profile="$(jq -r '.profile // empty' "$snapshot_receipt")"
  snapshot_mode_profile="$(jq -r '.mode_profile // empty' "$snapshot_receipt")"
  snapshot_acl_profile="$(jq -r '.acl_profile // empty' "$snapshot_receipt")"
  target_snapshot_scope="$(jq -r '.runtime.state_snapshot_scope // empty' "$target_manifest")"
  target_snapshot_schema="$(jq -r '.runtime.state_snapshot_receipt_schema // empty' "$target_manifest")"
  target_snapshot_mode_profile="$(jq -r '.runtime.state_snapshot_mode_profile // empty' "$target_manifest")"
  target_snapshot_acl_profile="$(jq -r '.runtime.state_snapshot_acl_profile // empty' "$target_manifest")"
  if [[ "$target_snapshot_scope" != full-state-root-v3 \
    || "$target_snapshot_schema" != hepta_vnext_state_snapshot_receipt_v3 \
    || "$target_snapshot_mode_profile" != hepta_vnext_state_mode_profile_v3 \
    || "$target_snapshot_acl_profile" != hepta_vnext_state_acl_profile_deny_only_v1 \
    || "$snapshot_schema" != hepta_vnext_state_snapshot_receipt_v3 \
    || "$snapshot_profile" != full-state-root-v3 \
    || "$snapshot_mode_profile" != hepta_vnext_state_mode_profile_v3 \
    || "$snapshot_acl_profile" != hepta_vnext_state_acl_profile_deny_only_v1 ]]; then
    echo "persisted canary requires the exact full-state-root-v3 receipt, mode, and ACL profiles" >&2
    exit 1
  fi
  jq -e '
    .scope == "full-state-root"
    and .all_top_level_entries_covered == true
    and .mode_policy_validated == true
    and .original_modes_preserved == true
    and (.original_mode_inventory_sha256 | test("^[0-9a-f]{64}$"))
    and .modes_uid_gid_mtime_flags_acl_xattr_preserved == true
    and .acl_allow_aces_forbidden == true
    and .acl_deny_only_preserved == true
    and .acl_inventory_bound == true
    and (.acl_inventory_sha256 | test("^[0-9a-f]{64}$"))
    and .wal_shm_and_keys_covered == true
    and .replay_protected_by_destination_binding == true
    and .writer_admission_closed == true
    and .writer_barrier.writer_admission_closed == true
  ' "$snapshot_receipt" >/dev/null || {
    echo "persisted canary requires a complete full-root v3 snapshot receipt" >&2
    exit 1
  }
  snapshot_id="$(jq -r '.snapshot_id' "$snapshot_receipt")"
  snapshot_source_identity_sha="$(jq -r '.source_identity_inventory_sha256' "$snapshot_receipt")"
  snapshot_portable_payload_sha="$(jq -r '.portable_payload_inventory_sha256' "$snapshot_receipt")"
  snapshot_original_mode_sha="$(jq -r '.original_mode_inventory_sha256' "$snapshot_receipt")"
  snapshot_top_level_sha="$(jq -r '.top_level_inventory_sha256' "$snapshot_receipt")"
  snapshot_sidecar_sha="$(jq -r '.sqlite_sidecar_inventory_sha256' "$snapshot_receipt")"
  snapshot_key_sha="$(jq -r '.key_inventory_sha256' "$snapshot_receipt")"
  snapshot_hardlink_sha="$(jq -r '.hardlink_topology_inventory_sha256' "$snapshot_receipt")"
  snapshot_acl_sha="$(jq -r '.acl_inventory_sha256' "$snapshot_receipt")"
  snapshot_writer_barrier="$(jq -c '.writer_barrier' "$snapshot_receipt")"
  if [[ "$(jq -r '.recutover_predecessor == null' "$snapshot_receipt")" != true ]]; then
    snapshot_predecessor_receipt="$(jq -r '.recutover_predecessor.receipt' "$snapshot_receipt")"
    snapshot_predecessor_sha="$(jq -r '.recutover_predecessor.sha256' "$snapshot_receipt")"
    snapshot_predecessor_plan_sha="$(jq -r '.recutover_predecessor.plan_sha256' "$snapshot_receipt")"
    snapshot_predecessor_sequence="$(jq -r '.recutover_predecessor.sequence' "$snapshot_receipt")"
  fi
fi
for receipt_path in "$output_receipt" "$output_soak_receipt"; do
  [[ -z "$receipt_path" || ( "$receipt_path" == /* && "$receipt_path" != "/" && "$receipt_path" != */ ) ]] || usage
  [[ -z "$receipt_path" || ( ! -e "$receipt_path" && ! -L "$receipt_path" ) ]] || {
    echo "refusing to replace canary evidence: $receipt_path" >&2
    exit 1
  }
  if [[ -n "$source_state_root" && ( "$receipt_path" == "$source_state_root" || "$receipt_path" == "$source_state_root/"* ) ]]; then
    echo "canary evidence must remain outside the source state root" >&2
    exit 1
  fi
done
if lsof -nP -iTCP:17373 -sTCP:LISTEN 2>/dev/null | grep -q .; then
  echo "isolated canary port 17373 is already in use" >&2
  exit 1
fi

tmp_root="${TMPDIR:-/tmp}"
root="$(mktemp -d "${tmp_root%/}/hepta-vnext-canary.XXXXXX")"
server_pid=""
cleanup() {
  if [[ -n "$server_pid" ]]; then
    kill "$server_pid" >/dev/null 2>&1 || true
    wait "$server_pid" >/dev/null 2>&1 || true
  fi
  chflags -R nouchg,noschg "$root" 2>/dev/null || true
  chmod -RN "$root" 2>/dev/null || true
  chmod -R u+w "$root" 2>/dev/null || true
  rm -rf "$root"
}
trap cleanup EXIT
state_root="$root/state"
runtime_root="$state_root/runtime-v2"
keys_root="$runtime_root/keys"
install_root="$root/install"
release="$root/release"
launch_agents="$root/LaunchAgents"
inventory_tree() {
  local tree_root="$1" output="$2"
  [[ -d "$tree_root" && ! -L "$tree_root" ]] || return 1
  (
    cd "$tree_root"
    find . -print | LC_ALL=C sort | while IFS= read -r item; do
      [[ ! -L "$item" ]] || { echo "symlink rejected in inventory: $item" >&2; exit 1; }
      if [[ -f "$item" ]]; then
        printf '%s|file|%s|%s\n' "$item" "$(stat -f '%Lp|%u|%g|%z|%m|%c|%l' "$item")" "$(shasum -a 256 "$item" | awk '{print $1}')"
      elif [[ -d "$item" ]]; then
        printf '%s|directory|%s\n' "$item" "$(stat -f '%Lp|%u|%g|%z|%m|%c' "$item")"
      else
        echo "unsupported state entry: $item" >&2
        exit 1
      fi
    done
  ) >"$output"
}

payload_inventory() {
  local tree_root="$1" output="$2"
  (
    cd "$tree_root"
    find . -type f -print | LC_ALL=C sort | while IFS= read -r item; do
      printf '%s|%s|%s|%s\n' "$item" "$(stat -f '%Lp' "$item")" "$(stat -f '%z' "$item")" "$(shasum -a 256 "$item" | awk '{print $1}')"
    done
  ) >"$output"
}

acl_sha256() {
  /bin/ls -lden "$1" | sed '1d' | shasum -a 256 | awk '{print $1}'
}

xattr_sha256() {
  local item="$1" name names
  names="$(/usr/bin/xattr "$item" 2>/dev/null || true)"
  {
    if [[ -n "$names" ]]; then
      printf '%s\n' "$names" | LC_ALL=C sort | while IFS= read -r name; do
        [[ "$name" != *$'\r'* && "$name" != *'|'* ]] || exit 1
        printf '%s|%s\n' "$name" "$(/usr/bin/xattr -p "$name" "$item" | shasum -a 256 | awk '{print $1}')"
      done
    fi
  } | shasum -a 256 | awk '{print $1}'
}

portable_inventory_v2() {
  local tree_root="$1" output="$2"
  (
    cd "$tree_root"
    find . -print | LC_ALL=C sort | while IFS= read -r item; do
      [[ ! -L "$item" && "$item" != *$'\n'* && "$item" != *$'\r'* && "$item" != *'|'* ]] || exit 1
      if [[ -f "$item" ]]; then
        printf '%s|file|%s|%s|%s|%s\n' "$item" \
          "$(stat -f '%Lp|%u|%g|%z|%m|%l|%f' "$item")" \
          "$(acl_sha256 "$item")" "$(xattr_sha256 "$item")" "$(sha256_file "$item")"
      elif [[ -d "$item" ]]; then
        printf '%s|directory|%s|%s|%s\n' "$item" \
          "$(stat -f '%Lp|%u|%g|%m|%f' "$item")" \
          "$(acl_sha256 "$item")" "$(xattr_sha256 "$item")"
      else
        exit 1
      fi
    done
  ) >"$output"
}

portable_inventory_v3() { portable_inventory_v2 "$@"; }

acl_inventory_v3() {
  local tree_root="$1" output="$2" item item_type acl_lines
  (
    cd "$tree_root"
    find . -print | LC_ALL=C sort | while IFS= read -r item; do
      [[ ! -L "$item" && "$item" != *$'\n'* && "$item" != *$'\r'* && "$item" != *'|'* ]] || exit 1
      if [[ -f "$item" ]]; then item_type='file'
      elif [[ -d "$item" ]]; then item_type='directory'
      else exit 1
      fi
      acl_lines="$(/bin/ls -lden "$item" | sed '1d')" || exit 1
      if [[ -n "$acl_lines" ]]; then
        ! grep -Eq '[[:space:]]allow[[:space:]]' <<<"$acl_lines" || exit 1
        ! grep -Ev '^[[:space:]]*[0-9]+: .*([[:space:]])deny([[:space:]])' <<<"$acl_lines" | grep -q . || exit 1
      fi
      printf '%s|%s|%s\n' "$item" "$item_type" "$(acl_sha256 "$item")"
    done
  ) >"$output"
}

mode_inventory_v3() {
  local tree_root="$1" output="$2" item item_type raw_mode mode_bits
  (
    cd "$tree_root"
    find . -print | LC_ALL=C sort | while IFS= read -r item; do
      [[ ! -L "$item" && "$item" != *$'\n'* && "$item" != *$'\r'* && "$item" != *'|'* ]] || exit 1
      if [[ -f "$item" ]]; then item_type="file"
      elif [[ -d "$item" ]]; then item_type="directory"
      else exit 1
      fi
      raw_mode="$(stat -f '%p' "$item")" || exit 1
      mode_bits="$((8#$raw_mode & 07777))"
      printf '%s|%s|%04o\n' "$item" "$item_type" "$mode_bits"
    done
  ) >"$output"
}

hardlink_topology_inventory_v2() {
  local tree_root="$1" output="$2" raw
  raw="$(mktemp "$root/hardlink-topology.XXXXXX")"
  if ! (
    cd "$tree_root"
    find . -type f -print | LC_ALL=C sort | while IFS= read -r item; do
      [[ "$item" != *$'\n'* && "$item" != *$'\r'* && "$item" != *'|'* ]] || exit 1
      printf '%s|%s|%s|%s\n' "$(stat -f '%d' "$item")" "$(stat -f '%i' "$item")" "$(stat -f '%l' "$item")" "$item"
    done
  ) >"$raw"; then
    rm -f "$raw"
    return 1
  fi
  if ! awk -F '|' '
    {
      key = $1 SUBSEP $2
      rows += 1; file[rows] = $4; row_key[rows] = key; observed[key] += 1
      if (!(key in primary)) { primary[key] = $4; declared[key] = $3 }
      else if (declared[key] != $3) invalid = 1
    }
    END {
      for (key in observed) if (declared[key] != observed[key]) invalid = 1
      if (invalid) exit 1
      for (row = 1; row <= rows; row++) {
        key = row_key[row]
        printf "%s|%s|%d\n", file[row], primary[key], observed[key]
      }
    }
  ' "$raw" >"$output"; then
    rm -f "$raw" "$output"
    return 1
  fi
  rm -f "$raw"
}

hardlink_topology_inventory_v3() { hardlink_topology_inventory_v2 "$@"; }

copy_full_tree_v2() {
  local source="$1" destination="$2"
  [[ -d "$source" && ! -L "$source" && ! -e "$destination" && ! -L "$destination" ]] || return 1
  mkdir "$destination"
  (cd "$source" && /usr/bin/tar --acls --xattrs --fflags -cf - .) \
    | (cd "$destination" && /usr/bin/tar --acls --xattrs --fflags -xpf -) \
    || return 1
  /usr/bin/touch -r "$source" "$destination" || return 1
}

copy_full_tree_v3() { copy_full_tree_v2 "$@"; }

sha256_file() { shasum -a 256 "$1" | awk '{print $1}'; }

write_private_new() {
  local destination="$1" source="$2" parent staged source_sha
  [[ ! -e "$destination" && ! -L "$destination" ]] || return 1
  parent="$(dirname "$destination")"; mkdir -p "$parent"; chmod 0700 "$parent"
  staged="$(mktemp "$parent/.hepta-canary-evidence.XXXXXX")"
  trap 'rm -f "$staged"' RETURN
  source_sha="$(sha256_file "$source")"
  cp "$source" "$staged"; chmod -N "$staged" 2>/dev/null || true; /usr/bin/xattr -c "$staged" 2>/dev/null || true; chflags nouchg,noschg,nohidden "$staged" 2>/dev/null || true; chmod 0400 "$staged"
  [[ "$(sha256_file "$staged")" == "$source_sha" && "$(stat -f '%l' "$staged")" == 1 ]] || return 1
  python3 - "$staged" <<'PY'
import os, sys
fd = os.open(sys.argv[1], os.O_RDONLY)
try: os.fsync(fd)
finally: os.close(fd)
PY
  ln "$staged" "$destination"
  # The staged artifact is intentionally 0400; use non-interactive cleanup so
  # a PTY-backed soak cannot block on a write-protection confirmation prompt.
  rm -f "$staged"; staged=""
  python3 - "$parent" <<'PY'
import os, sys
fd = os.open(sys.argv[1], os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try: os.fsync(fd)
finally: os.close(fd)
PY
  trap - RETURN
}

production_inventory() {
  local output="$1" launch_root="$HOME/Library/LaunchAgents" plist listener executable
  : >"$output"
  for plist in "$launch_root/ai.hepta.gateway.plist" "$launch_root/ai.hepta.installed-live-watchdog.plist"; do
    if [[ -f "$plist" && ! -L "$plist" ]]; then
      printf 'plist|%s|%s\n' "$(basename "$plist")" "$(sha256_file "$plist")" >>"$output"
    else
      printf 'plist|%s|absent\n' "$(basename "$plist")" >>"$output"
    fi
  done
  listener="$(lsof -nP -iTCP:7373 -sTCP:LISTEN -t 2>/dev/null | LC_ALL=C sort -u || true)"
  if [[ -z "$listener" ]]; then
    printf 'listener|7373|absent\n' >>"$output"
  else
    while IFS= read -r listener_pid; do
      executable="$(lsof -a -p "$listener_pid" -d txt -Fn 2>/dev/null | sed -n 's/^n//p' | head -1)"
      [[ -f "$executable" ]] || { echo "cannot identify production listener executable" >&2; return 1; }
      printf 'listener|7373|%s\n' "$(sha256_file "$executable")" >>"$output"
    done <<<"$listener"
  fi
}

live_before=""; live_after=""; live_payload=""; copy_payload=""; live_modes=""; copy_modes=""; live_acls=""; copy_acls=""; live_hardlinks=""; copy_hardlinks=""; full_state_source_copied=false
production_before="$root/production-before.inventory"
production_after="$root/production-after.inventory"
production_inventory "$production_before"
mkdir -p "$state_root" "$launch_agents"
chmod 0700 "$state_root" "$launch_agents"
if [[ -n "$source_state_root" ]]; then
  source_runtime="$source_state_root/runtime-v2"
  [[ -d "$source_runtime" && ! -L "$source_runtime" ]] || {
    echo "source runtime-v2 is missing or unsafe" >&2
    exit 1
  }
  live_before="$root/live-before.inventory"
  live_after="$root/live-after.inventory"
  live_payload="$root/live.payload"
  copy_payload="$root/copy.payload"
  inventory_tree "$source_state_root" "$live_before"
  if [[ "$snapshot_schema" == hepta_vnext_state_snapshot_receipt_v3 ]]; then
    rmdir "$state_root"
    copy_full_tree_v3 "$source_state_root" "$state_root"
    full_state_source_copied=true
  else
    cp -pR "$source_runtime" "$state_root/runtime-v2"
  fi
  inventory_tree "$source_state_root" "$root/live-after-copy.inventory"
  diff -u "$live_before" "$root/live-after-copy.inventory" >/dev/null || {
    echo "source state changed while making the private copy" >&2
    exit 1
  }
  if [[ "$snapshot_schema" == hepta_vnext_state_snapshot_receipt_v3 ]]; then
    portable_inventory_v3 "$source_state_root" "$live_payload"
    portable_inventory_v3 "$state_root" "$copy_payload"
    live_modes="$root/live.modes"
    copy_modes="$root/copy.modes"
    mode_inventory_v3 "$source_state_root" "$live_modes"
    mode_inventory_v3 "$state_root" "$copy_modes"
    live_acls="$root/live.acls"
    copy_acls="$root/copy.acls"
    acl_inventory_v3 "$source_state_root" "$live_acls"
    acl_inventory_v3 "$state_root" "$copy_acls"
    live_hardlinks="$root/live.hardlinks"
    copy_hardlinks="$root/copy.hardlinks"
    hardlink_topology_inventory_v3 "$source_state_root" "$live_hardlinks"
    hardlink_topology_inventory_v3 "$state_root" "$copy_hardlinks"
  else
    payload_inventory "$source_runtime" "$live_payload"
    payload_inventory "$runtime_root" "$copy_payload"
  fi
  diff -u "$live_payload" "$copy_payload" >/dev/null || {
    echo "private state copy differs from source bytes or modes" >&2
    exit 1
  }
  if [[ "$snapshot_schema" == hepta_vnext_state_snapshot_receipt_v3 \
    && "$(sha256_file "$live_payload")" != "$snapshot_portable_payload_sha" ]]; then
    echo "private full-state canary copy is not bound to the snapshot portable inventory" >&2
    exit 1
  fi
  if [[ "$snapshot_schema" == hepta_vnext_state_snapshot_receipt_v3 \
    && ( "$(sha256_file "$live_acls")" != "$snapshot_acl_sha" \
      || "$(sha256_file "$copy_acls")" != "$snapshot_acl_sha" ) ]]; then
    echo "private full-state canary copy changed the deny-only ACL inventory" >&2
    exit 1
  fi
  if [[ "$snapshot_schema" == hepta_vnext_state_snapshot_receipt_v3 \
    && ( "$(sha256_file "$live_modes")" != "$snapshot_original_mode_sha" \
      || "$(sha256_file "$copy_modes")" != "$snapshot_original_mode_sha" ) ]]; then
    echo "private full-state canary copy changed the snapshot per-entry modes" >&2
    exit 1
  fi
  if [[ "$snapshot_schema" == hepta_vnext_state_snapshot_receipt_v3 \
    && ( "$(sha256_file "$live_hardlinks")" != "$snapshot_hardlink_sha" \
      || "$(sha256_file "$copy_hardlinks")" != "$snapshot_hardlink_sha" \
      || ! -s "$live_hardlinks" ) ]]; then
    echo "private full-state canary copy changed the snapshot hardlink alias topology" >&2
    exit 1
  fi
else
  mkdir -p "$keys_root"
  chmod 0700 "$runtime_root" "$keys_root"
  for key in runtime-integrity.key preference-integrity.key preference-ingress-auth.key; do
    printf '%064d\n' 0 >"$keys_root/$key"
    chmod 0600 "$keys_root/$key"
  done
  for database in outcomes.sqlite3 preferences.sqlite3; do
    sqlite3 "$runtime_root/$database" >/dev/null <<'SQL'
PRAGMA journal_mode=DELETE;
CREATE TABLE hepta_v2_schema (singleton INTEGER PRIMARY KEY, version INTEGER NOT NULL);
INSERT INTO hepta_v2_schema VALUES (1, 5);
CREATE TABLE hepta_v2_write_lock (singleton INTEGER PRIMARY KEY, generation INTEGER NOT NULL);
INSERT INTO hepta_v2_write_lock VALUES (1, 0);
CREATE TABLE hepta_v2_integrity (singleton INTEGER PRIMARY KEY, algorithm TEXT NOT NULL, key_id TEXT NOT NULL);
INSERT INTO hepta_v2_integrity VALUES (1, 'hmac-sha256-v1', 'sha256:4a75c5baf4bd27a70e3a28856ec5ff1e54c91c7c9bb8d3151b1a9aae279ff4bc');
CREATE TABLE hepta_v2_outcome_records (receipt_id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL, payload_json TEXT NOT NULL, storage_hash TEXT NOT NULL);
CREATE TABLE hepta_v2_outcome_intents (attempt_id TEXT PRIMARY KEY, receipt_id TEXT NOT NULL, state TEXT NOT NULL, payload_json TEXT NOT NULL, storage_hash TEXT NOT NULL);
CREATE TABLE hepta_v2_execution_intents (attempt_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL, payload_json TEXT NOT NULL, storage_hash TEXT NOT NULL);
CREATE TABLE hepta_v2_execution_effect_acks (attempt_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL, effect_plan_hash TEXT NOT NULL, payload_json TEXT NOT NULL, storage_hash TEXT NOT NULL);
CREATE TABLE hepta_v2_preference_genesis (preference_id TEXT NOT NULL, subject_id TEXT NOT NULL, payload_json TEXT NOT NULL, storage_hash TEXT NOT NULL);
CREATE TABLE hepta_v2_preference_heads (preference_id TEXT NOT NULL, subject_id TEXT NOT NULL, payload_json TEXT NOT NULL, storage_hash TEXT NOT NULL);
CREATE TABLE hepta_v2_preference_transitions (sequence INTEGER PRIMARY KEY, transition_id TEXT NOT NULL, evidence_id TEXT NOT NULL, receipt_id TEXT NOT NULL, preference_id TEXT NOT NULL, subject_id TEXT NOT NULL, payload_json TEXT NOT NULL, storage_hash TEXT NOT NULL);
SQL
    chmod 0600 "$runtime_root/$database"
  done
  printf '%s\n' '{"payload":{"version":1,"generation":0,"snapshot":{"sessions":[],"memories":[],"transcripts":[]}},"integrity_tag":"hmac-sha256:5fec32ebcd9fa7ee6c5b30ede59ba942a0e9760123594318611bf7a258e71b8b"}' >"$runtime_root/runtime-state.json"
  chmod 0600 "$runtime_root/runtime-state.json"
fi

before_inventory="$root/state-before.inventory"
after_inventory="$root/state-after.inventory"
inventory_tree "$runtime_root" "$before_inventory"

"$binary" --serve-ui 127.0.0.1:17373 --state-root "$state_root" \
  >"$root/gateway.stdout" 2>"$root/gateway.stderr" &
server_pid=$!
ready=false
for _ in $(seq 1 300); do
  if curl --fail --silent --max-time 1 http://127.0.0.1:17373/healthz >/dev/null 2>&1; then
    ready=true
    break
  fi
  if ! kill -0 "$server_pid" >/dev/null 2>&1; then
    sed -n '1,160p' "$root/gateway.stderr" >&2
    echo "canary gateway exited before readiness" >&2
    exit 1
  fi
  sleep 0.1
done
[[ "$ready" == "true" ]] || {
  sed -n '1,160p' "$root/gateway.stderr" >&2
  echo "canary gateway did not become ready" >&2
  exit 1
}

"$script_dir/hepta-immutable-release-tree" materialize \
  --binary "$binary" \
  --destination "$release" \
  --state-root "$state_root" \
  --install-root "$install_root" \
  --gateway-label ai.hepta.vnext.canary \
  --watchdog-label ai.hepta.vnext.canary.watchdog \
  --listen-port 17373 \
  --source-commit "$source_commit" >/dev/null
"$release/scripts/hepta-generation-pointer" initialize \
  --install-root "$install_root" \
  --manifest "$release/manifest.json" >/dev/null
"$release/scripts/hepta-install-live-gateway" \
  --manifest "$release/manifest.json" \
  --launch-agent-root "$launch_agents" >/dev/null
"$release/scripts/hepta-install-live-watchdog" \
  --manifest "$release/manifest.json" \
  --launch-agent-root "$launch_agents" >/dev/null
watchdog="$("$release/scripts/hepta-watchdog.sh" --manifest "$release/manifest.json")"
soak="$("$release/scripts/hepta-live-soak.sh" --manifest "$release/manifest.json" --samples 3 --interval-seconds 0)"
jq -e '.status == "ready" and .authority_all_closed == true' <<<"$watchdog" >/dev/null
jq -e '.status == "ready" and .passed == 3 and .failed == 0 and .authority_all_closed == true' <<<"$soak" >/dev/null

inventory_tree "$runtime_root" "$after_inventory"
diff -u "$before_inventory" "$after_inventory" >/dev/null || {
  echo "read-only canary changed its state fixture" >&2
  exit 1
}
source_state_copied=false
source_unchanged=true
if [[ -n "$source_state_root" ]]; then
  source_state_copied=true
  inventory_tree "$source_state_root" "$live_after"
  diff -u "$live_before" "$live_after" >/dev/null || {
    echo "source state changed during the private-copy canary" >&2
    exit 1
  }
fi
for protected_route in \
  /api/hepta/control/status \
  /api/hepta/telegram/status \
  /api/hepta/channels \
  /api/hepta/plugins; do
  response_code="$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 5 "http://127.0.0.1:17373$protected_route")"
  [[ "$response_code" == "404" ]] || {
    echo "legacy or protected route remained reachable: $protected_route ($response_code)" >&2
    exit 1
  }
done
post_code="$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 5 \
  -X POST http://127.0.0.1:17373/api/hepta/runtime)"
[[ "$post_code" == "405" ]] || { echo "read-only canary accepted POST" >&2; exit 1; }

production_inventory "$production_after"
diff -u "$production_before" "$production_after" >/dev/null || {
  echo "production 7373 or LaunchAgent inventory changed during canary" >&2
  exit 1
}

soak_tmp="$root/soak-receipt.json"
canary_tmp="$root/canary-receipt.json"
printf '%s\n' "$soak" >"$soak_tmp"
jq -n \
  --arg binary_sha256 "$(shasum -a 256 "$binary" | awk '{print $1}')" \
  --arg manifest "$release/manifest.json" \
  --arg manifest_sha256 "$(shasum -a 256 "$release/manifest.json" | awk '{print $1}')" \
  --arg canary_state_root "$state_root" \
  --arg target_manifest "$target_manifest" \
  --arg target_manifest_sha256 "$target_manifest_sha" \
  --arg snapshot_receipt_sha256 "$snapshot_receipt_sha" \
  --arg snapshot_schema "$snapshot_schema" \
  --arg snapshot_profile "$snapshot_profile" \
  --arg snapshot_mode_profile "$snapshot_mode_profile" \
  --arg snapshot_acl_profile "$snapshot_acl_profile" \
  --arg snapshot_id "$snapshot_id" \
  --arg snapshot_source_identity_sha256 "$snapshot_source_identity_sha" \
  --arg snapshot_portable_payload_sha256 "$snapshot_portable_payload_sha" \
  --arg snapshot_original_mode_sha256 "$snapshot_original_mode_sha" \
  --arg snapshot_top_level_inventory_sha256 "$snapshot_top_level_sha" \
  --arg snapshot_sqlite_sidecar_inventory_sha256 "$snapshot_sidecar_sha" \
  --arg snapshot_key_inventory_sha256 "$snapshot_key_sha" \
  --arg snapshot_hardlink_topology_inventory_sha256 "$snapshot_hardlink_sha" \
  --arg snapshot_acl_inventory_sha256 "$snapshot_acl_sha" \
  --arg snapshot_predecessor_receipt "$snapshot_predecessor_receipt" \
  --arg snapshot_predecessor_sha256 "$snapshot_predecessor_sha" \
  --arg snapshot_predecessor_plan_sha256 "$snapshot_predecessor_plan_sha" \
  --arg snapshot_predecessor_sequence "$snapshot_predecessor_sequence" \
  --argjson snapshot_writer_barrier "$snapshot_writer_barrier" \
  --arg source_commit "$source_commit" \
  --arg source_state_root "$source_state_root" \
  --arg source_inventory_sha256 "$(if [[ -n "$live_before" ]]; then sha256_file "$live_before"; else sha256_file "$before_inventory"; fi)" \
  --arg copy_payload_sha256 "$(if [[ -n "$copy_payload" ]]; then sha256_file "$copy_payload"; else sha256_file "$before_inventory"; fi)" \
  --arg copy_mode_inventory_sha256 "$(if [[ -n "$copy_modes" ]]; then sha256_file "$copy_modes"; else printf ''; fi)" \
  --arg copy_acl_inventory_sha256 "$(if [[ -n "$copy_acls" ]]; then sha256_file "$copy_acls"; else printf ''; fi)" \
  --arg soak_receipt_sha256 "$(sha256_file "$soak_tmp")" \
  --arg production_inventory_sha256 "$(sha256_file "$production_before")" \
  --argjson source_state_copied "$source_state_copied" \
  --argjson source_unchanged "$source_unchanged" \
  --argjson full_state_source_copied "$full_state_source_copied" \
  '{schema:(if $snapshot_schema == "hepta_vnext_state_snapshot_receipt_v3" then "hepta_vnext_runtime_canary_e2e_v3" else "hepta_vnext_runtime_canary_e2e_v1" end),status:"ready",listen_addr:"127.0.0.1:17373",source_commit:$source_commit,source_tree_clean:true,binary_sha256:$binary_sha256,manifest:$manifest,manifest_sha256:$manifest_sha256,canary_state_root:$canary_state_root,target_manifest:(if $target_manifest=="" then null else $target_manifest end),target_manifest_sha256:(if $target_manifest_sha256=="" then null else $target_manifest_sha256 end),snapshot_receipt_sha256:(if $snapshot_receipt_sha256=="" then null else $snapshot_receipt_sha256 end),snapshot_schema:(if $snapshot_schema=="" then null else $snapshot_schema end),snapshot_profile:(if $snapshot_profile=="" then null else $snapshot_profile end),snapshot_mode_profile:(if $snapshot_mode_profile=="" then null else $snapshot_mode_profile end),snapshot_acl_profile:(if $snapshot_acl_profile=="" then null else $snapshot_acl_profile end),snapshot_id:(if $snapshot_id=="" then null else $snapshot_id end),snapshot_writer_barrier:$snapshot_writer_barrier,snapshot_source_identity_inventory_sha256:(if $snapshot_source_identity_sha256=="" then null else $snapshot_source_identity_sha256 end),snapshot_portable_payload_inventory_sha256:(if $snapshot_portable_payload_sha256=="" then null else $snapshot_portable_payload_sha256 end),snapshot_original_mode_inventory_sha256:(if $snapshot_original_mode_sha256=="" then null else $snapshot_original_mode_sha256 end),snapshot_acl_inventory_sha256:(if $snapshot_acl_inventory_sha256=="" then null else $snapshot_acl_inventory_sha256 end),snapshot_top_level_inventory_sha256:(if $snapshot_top_level_inventory_sha256=="" then null else $snapshot_top_level_inventory_sha256 end),snapshot_sqlite_sidecar_inventory_sha256:(if $snapshot_sqlite_sidecar_inventory_sha256=="" then null else $snapshot_sqlite_sidecar_inventory_sha256 end),snapshot_key_inventory_sha256:(if $snapshot_key_inventory_sha256=="" then null else $snapshot_key_inventory_sha256 end),snapshot_hardlink_topology_inventory_sha256:(if $snapshot_hardlink_topology_inventory_sha256=="" then null else $snapshot_hardlink_topology_inventory_sha256 end),snapshot_recutover_predecessor:(if $snapshot_predecessor_sha256=="" then null else {receipt:$snapshot_predecessor_receipt,sha256:$snapshot_predecessor_sha256,plan_sha256:$snapshot_predecessor_plan_sha256,sequence:($snapshot_predecessor_sequence|tonumber)} end),source_state_root:(if $source_state_root=="" then null else $source_state_root end),source_inventory_sha256:$source_inventory_sha256,copy_payload_sha256:$copy_payload_sha256,copy_mode_inventory_sha256:(if $copy_mode_inventory_sha256=="" then null else $copy_mode_inventory_sha256 end),copy_acl_inventory_sha256:(if $copy_acl_inventory_sha256=="" then null else $copy_acl_inventory_sha256 end),soak_receipt_sha256:$soak_receipt_sha256,soak_samples:3,production_inventory_sha256:$production_inventory_sha256,schema_v5_open_existing:true,keyed_integrity_verified:true,immutable_query_only:true,requires_empty_wal:true,source_state_copied:$source_state_copied,full_state_source_copied:$full_state_source_copied,full_snapshot_receipt_bound:($snapshot_schema == "hepta_vnext_state_snapshot_receipt_v3"),writer_admission_closed:($snapshot_schema == "hepta_vnext_state_snapshot_receipt_v3"),all_top_level_entries_copied:($snapshot_schema == "hepta_vnext_state_snapshot_receipt_v3"),original_modes_preserved:($snapshot_schema == "hepta_vnext_state_snapshot_receipt_v3"),deny_only_acls_preserved:($snapshot_schema == "hepta_vnext_state_snapshot_receipt_v3"),hardlinks_preserved:($snapshot_schema == "hepta_vnext_state_snapshot_receipt_v3"),source_unchanged:$source_unchanged,copy_unchanged:true,metadata_and_hash_checked:true,installer_dry_run:true,protected_routes_absent:true,non_get_rejected:true,authority_all_closed:true,production_service_changed:false}' >"$canary_tmp"
if [[ -n "$output_receipt" ]]; then
  write_private_new "$output_soak_receipt" "$soak_tmp"
  write_private_new "$output_receipt" "$canary_tmp"
fi
cat "$canary_tmp"
