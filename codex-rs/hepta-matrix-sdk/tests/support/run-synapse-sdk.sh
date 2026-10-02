#!/usr/bin/env bash
# Disposable Linux protocol test. Does not replace paired-host qualification.
set -euo pipefail
root=$(git rev-parse --show-toplevel)
fixture=$(mktemp -d)
name="hepta-sdk-synapse-${RANDOM}-${RANDOM}"
image='matrixdotorg/synapse@sha256:b1a1e1ab727ed567ceb7660b52149cbeb973348edf696e263454f0261d8153bb'
cleanup() {
  docker logs "$name" > "$fixture/synapse.log" 2>&1 || true
  docker rm -f "$name" >/dev/null 2>&1 || true
  if [[ -n ${HEPTA_SDK_ARTIFACTS:-} ]]; then
    mkdir -p "$HEPTA_SDK_ARTIFACTS"
    cp "$fixture/synapse.log" "$HEPTA_SDK_ARTIFACTS/"
  fi
  rm -rf "$fixture"
}
trap cleanup EXIT
command -v docker >/dev/null
# Configuration, accounts and stores exist only in this temporary fixture.
cat > "$fixture/homeserver.yaml" <<'YAML'
server_name: fixture.invalid
pid_file: /data/homeserver.pid
listeners:
  - port: 8008
    tls: false
    type: http
    bind_addresses: ['0.0.0.0']
    resources:
      - names: [client]
        compress: false
database:
  name: sqlite3
  args:
    database: /data/homeserver.db
log_config: /data/log.config
media_store_path: /data/media_store
signing_key_path: /data/fixture.invalid.signing.key
macaroon_secret_key: isolated-sdk-fixture-only
form_secret: isolated-sdk-fixture-only
enable_registration: true
enable_registration_without_verification: true
report_stats: false
trusted_key_servers: []
rc_registration:
  per_second: 100
  burst_count: 100
rc_message:
  per_second: 100
  burst_count: 100
YAML
cat > "$fixture/log.config" <<'YAML'
version: 1
handlers:
  console:
    class: logging.StreamHandler
root:
  level: INFO
  handlers: [console]
disable_existing_loggers: false
YAML
# Use the same unprivileged owner for generation and serving, so the private
# signing key stays readable without widening fixture permissions.
fixture_uid="$(id -u)"
fixture_gid="$(id -g)"
docker run --rm --user "$fixture_uid:$fixture_gid" -v "$fixture:/data" --entrypoint python "$image" -m synapse.app.homeserver --config-path /data/homeserver.yaml --generate-keys
# Publish to loopback only; never expose the disposable registration endpoint.
docker run -d --user "$fixture_uid:$fixture_gid" -e UID="$fixture_uid" -e GID="$fixture_gid" --name "$name" -p 127.0.0.1:18008:8008 -v "$fixture:/data" "$image" >/dev/null
for i in $(seq 1 90); do
  if curl --fail --silent http://127.0.0.1:18008/_matrix/client/versions >/dev/null; then break; fi
  if [[ "$i" == 90 ]]; then echo 'Synapse failed readiness' >&2; exit 1; fi
  sleep 1
done
cd "$root/codex-rs"
HEPTA_SDK_SYNAPSE_URL=http://127.0.0.1:18008 just test --locked --retries 0 -p codex-hepta-matrix-sdk --features synapse-sdk-qualification --test synapse_sdk_upgrade
