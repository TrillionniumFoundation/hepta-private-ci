#!/bin/zsh
set -euo pipefail

qualification_root=/Volumes/T5/hepta-vnext/artifacts/receipts/qualification-3110c5aba5-final-20260810T192902Z
product_root=/Volumes/T5/hepta-vnext/artifacts/audits/2026-08-09-frozen-product-2f704-live-build
acceptance_parent=/Volumes/T5/hepta-vnext/artifacts/acceptances
tool_root=/Volumes/T5/hepta-vnext/artifacts/tools/hepta-operator-acceptance-v1
acceptance_bin="$tool_root/hepta-operator-acceptance"
namespace=hepta-vnext-operator-acceptance-v1
policy_scope=externally_pinned_single_ed25519_external_revocation_responsibility_no_local_krl_v1
script_path=${0:A}

if [[ $# -eq 0 ]]; then
  exec /Volumes/T5/hepta-vnext/bin/hepta-ssd-run operator-acceptance -- \
    "$script_path" --inside-wrapper
fi
if [[ $# -ne 1 || "$1" != --inside-wrapper ]]; then
  print -u2 -- "usage: formal_e2e.zsh"
  exit 2
fi

for assignment in \
  "HEPTA_SSD_ROOT=/Volumes/T5/hepta-vnext" \
  "HEPTA_SSD_VOLUME_UUID=FB804D1B-24CB-4D6E-AEA7-A9E180807758" \
  "HEPTA_LANE=operator-acceptance" \
  "HEPTA_WORKTREE=/Volumes/T5/hepta-vnext/worktrees/operator-acceptance" \
  "HEPTA_ARTIFACTS_DIR=/Volumes/T5/hepta-vnext/artifacts"; do
  env_name=${assignment%%=*}
  expected=${assignment#*=}
  [[ ${(P)env_name-} == "$expected" ]] || {
    print -u2 -- "formal wrapper environment mismatch: $env_name"
    exit 2
  }
done

[[ -x "$acceptance_bin" && -f "$tool_root/SHA256SUMS" ]] || {
  print -u2 -- "qualified test binary or SHA256SUMS is absent"
  exit 2
}
(
  cd "$tool_root"
  shasum -a 256 -c SHA256SUMS >/dev/null
)
[[ -d "$acceptance_parent" ]] || {
  print -u2 -- "canonical acceptance parent is absent"
  exit 2
}
trust_dir=$(mktemp -d /Volumes/T5/hepta-vnext/tmp/operator-acceptance-formal-e2e.XXXXXX)
primary_store=$(mktemp -d "$acceptance_parent/operator-acceptance-test-primary.XXXXXX")
invalid_store=$(mktemp -d "$acceptance_parent/operator-acceptance-test-invalid.XXXXXX")
orphan_store=$(mktemp -d "$acceptance_parent/operator-acceptance-test-orphan.XXXXXX")
copied_store=$(mktemp -d "$acceptance_parent/operator-acceptance-test-copy.XXXXXX")
chmod 700 "$trust_dir" "$primary_store" "$invalid_store" "$orphan_store" "$copied_store"

for temp_root in "$trust_dir" "$primary_store" "$invalid_store" "$orphan_store" "$copied_store"; do
  case "$temp_root" in
    /Volumes/T5/hepta-vnext/tmp/operator-acceptance-formal-e2e.* | \
    /Volumes/T5/hepta-vnext/artifacts/acceptances/operator-acceptance-test-*) ;;
    *) print -u2 -- "unsafe temporary root: $temp_root"; exit 2 ;;
  esac
done

cleanup() {
  set +e
  /bin/rm -rf -- "$trust_dir" "$primary_store" "$invalid_store" "$orphan_store" "$copied_store"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

record() {
  local event=$1
  local result=$2
  local detail=${3:-}
  jq -cnS --arg event "$event" --arg result "$result" --arg detail "$detail" \
    '{detail:$detail,event:$event,result:$result,test_only:true}'
}

digest_file() {
  local digest_output
  digest_output=$(shasum -a 256 "$1")
  print -r -- "${digest_output%% *}"
}

file_snapshot() {
  stat -f '%d:%i:%m:%c:%z' "$1"
}

write_policy() {
  local store_root=$1
  local policy_name=$2
  current_policy="$trust_dir/$policy_name.json"
  jq -cjnS \
    --arg store "$store_root" \
    --arg allowed "$allowed_sha" \
    --arg fingerprint "$fingerprint" \
    --arg principal "test-operator@example" \
    --arg scope "$policy_scope" \
    --arg root_id "test-only-$policy_name" \
    '{acceptance_store_root:$store,allowed_signers_sha256:$allowed,key_fingerprint:$fingerprint,maximum_lifetime_seconds:900,principal:$principal,schema:"hepta_operator_acceptance_trust_policy_v1",schema_version:1,trust_policy_scope:$scope,trust_root_id:$root_id,trust_root_revision:1}' \
    > "$current_policy"
  chmod 600 "$current_policy"
  current_policy_sha=$(digest_file "$current_policy")
}

prepare_store() {
  local store_root=$1
  local policy_file=$2
  local policy_sha=$3
  "$acceptance_bin" prepare "$qualification_root" "$product_root" "$store_root" \
    "$allowed_signers" "$policy_file" "$policy_sha"
}

verify_store() {
  local store_root=$1
  local policy_file=$2
  local policy_sha=$3
  local signature_file=$4
  "$acceptance_bin" verify "$qualification_root" "$product_root" "$store_root" \
    "$allowed_signers" "$policy_file" "$policy_sha" "$signature_file"
}

verify_receipt() {
  local store_root=$1
  local policy_file=$2
  local policy_sha=$3
  "$acceptance_bin" verify-receipt "$qualification_root" "$product_root" "$store_root" \
    "$allowed_signers" "$policy_file" "$policy_sha"
}

expect_failure() {
  local label=$1
  shift
  set +e
  local output
  output=$("$@" 2>&1)
  local rc=$?
  set -e
  [[ $rc -ne 0 ]] || {
    record "$label" FAIL "unexpected success"
    return 1
  }
  record "$label" PASS "$output"
}

canonical_mutate() {
  local target=$1
  local filter=$2
  local temporary="$target.mutating"
  jq -cSj "$filter" "$target" > "$temporary"
  chmod 600 "$temporary"
  mv -f "$temporary" "$target"
}

/usr/bin/ssh-keygen -q -t ed25519 -N "" -f "$trust_dir/test-only-operator-key"
read -r key_type key_blob key_comment < "$trust_dir/test-only-operator-key.pub"
allowed_signers="$trust_dir/allowed_signers"
printf "%s %s %s\n" "test-operator@example" "$key_type" "$key_blob" > "$allowed_signers"
chmod 600 "$allowed_signers"
allowed_sha=$(digest_file "$allowed_signers")
fingerprint=$(/usr/bin/ssh-keygen -E sha256 -lf "$trust_dir/test-only-operator-key.pub" | awk '{print $2}')

# Exact environment guard is enforced in the public library, not only main.
expect_failure env_pin_missing env -u HEPTA_LANE "$acceptance_bin" prepare \
  "$qualification_root" "$product_root" "$primary_store" "$allowed_signers" /nonexistent 0
for env_name in HEPTA_SSD_ROOT HEPTA_SSD_VOLUME_UUID HEPTA_LANE HEPTA_WORKTREE HEPTA_ARTIFACTS_DIR; do
  expect_failure "env_pin_wrong_$env_name" env "$env_name=wrong" "$acceptance_bin" prepare \
    "$qualification_root" "$product_root" "$primary_store" "$allowed_signers" /nonexistent 0
done
expect_failure wrong_qualification_root "$acceptance_bin" prepare \
  "$product_root" "$product_root" "$primary_store" "$allowed_signers" /nonexistent 0
expect_failure wrong_product_root "$acceptance_bin" prepare \
  "$qualification_root" "$qualification_root" "$primary_store" "$allowed_signers" /nonexistent 0
expect_failure sidecar_outside_acceptance_parent "$acceptance_bin" prepare \
  "$qualification_root" "$product_root" "$trust_dir" "$allowed_signers" /nonexistent 0
record formal_environment_and_root_guards PASS

# Primary valid test-only ceremony and location-bound stored receipt.
write_policy "$primary_store" primary-policy
primary_policy=$current_policy
primary_policy_sha=$current_policy_sha
prepared=$(prepare_store "$primary_store" "$primary_policy" "$primary_policy_sha")
primary_challenge="$primary_store/operator-acceptance-challenge.json"
/usr/bin/ssh-keygen -Y sign -f "$trust_dir/test-only-operator-key" -n "$namespace" \
  "$primary_challenge" >/dev/null
chmod 600 "$primary_challenge.sig"
sealed=$(verify_store "$primary_store" "$primary_policy" "$primary_policy_sha" \
  "$primary_challenge.sig")
receipt_sha=$(print -r -- "$sealed" | jq -r .acceptance_receipt_sha256)
challenge_sha=$(print -r -- "$sealed" | jq -r .challenge_sha256)
rm -f "$primary_challenge.sig"
readback=$(verify_receipt "$primary_store" "$primary_policy" "$primary_policy_sha")
[[ "$sealed" == "$readback" ]]
record delete_original_signature_then_verify_receipt PASS "$receipt_sha"

# Cooperative replay must not rewrite immutable claim or receipt bytes/mtime.
primary_claim="$primary_store/operator-acceptance-nonce-claim.json"
primary_receipt="$primary_store/operator-acceptance-receipt.json"
claim_sha_before=$(digest_file "$primary_claim")
receipt_sha_before=$(digest_file "$primary_receipt")
claim_snapshot_before=$(file_snapshot "$primary_claim")
receipt_snapshot_before=$(file_snapshot "$primary_receipt")
sleep 1
replay=$(verify_store "$primary_store" "$primary_policy" "$primary_policy_sha" \
  "$primary_store/deleted-original.sig")
[[ "$sealed" == "$replay" ]]
[[ "$claim_sha_before" == "$(digest_file "$primary_claim")" ]]
[[ "$receipt_sha_before" == "$(digest_file "$primary_receipt")" ]]
[[ "$claim_snapshot_before" == "$(file_snapshot "$primary_claim")" ]]
[[ "$receipt_snapshot_before" == "$(file_snapshot "$primary_receipt")" ]]
record idempotent_replay_preserves_claim_and_receipt PASS

# Back up exact canonical store records, then exercise semantic tampering.
cp -p "$primary_challenge" "$trust_dir/challenge.original"
cp -p "$primary_claim" "$trust_dir/claim.original"
cp -p "$primary_receipt" "$trust_dir/receipt.original"

canonical_mutate "$primary_receipt" '.signature.detached_signature_sshsig_base64 |= (if startswith("A") then "B" + .[1:] else "A" + .[1:] end)'
expect_failure embedded_signature_bitflip verify_receipt "$primary_store" "$primary_policy" "$primary_policy_sha"
cp -p "$trust_dir/receipt.original" "$primary_receipt"

canonical_mutate "$primary_challenge" '.decision = "reject"'
expect_failure canonical_challenge_tamper verify_receipt "$primary_store" "$primary_policy" "$primary_policy_sha"
cp -p "$trust_dir/challenge.original" "$primary_challenge"

canonical_mutate "$primary_claim" '.nonce = ("f" * 64)'
expect_failure nonce_claim_tamper verify_receipt "$primary_store" "$primary_policy" "$primary_policy_sha"
cp -p "$trust_dir/claim.original" "$primary_claim"

canonical_mutate "$primary_receipt" '.authority.enforce = true'
expect_failure receipt_top_authority_tamper verify_receipt "$primary_store" "$primary_policy" "$primary_policy_sha"
cp -p "$trust_dir/receipt.original" "$primary_receipt"

canonical_mutate "$primary_receipt" '.challenge.authority.enforce = true'
expect_failure receipt_nested_authority_tamper verify_receipt "$primary_store" "$primary_policy" "$primary_policy_sha"
cp -p "$trust_dir/receipt.original" "$primary_receipt"

canonical_mutate "$primary_receipt" '.challenge.excluded_gates.windows_gate_run = true'
expect_failure receipt_nested_exclusion_tamper verify_receipt "$primary_store" "$primary_policy" "$primary_policy_sha"
cp -p "$trust_dir/receipt.original" "$primary_receipt"

canonical_mutate "$primary_receipt" '.challenge.automatic_transition = true'
expect_failure receipt_automatic_transition_tamper verify_receipt "$primary_store" "$primary_policy" "$primary_policy_sha"
cp -p "$trust_dir/receipt.original" "$primary_receipt"
record semantic_tamper_matrix PASS

# Wrong namespace must not consume; the exact same challenge then succeeds.
write_policy "$invalid_store" invalid-policy
invalid_policy=$current_policy
invalid_policy_sha=$current_policy_sha
prepare_store "$invalid_store" "$invalid_policy" "$invalid_policy_sha" >/dev/null
invalid_challenge="$invalid_store/operator-acceptance-challenge.json"
/usr/bin/ssh-keygen -Y sign -f "$trust_dir/test-only-operator-key" -n wrong-namespace \
  "$invalid_challenge" >/dev/null
chmod 600 "$invalid_challenge.sig"
expect_failure wrong_namespace_signature verify_store "$invalid_store" "$invalid_policy" \
  "$invalid_policy_sha" "$invalid_challenge.sig"
[[ ! -e "$invalid_store/operator-acceptance-nonce-claim.json" ]]
[[ ! -e "$invalid_store/operator-acceptance-receipt.json" ]]
rm -f "$invalid_challenge.sig"
/usr/bin/ssh-keygen -Y sign -f "$trust_dir/test-only-operator-key" -n "$namespace" \
  "$invalid_challenge" >/dev/null
chmod 600 "$invalid_challenge.sig"
verify_store "$invalid_store" "$invalid_policy" "$invalid_policy_sha" \
  "$invalid_challenge.sig" >/dev/null
record invalid_signature_then_valid_same_challenge PASS

# A preexisting orphan claim permanently prevents PASS.
write_policy "$orphan_store" orphan-policy
orphan_policy=$current_policy
orphan_policy_sha=$current_policy_sha
prepare_store "$orphan_store" "$orphan_policy" "$orphan_policy_sha" >/dev/null
printf "%s" '{}' > "$orphan_store/operator-acceptance-nonce-claim.json"
chmod 600 "$orphan_store/operator-acceptance-nonce-claim.json"
expect_failure orphan_claim_first_attempt verify_store "$orphan_store" "$orphan_policy" \
  "$orphan_policy_sha" "$orphan_store/no-signature-needed.sig"
expect_failure orphan_claim_retry verify_store "$orphan_store" "$orphan_policy" \
  "$orphan_policy_sha" "$orphan_store/no-signature-needed.sig"
expect_failure orphan_claim_readback verify_receipt "$orphan_store" "$orphan_policy" \
  "$orphan_policy_sha"
[[ ! -e "$orphan_store/operator-acceptance-receipt.json" ]]
record orphan_claim_permanent_fail_closed PASS

# Copying a complete store cannot bypass the external absolute store pin.
rmdir "$copied_store"
cp -Rp "$primary_store" "$copied_store"
expect_failure copied_store_policy_pin verify_receipt "$copied_store" "$primary_policy" \
  "$primary_policy_sha"
record copied_store_rejected PASS

# Read-only verification refuses a missing lock and does not recreate it.
rm -f "$primary_store/.operator-acceptance.lock"
expect_failure missing_lock_read_only verify_receipt "$primary_store" "$primary_policy" \
  "$primary_policy_sha"
[[ ! -e "$primary_store/.operator-acceptance.lock" ]]
record missing_lock_not_recreated PASS
record formal_e2e_complete PASS

jq -cnS \
  --arg schema hepta_operator_acceptance_formal_e2e_summary_v1 \
  --arg challenge_sha256 "$challenge_sha" \
  --arg receipt_sha256 "$receipt_sha" \
  --arg binary_sha256 "$(digest_file "$acceptance_bin")" \
  '{binary_sha256:$binary_sha256,challenge_sha256:$challenge_sha256,receipt_sha256:$receipt_sha256,schema:$schema,test_only:true,verdict:"PASS"}'
