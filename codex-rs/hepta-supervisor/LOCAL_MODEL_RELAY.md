# Local credential-owning model route

The Linux installation can reuse the operator's existing Codex login without
placing that login in an Agent's home. Compile `hepta-model-authority` with the
explicit `local-model-relay` feature and enroll a separate workload UID. The
existing issuer socket and ordinary final-use authority remain the authority
for this route. This service cannot issue independent evaluation or evolution
acceptance.

Add the following optional object to the root-owned model-authority config:

```json
{
  "model_relay": {
    "socket": "/run/hepta-private-ci-model/responses.sock",
    "credential_profile_home": "/home/operator/.codex",
    "credential_uid": 1000,
    "credential_gid": 1000,
    "allowed_models": ["gpt-5.6-sol"],
    "max_concurrent_calls": 2,
    "ingress_timeout_ms": 5000,
    "credential_timeout_ms": 30000,
    "call_timeout_ms": 300000
  }
}
```

Use the actual profile owner and enrolled models. Keep the profile private to
that owner (mode `0700`). The credential UID must differ from the workload UID.
The service's private credential helper drops UID, GID and supplementary groups,
refreshes the existing login through `AuthManager`, and returns credentials only
through an anonymous pipe. Preserve the operator's required proxy, certificate
and keyring session environment when configuring the service.

The root launcher sets `HEPTA_MODEL_RELAY_SOCKET` to the enrolled socket. Its
frozen launch environment includes that socket. An Agent cannot simultaneously
receive `HEPTA_MODEL_CREDENTIAL_PROFILE_HOME`. The App Server then uses the local
Responses provider with WebSockets and automatic request/stream retries disabled.
Core admits only `http://localhost/hepta/v1/responses` through the protected Unix
socket. Existing local conversation compaction uses the same Responses route;
this provider does not expose remote `/compact`.

The model service checks the actual peer UID, executable, process start identity,
root-owned cgroup and current Fleet execution lease. It repeats that check around
durable one-use grant admission and validates the original authority head and
clock at HTTP entry. Request framing, compressed input, concurrency, response
bytes and call duration are bounded. Upstream destinations are selected from the
actual login type: the Codex backend for ChatGPT login, or the OpenAI Responses
API for API-key login. Redirects and workload-supplied authentication are rejected.

Install the approved Agent executable immutably and enroll its exact path and
SHA-256 in the existing model-authority config. The Unix socket is root-owned,
mode `0660`, and uses the enrolled workload GID. Its parent must permit that GID
to traverse; a systemd `RuntimeDirectory` must be recreated with that group after
restart. Preserve the existing authority state, clock floor and nonce history
when upgrading this service.

During installation, verify the actual isolated Agent process, original Fleet
lease, real model response, cancellation and service restart. Successful profile
loading or readiness alone does not establish those product checks. A lost model
response remains subject to the original App Server/Agent effect reconciliation;
the relay does not automatically repeat it.
