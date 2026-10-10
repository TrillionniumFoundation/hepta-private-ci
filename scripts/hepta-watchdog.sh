#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
usage: hepta-watchdog.sh --manifest PATH [--url http://127.0.0.1:PORT]

Read-only validation only: verifies immutable bytes, the generation pointer,
health, schema-v5 open-existing status, and closed authority bits. It never
restarts the service.
EOF
  exit 64
}

manifest=""; live_url=""
while (( $# > 0 )); do
  case "$1" in
    --manifest) shift; [[ $# -gt 0 ]] || usage; manifest="$1" ;;
    --url) shift; [[ $# -gt 0 ]] || usage; live_url="$1" ;;
    *) usage ;;
  esac
  shift
done
[[ -n "$manifest" ]] || usage
manifest="$(realpath "$manifest")"
release="$(dirname "$manifest")"
verify_relative="$(jq -r '.watchdog.verify_tool' "$manifest")"
[[ "$verify_relative" == "scripts/hepta-immutable-release-tree" ]] || {
  echo "manifest declares an unsupported verifier" >&2
  exit 1
}
verifier="$release/$verify_relative"
"$verifier" verify --manifest "$manifest" >/dev/null
state_root="$(jq -r '.runtime.state_root' "$manifest")"
install_root="$(jq -r '.runtime.install_root' "$manifest")"
listen_port="$(jq -r '.runtime.listen_port' "$manifest")"
live_url="${live_url:-http://127.0.0.1:$listen_port}"
[[ "$live_url" == "http://127.0.0.1:$listen_port" ]] || {
  echo "watchdog URL must match the manifest-bound loopback port" >&2
  exit 1
}
generation="$("$release/scripts/hepta-generation-pointer" verify \
  --install-root "$install_root" --manifest "$manifest")"
health="$(curl --fail --silent --show-error --max-time 5 "$live_url/healthz")"
runtime="$(curl --fail --silent --show-error --max-time 5 "$live_url/api/hepta/runtime")"
jq -e '.product == "hepta" and .status == "ok"' <<<"$health" >/dev/null || {
  echo "gateway health response is invalid" >&2
  exit 1
}
jq -e \
  --arg state_root "$state_root" '
    .schema == "hepta_vnext_live_runtime_status_v1"
    and .product == "hepta"
    and .status == "ready"
    and .state_root == $state_root
    and .state.schema_version == 5
    and .state.open_mode == "immutable-query-only-open-existing"
    and .state.integrity_verification == "hmac-sha256-v1-key-id-and-row-macs-verified"
    and .authority.telegram == false
    and .authority.outbound == false
    and .authority.model_invocation == false
    and .authority.operator_mutation == false
    and .authority.enforce == false
    and .authority.promotion == false
    and .authority.retirement == false
    and .authority.automatic_transition == false
  ' <<<"$runtime" >/dev/null || {
  echo "gateway runtime response is not the closed schema-v5 live shell" >&2
  exit 1
}
jq -cn \
  --arg manifest "$manifest" \
  --arg manifest_sha256 "$(shasum -a 256 "$manifest" | awk '{print $1}')" \
  --arg live_url "$live_url" \
  --arg state_root "$state_root" \
  --arg active_artifact_sha256 "$(jq -r '.artifact_sha256' <<<"$generation")" \
  '{schema:"hepta_vnext_live_watchdog_v1",status:"ready",manifest:$manifest,manifest_sha256:$manifest_sha256,live_url:$live_url,state_root:$state_root,active_artifact_sha256:$active_artifact_sha256,schema_v5_open_existing:true,keyed_integrity_verified:true,immutable_query_only:true,authority_all_closed:true,gateway_restarted:false,generation_changed:false}'
