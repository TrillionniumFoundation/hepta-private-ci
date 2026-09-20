#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
usage: hepta-live-soak.sh --manifest PATH [--url http://127.0.0.1:PORT] [--samples N] [--interval-seconds N]

The manifest is required so the soak binds one exact active generation, state
root, artifact, and loopback port (recommended canary port: 17373).
EOF
  exit 64
}

manifest=""; live_url=""; samples="${HEPTA_SOAK_SAMPLES:-12}"; interval="${HEPTA_SOAK_INTERVAL_SECONDS:-1}"
while (( $# > 0 )); do
  case "$1" in
    --manifest) shift; [[ $# -gt 0 ]] || usage; manifest="$1" ;;
    --url) shift; [[ $# -gt 0 ]] || usage; live_url="$1" ;;
    --samples) shift; [[ $# -gt 0 ]] || usage; samples="$1" ;;
    --interval-seconds) shift; [[ $# -gt 0 ]] || usage; interval="$1" ;;
    *) usage ;;
  esac
  shift
done
if ! [[ "$samples" =~ ^[0-9]+$ ]] || ! (( samples >= 1 && samples <= 10000 )); then
  echo "--samples must be from 1 through 10000" >&2
  exit 1
fi
[[ "$interval" =~ ^[0-9]+([.][0-9]+)?$ ]] || {
  echo "--interval-seconds must be a non-negative number" >&2
  exit 1
}
[[ -n "$manifest" ]] || usage
manifest="$(realpath "$manifest")"
release="$(dirname "$manifest")"
verify_relative="$(jq -r '.watchdog.verify_tool' "$manifest")"
[[ "$verify_relative" == "scripts/hepta-immutable-release-tree" ]] || {
  echo "manifest declares an unsupported verifier" >&2
  exit 1
}
"$release/$verify_relative" verify --manifest "$manifest" >/dev/null
state_root="$(jq -r '.runtime.state_root' "$manifest")"
install_root="$(jq -r '.runtime.install_root' "$manifest")"
listen_port="$(jq -r '.runtime.listen_port' "$manifest")"
generation="$("$release/scripts/hepta-generation-pointer" verify \
  --install-root "$install_root" --manifest "$manifest")"
live_url="${live_url:-http://127.0.0.1:$listen_port}"
[[ "$live_url" == "http://127.0.0.1:$listen_port" ]] || {
  echo "soak URL differs from manifest-bound loopback port" >&2
  exit 1
}

started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
passed=0
for (( sample = 1; sample <= samples; sample++ )); do
  health="$(curl --fail --silent --show-error --max-time 5 "$live_url/healthz")"
  runtime="$(curl --fail --silent --show-error --max-time 5 "$live_url/api/hepta/runtime")"
  jq -e '.product == "hepta" and .status == "ok"' <<<"$health" >/dev/null
  jq_filter='
    .schema == "hepta_vnext_live_runtime_status_v1"
    and .product == "hepta"
    and .status == "ready"
    and .state.schema_version == 5
    and .state.open_mode == "immutable-query-only-open-existing"
    and .state.integrity_verification == "hmac-sha256-v1-key-id-and-row-macs-verified"
    and (.authority | keys == ["automatic_transition","enforce","model_invocation","operator_mutation","outbound","promotion","retirement","telegram"])
    and .authority.telegram == false
    and .authority.outbound == false
    and .authority.model_invocation == false
    and .authority.operator_mutation == false
    and .authority.enforce == false
    and .authority.promotion == false
    and .authority.retirement == false
    and .authority.automatic_transition == false
  '
  if [[ -n "$state_root" ]]; then
    jq -e --arg state_root "$state_root" "($jq_filter) and .state_root == \$state_root" <<<"$runtime" >/dev/null
  else
    jq -e "$jq_filter" <<<"$runtime" >/dev/null
  fi
  passed=$((passed + 1))
  if (( sample < samples )); then
    sleep "$interval"
  fi
done
finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
jq -cn \
    --arg manifest "$manifest" \
    --arg manifest_sha256 "$(shasum -a 256 "$manifest" | awk '{print $1}')" \
    --arg active_artifact_sha256 "$(jq -r '.artifact_sha256' <<<"$generation")" \
  --arg live_url "$live_url" \
  --arg state_root "$state_root" \
  --arg started_at "$started_at" \
  --arg finished_at "$finished_at" \
  --argjson samples "$samples" \
  --argjson passed "$passed" \
    '{schema:"hepta_vnext_live_soak_v1",status:"ready",manifest:$manifest,manifest_sha256:$manifest_sha256,active_artifact_sha256:$active_artifact_sha256,live_url:$live_url,state_root:$state_root,started_at:$started_at,finished_at:$finished_at,samples:$samples,passed:$passed,failed:($samples-$passed),schema_v5_open_existing:true,keyed_integrity_verified:true,immutable_query_only:true,authority_all_closed:true,service_changed:false}'
