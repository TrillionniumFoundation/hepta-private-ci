# Install the qualified Linux chat renderer through the existing owner

`scripts/hepta-install-native-chat` is a closed Root deployment driver for the
actual ordinary a0 Gateway/Bridge/Fleetctl and the separately qualified Robrix
renderer and credential helper. It does not install or restart Supervisor,
change an Agent, grant an ACL, open a private Agent directory, or read an existing
keyring credential. Root must review and publish the script and its four
`native_chat_install_*.py` production modules together in a Root-owned protected directory
before executing it. The source-only tests do not constitute a live installation.

The exact admitted ordinary SHA256 values are in `native_chat_install_plan.py`.
The original a0 directory has `hepta-native-gateway`, not the old `hepta` CLI;
its wrapper supplies `--serve-ui` itself. The driver removes only that obsolete
argument, retaining every other original read/lifecycle argument. The a0 build
has no new `hepta-native-credential`: publish the qualified `import-chat` helper
separately. An old helper fails admission before generating any credential.

Publish the qualified 135-file renderer bundle, including `bundle-manifest.json`,
`resources/`, and `licenses/`, under `/opt/hepta-private-ci`. Keep every original
byte. The driver verifies the entire pinned bundle and executable files through
non-following FDs, including namespace and file identity after each read. The
actual Gateway UID984 and desktop UID1000 must be able to execute their respective
normal programs, and UID1000 must be able to read the resources. Prepare checks
these permissions as those users. It does not fix denied access by changing an
Agent or credential directory. Any failure leaves startup blocked explicitly.

The Root-owned, single-link request JSON uses schema
`hepta.native-chat.install-request.v1`, rejects duplicate and unknown fields,
and contains exactly:

- `installation_id`: a fresh canonical UUID; never reuse an attempted namespace.
- `gateway`, `bridge`, `renderer`, `credential_helper`, `fleetctl`,
  `bridge_template`, `desktop_config`, `renderer_manifest`: each has `path` and
  lowercase 64-digit `sha256`. The manifest is the renderer's sibling
  `bundle-manifest.json`. The desktop config remains the original UID1000
  `hepta-native/config.json`; do not supply a fresh empty state/journal.
- `original_policy_sha256`, `original_gateway_unit_sha256`: exact fresh hashes of
  `/etc/hepta-private-ci/local-host.json` and the existing Gateway unit.
- `agents`: at most 16 entries, each with `agentId`, canonical existing `workspace`,
  and `managedProject` (`name`, `idempotencyKey`). The key is exactly
  `hepta.native-chat.project.v1:AGENT_UUID`. Every UUID must already be admitted
  by the original per-Agent workload map. Project creation uses the existing
  AppServer's stable operation, not a second project store.

The original enrollment must remain Gateway984:G973, desktop1000, separate from
all workload UIDs, and the original Gateway cgroup. Existing drop-ins, Chat paths,
unknown desktop fields, or a previous Chat enrollment require reconciliation;
the driver rejects them instead of overwriting them. It reads the original
public unit/policy/config and checks SecretService's D-Bus ownership metadata.
It never requests old key values or touches endpoint/trust signatures.

Root runs the following modes with the same pinned request:

1. `plan --request ROOT_REQUEST --sha256 REQUEST_SHA` validates sources without
   changing files or services.
2. `prepare --request ROOT_REQUEST --sha256 REQUEST_SHA` exclusively creates
   `/var/lib/hepta-private-ci/native-chat-installations/UUID` (Root0700). It saves
   the original bytes and candidate policy. A fresh independent Chat account/key
   is generated inside the helper; key bytes go only to a protected file and the
   credential helper's stdin pipe under UID1000. The existing read/lifecycle
   accounts are retained. No key appears in argv, result JSON, or phase logs.
3. Root performs the already reviewed original Supervisor handoff to the exact
   saved `candidate-host-policy.json`, preserving all original Agents/history.
   This is an external prerequisite, not another owner created by this driver.
4. `activate --request ROOT_REQUEST --sha256 REQUEST_SHA --expected-epoch EPOCH`
   verifies the actual ready epoch and original Gateway incarnation. One 30-second
   command deadline covers stopping the Gateway, staging the exact two-cap Bridge
   unit/config and Chat-only capability, starting Bridge/Gateway, and rechecking
   epoch/kernel UID/GID/cgroup/executable/argv/caps/NNP. The desktop config gains
   only `chat_keyring_account`. File durability barriers remain in force.

Any timed-out/nonzero operation retains a numbered external intent and reports
an unresolved result. No process is killed, no native command is replayed, no
keyring account is deleted, and activation cannot silently be run again. An
interrupted activation must be inspected before explicit restoration. These
external observations are not a domain journal or an authority.

`restore` uses the same request and current epoch. It permits only the original
activation's exact files, keeps the newly enrolled Gateway executable, restores
its original read/lifecycle flags and original desktop bytes, and leaves Chat
keys/unknown intents available for reconciliation. A different policy, epoch,
unit/drop-in, desktop config, or program is refused. Restoring the old executable
would break the original controller enrollment; full old-program rollback needs
Root's original Supervisor policy handoff instead. The tool never resets Fleet.

For actual desktop acceptance, close the old normal UI cleanly to release its
existing journal, then start the pinned `hepta-robrix --config ORIGINAL_CONFIG`
as UID1000 in the existing graphical/keyring session. Never run the GUI as Root.
Verify Chat → Console → Chat, the existing Start/Stop/Restart/Inspect controls,
create/resume an original project/session, and send a real message to one exact
current Agent. Keep the original operation ID when transport becomes unknown:
Send reconciles it; unknown Create/Resume/Cancel remain blocked because no original
receipt query exists. Do not replay them. A missing/locked keyring or unavailable
Bridge is a visible startup/action failure, not proof of a successful Chat.

The renderer currently refuses updater handoff; the original native renderer
remains the admitted update/platform entry. Real Wayland and live Chat acceptance
remain separate checks. The driver returns `live_chat_proved: false` after service
activation so source tests or process readiness cannot be mistaken for delivery.
