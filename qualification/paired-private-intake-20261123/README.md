# Publish a privately admitted paired evaluation once

The original enrollment host observes the frozen pair and the subsequent first task event in its own durable stream. The evaluation host verifies the original scoped human consent with the registered Linux issuer, assembles a single-record request with the frozen tokenizer, then publishes one recoverable delivery. The shared income or provider roles receive five content commitments and the declared source scope. The evaluation request itself stays on the authorized evaluation side.

## Source and deployment

Configure one durable study home for this freeze. Its operator must already trust the source host, owner UID, inode-backed enrollment directory, reference protocol, installed binary hash and private launcher configuration. The source owner can be the existing attached host. Untrusted task submitters must have no write access to either the source-owner directory or the private intake home. The source adapter uses the original source's durable event sequence. The sequence for B is the first event of the **task** on the source stream. A new receipt written for a historical task retains its original task sequence. The site remains responsible for complete source history, semantic independence and the association between an account and a person.

The source owner can project its existing event into a write-once observation with the following commands. Set `PYTHONPATH=scripts` at the repository root. Supply the deployment-owned paths and actual original values. Each study uses its own source directory, owned by the custodian and readable by the evaluator with a read-only mount or private group. Files are 0640. Digest arguments are lowercase 64-digit hex strings.

```sh
python -m cell_experiments.paired_observation "$inbox" "$study" "$freeze" "$original_freeze_seq" freeze
python -m cell_experiments.paired_intake "$study_home" install "$snapshot" "$study" "$freeze" "$inbox" "$native" "$native_sha256" --scope owner_intake
python -m cell_experiments.paired_observation "$inbox" "$study" "$freeze" "$original_task_seq" arrival "$arrival" "$record_sha256" "$consent_delivery" "$study_principal"
```

`arrival` identifies the source's original task arrival. `record_sha256` is `data.record_digest` of the complete v1 evaluation-only confirmation record. `consent_delivery` is the retained original AuthBus **consent** delivery. `study_principal` is the registered study-scoped principal in the site's private source record. The source directory identity and freeze record become immutable intake pins at install. The protected source stream and its durable retention policy are external to this module. An installation made by a researcher for a test supplies `--scope engineering_fixture`.

## Admission and release

Use the attached launcher's original connected Root socket on fd 3, pre-held Root pidfd on fd 4, registered route and private store. `$future` contains a one-element JSON list. The launcher, hash-pinned verifier and source enrollment procedure come from #7019. The expected native readback covers the complete Rust consent text, use, study, delivery and principal. The evaluator opens the record only after verifying this consent.

```sh
admission=$(python -m cell_experiments.paired_intake "$study_home" admit "$arrival" "$snapshot" "$materials" "$future" "$root_pid" "$sqlite_home" "$route")
python -m cell_experiments.paired_intake "$study_home" release "$admission"
python -m cell_experiments.paired_intake "$study_home" people-status "$admission"
```

The private `$study_home/$admission/paired.json` is the exact request assembled by the normal #7025 path. Use its canonical digest and material directory with `cell_experiments.paired_cold` on the teacher-off evaluator. `release.json` contains the canonical study, freeze, candidate, paired request and admission commitments plus source scope. A consumer such as a development escrow owner should bind its task to the same request and logical admission. Contents of local claims, records, consent, enrollment originals and raw evaluation belong on the authorized host.

SQLite atomically claims original arrival, consent delivery, full record, actual input tokens, record ID and available original source identifiers across requests within a study home. Retrying identical content yields the original admission. An OS-held lease and an atomic directory rename publish both files together. Death after publication and before the final database commit can be reconciled from the original bytes. A completed delivery that is subsequently lost or changed requires restoration from the original record. The ledger counts one logical publication. Actual model dispatch, payment and recovery from cloning or rolling back the original ledger are separate responsibilities of the corresponding owners.

## Optional enrolled-person check

Add `--training-run "$materials/paired-training/$key"` to the **first** admission of an arrival to require a site-attested distinct-person pair. The original enrollment authority retains its canonical source records in the protected directory. Keep the existing canonical freeze and first observation unchanged.

| Original | Additional fields beyond schema, study_sha256, freeze_sha256 and original sequence |
| --- | --- |
| `training-person.json`, schema `hepta.paired-intake.training-person.v1` | `authority_sha256`, `enrollment_receipt_sha256`, `person_sha256`, `study_principal_sha256`, `consent_delivery_id`, `source_completion_sha256` |
| `person-<arrival>.json`, schema `hepta.paired-intake.evaluation-person.v1` | Same authority, enrollment receipt, person, principal and consent fields, plus `arrival_id`, `record_sha256`, `request_sha256` |
| `enrollment-<enrollment_receipt_sha256>.bin` | Original private enrollment evidence bytes for the associated person, read only to verify their content commitment |

The registrar must determine stable within-study person references across multiple accounts controlled by one individual. The check reopens both original enrollment materials and validates the common authority, different people, distinct principals, earlier training enrollment, B's exact arrival and request, A's source completion and actual training receipt, and B's live evaluation receipt. `source_completion_sha256` and the training receipt digest use canonical `data.digest`. The enrollment evidence uses SHA-256 of its original bytes. `people-status` distinguishes the check from a site-attested real pair. Fixture scope always returns false for the latter. A previously released anonymous-source evaluation keeps its original status.

The #7022 historical public A has withheld personal identifiers. A prospective task evaluated against it can be recorded with the normal admission if permitted. Separate enrollment originals and the matching authorized A source completion are necessary to use the strict option on a qualifying pair.

## Reproduction and scope

The eight targeted Linux tests use authored examples and synthetic owner/transport controls. They exercise the original freeze and tokenizer, source order and permission checks, native scope binding, enrollment original bytes, re-issued record rejection, a process exiting after publication, concurrent recovery by three processes, and missing deliveries. Run from repo root in the project's numerical environment.

```sh
PYTHONPATH=scripts HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -m unittest -v cell_experiments.test_paired_intake
```

The attached development release was actually admitted and published from the historical #7022 freeze. Its only incoming record was authored for this engineering exercise. Its complete request commitment is `f06b71caec78ab5d1e1c247b183a83f9086d75ebb489fdc72084de1ec9f2b039`. The matching native service receipt and original post-reservation execution are in [Chain #987](https://github.com/TrillionniumFoundation/Trillionnium-Chain/pull/987). [Private host bootstrap and consent](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7019) · [Frozen-tokenizer and exposure preflight](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7025)
