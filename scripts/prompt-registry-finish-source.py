#!/usr/bin/env python3
"""One-shot documentation authoring; never copied into the delivery branch."""
from pathlib import Path
import subprocess
import sys

root = Path(sys.argv[1]).resolve()
if subprocess.check_output(['git','rev-parse','HEAD'], cwd=root, text=True).strip() != 'be3046379a980f6a56555c2feb56f20aad422b91':
    raise SystemExit('source drift')

def replace(path, old, new):
    file = root / path
    text = file.read_text()
    if text.count(old) != 1:
        raise SystemExit(f'{path}: anchor mismatch {old[:70]!r}')
    file.write_text(text.replace(old,new,1))

path = 'docs/modules/prompt.registry/TECHNICAL.md'
replace(path, '**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0', '**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0 ([canonical plan](../../DEVELOPMENT.md), selected by `docs/CURRENT.json`).\n\n**Current implementation contracts:** [API and failure policy](API_CONTRACT.md), [operations and retention](OPERATIONS.md), [performance measurement](PERFORMANCE.md).')
replace(path, '### Native storage V3: immutable payload extents', '### Native storage V4: immutable payload extents and complete semantic metadata')
replace(path, '`DurablePromptRegistry` publishes storage V3 through the existing single writer.\n`registry.json` contains the V2 semantic metadata image plus bounded payload', '`DurablePromptRegistry` publishes strict storage V4 through the existing single writer.\n`registry.json` contains the V4 semantic metadata image, including relations, plus bounded payload')
replace(path, 'V1/V2 storage migrates on open without changing domain digests, lifecycle or grants.\nA validated V3 reopen does not rewrite its metadata snapshot.', 'V1/V2/V3 and transitional outer-V4/inner-V2 storage migrate on normal owner open\nwhile preserving their validated semantic facts. A validated strict-V4 reopen\ndoes not rewrite its metadata snapshot. Strict checkpoint verification is a\nseparate non-mutating path: it rejects legacy inputs instead of migrating them.')
replace(path, '`verify_restore_checkpoint` reopens and reconciles one candidate against an\noptional exact revision and registry digest.', '`verify_restore_checkpoint` performs a non-mutating strict-V4 read against a\nrequired trusted exact revision and registry digest. It never initializes,\nmigrates, republishes metadata or trims an unselected tail. Checkpoint receipts\ninclude equal source/checkpoint retained-history digests and explicitly report\n`source_erased=false`; omitted destination bytes are not original-store erasure.')
with (root / path).open('a') as output:
    output.write('\n## Current-use and delivery-consistency update — 2026-09-28\n\nThe real factor lifecycle is Draft, Admitted, Retired and Revoked. Agentd\npreparation and durable dispatch recording use the same typed current-use\ncontract. Cached ready contexts reconsult that owner and reject changed\nattachments rather than silently replacing an injected payload. The dispatch\nclaim retains the registry lock through durable recording and uses the trusted\nhost clock, not a caller-provided past timestamp. Terminal provider facts remain\ntruthful; this does not claim cancellation of already admitted network I/O or\nretraction of streamed output. See API_CONTRACT.md for the linearization boundary.\n\nMetrics remain available diagnostically after poisoning with\n`authoritative=false`; raw payloads and compiler diagnostics are not emitted in\nfinal-use Display messages. Checkpoint retry is idempotent only for the exact\ncompleted image. Partial/conflicting/symlink destinations are never overwritten.\n\nThe candidate builds checked-in Rust directly. Historical apply-prompt scripts\nand source-mutating qualification workflows were retired. The implementation\nmap is explicitly authored using --write after a source commit; CI uses --check\nonly and records each check result, including missing tests and timeouts.\n')
