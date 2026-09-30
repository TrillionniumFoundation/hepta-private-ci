# ui.native ordinary-source review map

The current review base is `9be52d267d02a76f73e8a94fd086191c351d1c70` on
`work/ui-native-qualified-integration-20260928`. The audit branch is
`work/ui-native-adversarial-audit-20261001`. Read CURRENT_SOURCE.json for the
immutable implementation SHA/tree and ADVERSARIAL-AUDIT-20261001.md for findings.

Historical WAL/index, portal, paging and package commits remain ancestry. The
old `bfa63c9aec5f1cdc6c3a8b554cbaaabf11676f52` freeze and
`6f145464d9d58233c59aafe262a1250a5ea873a8` review base describe earlier work.

| Audit source change | Commit |
| --- | --- |
| fence sessions and bound presentation input and diagnostics | `f8c078f8006a1e824a428540f7b63b27e2f1cb9c` |
| pin private journal roots and repair durable recovery boundaries | `befe5c710291cf3374859535c57687cd31b1206e` |
| bind update copies and arbitrate confirmation and rollback | `12fc86051bcb189fc21171eff9c33533fa914052` |
| align regression fixtures and enforce strict lint | `0d8afb30f7a2d68125eb7d6f2be4eb771d82ff81` |
| fence watchdog failures with durable update ownership | `4e307a0e69cf24b82457a636091b81fce9115a73` |
| bind complete source and dependency evidence and measure real storage samples | `f4ce125546ab743ebedbc793762add89b1143ac3` |
| keep semantic storage ceilings immutable after source freeze | `9dcb16b980c22dee2c215e9fb116fcf99248a77a` |
| share Windows private state without product dependency cycles | `f93cf2913868aeef4ad2e2496804f459d47e3a46` |
| reconcile retirement in bounded validated prefix batches | `dbde0b4fc00b1d9bdc434dcd78cee30d0823fafd` |
| qualify combined storage using the product release profile | `d6502257d890b915d2287cfc188509d8f18bdd6b` |
| bind WAL regression imports to the journal owner | `21cbe83cf85994bcbfd29666b5acd9d82cc15294` |
| rebuild mixed retirement histories with bounded authenticated spools; bind real first-migration samples and qualification boundaries | `ed5fd2229502099addd6bedec2fae18783d5c162` |

Later review commits update validators, source anchors, technical/development
documentation and evidence navigation. Product edits require a new freeze;
semantic storage budgets remain frozen except the two source-anchor fields.
The checker derives the full local Cargo dependency closure. Qualification
tooling is reviewed at the exact candidate/workflow identity.

Review commands:

```bash
implementation="$(python3 -c 'import json; print(json.load(open("apps/hepta-native/CURRENT_SOURCE.json"))["implementationSourceSha"])')"
git diff --stat 9be52d267d02a76f73e8a94fd086191c351d1c70.."$implementation"
git diff 9be52d267d02a76f73e8a94fd086191c351d1c70.."$implementation" -- apps/hepta-native/src
python3 scripts/check_hepta_ui_native_convergence.py
```

Review directory-handle ownership and WAL/checkpoint recovery first; then update
copy digests, rollback identity, ACK/cancellation arbitration, session and input
fences. Finally inspect exact source/package/SBOM semantics, raw performance
samples, durability counts and the seven-subject evidence aggregate.

The result is an incomplete implementation candidate. Non-Linux verified
Open/Reveal adapters remain absent. Physical acceptance, coverage, soak,
production signing, independent supply-chain acceptance and release authority
remain explicit gates.