replace('docs/modules/prompt.registry/PERFORMANCE.md', 'A actual\nsingle durable registration', 'An actual\nsingle durable registration')
path = 'scripts/hepta-prompt-registry-map.py'
replace(path, '        "sourceObjects": entries,', '        "sourceObjects": [{"path": path, "object": git("rev-parse", f"HEAD:{path}")} for path in sorted(set(paths + [CORE]))],')
# The framework input files themselves participate in the observed map identity.
replace(path, '    "scripts/hepta-prompt-registry-map.py",', '    "scripts/hepta-implementation-maps.py",\n    "scripts/hepta_module_source_roots.py",\n    "scripts/hepta-prompt-registry-map.py",')
path = 'scripts/hepta-prompt-registry-qualify.py'
replace(path, '            graph = json.loads(text)\n            names = {package["name"] for package in graph["packages"]}', '            try:\n                graph = json.loads(text[text.index("{"):])\n                names = {package["name"] for package in graph["packages"]}\n            except (ValueError, KeyError, TypeError):\n                checks.append("invalid Cargo source graph output")\n                names = set()')
(root / 'qualification/module-execution-dossiers/detail/prompt.registry.md').write_text('''# prompt.registry implementation and qualification dossier

Parent: `docs/modules/prompt.registry/TECHNICAL.md`. Canonical plan:
`docs/DEVELOPMENT.md`, selected by `docs/CURRENT.json`.

## 1. Claim boundary

Source implemented: true. Source composed: true. Product activated: false.
Independently accepted: false. Released: false. Production ready: false.
Current-source files, operation/test navigation and actual executed receipts are
separate evidence. A core-only pass, a generated source archive or a historic
run cannot qualify the current product candidate.

## 2. Source and ownership

The deterministic owner is `codex-rs/hepta-prompt-registry`. Agentd composition
is `codex-rs/hepta-agentd/src/prompt_runtime.rs`, not a phantom prompt_pipeline.rs.
Final-use validation and durable leases live in prompt_final_use.rs and
prompt_final_use_store.rs. The actual cached/provider-policy consumer is
`codex-rs/ext/hepta-prompt`; the intelligence compiler remains in
`codex-rs/hepta-intelligence/src/prompt_delivery.rs`. The optimizer is read-only.
Historical apply-prompt scripts are not part of the delivered build path.

## 3. Public operations

Signed operation-bound publication/admission/relation/realization/lifecycle
paths are conventional checked-in source. Factor lifecycle is Draft, Admitted,
Retired, Revoked. Model compatibility includes model/version, tokenizer,
template, tool schema, context profile, locale, role and payload identity.
Registry insertion does not auto-select or activate a factor.
The complete bounded API and typed recovery policy are in
`docs/modules/prompt.registry/API_CONTRACT.md`.

## 4. Durable storage and maintenance

Strict V4 metadata retains factors, realizations, bindings, relations,
supersession, payload references and lifecycle events. Immutable extents precede
atomic metadata selection. An uncertain post-rename outcome poisons the writer
until reopen/reconciliation; diagnostics do not expose authoritative access.
Copy-compaction omits inactive payloads, preserves retained-history identity,
and does not change or erase the original owner. Identical completed checkpoint
retries are idempotent. Partial/different/unsafe destinations are not overwritten.
Strict restore verification requires a trusted exact identity and never repairs
or creates the candidate. The detailed runbook is `OPERATIONS.md` beside the API.

## 5. Actual-use boundary

Preparation and durable dispatch claims share the current-use validator with a
trusted host clock. Cached ready attachments reconsult the owner and reject
identity changes. A revoked staged context must fail before dispatch recording,
and still fail after restart, leaving no dispatch claim for the rejected attempt.
The extension separately tests owner withdrawal before provider-policy begin.
These are source-level owner/consumer tests. Strong cancellation after an already
admitted dispatch, live transport, streaming/final-output consumers and deployed
host-configuration freshness are not established by this source test alone.
Terminal outcomes continue to record what physically happened.

## 6. Verification and performance

The read-only module workflow freezes one source and base identity for core and
product profiles, each on exact-head and deterministic synthetic-merge lanes.
Each command produces an exit status and log digest. Compiled test inventories
must contain named regressions; zero matched tests cannot count as success.
Checkpoints/restore failures, corruption, pre-rename failures, post-rename
poisoning, orphan tails and idempotent reconciliation have native test cases.
This is not a complete real-power-loss or device-failure campaign.

Actual ignored profiles measure 1k/8k/16k logical records, bounded fsync samples
and the one-realization Agentd compile-stage/current-use path. Their sample and
memory interpretation is in `PERFORMANCE.md`. Retained event history still grows;
metadata capacity, original/backups erasure, and oldest-reclaimable timestamps
are not magically solved by omitting inactive bytes from a new checkpoint.

## 7. Remaining evidence gates

Passing all current exact-head/base-merge core and product checks; independently
validated live transport/output cancellation; externally fenced checkpoint
activation and raw-byte retention/disposal; a durable age policy where required;
target-host security/semantic review, protected postmerge checks, operator
activation/acceptance and release. No source change grants these decisions.
''')
for file in ['scripts/hepta-prompt-registry-map.py','scripts/hepta-prompt-registry-qualify.py']:
    compile((root/file).read_text(),file,'exec')
print('Documentation and navigation contracts updated; map generation follows the source commit')
