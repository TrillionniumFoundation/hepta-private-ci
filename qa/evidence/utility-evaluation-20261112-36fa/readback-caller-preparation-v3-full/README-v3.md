# Original Selection and Artifact channel registration: v3 preparation

This is a reviewable source-protection preparation, not a source commit or a
completed learning loop. It makes no production Rust, authority, wire protocol,
verifier, workflow, or reference change. The source remains fixed to the audited
`b29869e856d08db1bfb066116a9c443376ccc57d` dependency and the existing e8 integration.
The base is the separately retained v2 CALLERS/QA preparation, whose CALLERS blob
is `317da5f28fbc1cf2556fa5935bb846dce8c7c2cb`.

## Exact change

The prepared CALLERS file has 534 boundaries and 399 protected files. All 390
existing protected rows remain identical to v2. Four existing boundary rows
retain all their other fields and original ordered member lists, then append
nine audited members. The other 530 boundary rows and all other top-level
metadata are unchanged.

Six memberships are the original Selector readback adapters: the evaluated
readback owner and two legacy client/service files in the original process-bound
framer; the legacy client in original initial and Dataset context checks; and the
legacy service in original Selector remote readback. The evaluated owner already
has a protected row, which is retained. Two new rows protect the legacy adapters.
The strict legacy three-receipt TrainingNoUpdate protocol remains unchanged.

Three more memberships admit the audited original Artifact HEAD client, HEAD
service and Registry source in the same framer. Seven new rows protect those
three files plus the four explicitly reviewed dependencies: original HEAD owner,
HEAD wire, HEAD signing configuration and physical RegistryDurable readback.

HEAD Sign is an existing effect: the client consumes the actual opaque original
writer continuation, and the original owner consumes its owner-wide admission
and enrolled key before one durable commit. HEAD Readback and Registry Readback
do not gain Sign. Native recovery remains an explicit operation and retains the
original minimum-anchor reconciliation; a recovered owner cannot become fresh.
The Registry durable reader's local transaction reconstruction is retained: its
`begin`, `record_*` and `acknowledge` calls do not write publication files.

## Scope of protection

The seven Artifact rows preserve actual stripped code of only the reviewed
critical functions, signatures and opaque layouts through the original ordered
marker machinery. This prevents an inserted Sign/reset operation from hiding
between a few selected markers within those functions. Each exact item is split
into the two nonempty markers required by the unchanged original verifier.
Raw required markers also retain the request magic and configuration digest
domain, which the original code stripper otherwise masks as string literals.

These source constraints protect fresh/recovered separation, single admission,
key consumption, same original source/journal custody, fixed purpose/nonce/binding,
pre/post current checks, complete saved HEAD verification, fixed expiry and actual
payload/registry/checkpoint/CURRENT/withdrawal observations. They are scoped
source constraints, not a proof of every Artifact dependency or a runtime proof
of independent actors, authorization, availability or adoption.

The existing 10 affected v2 QA files change only their EXPECTED member literals;
all 109 functions remain byte-for-byte and AST-identical. Their existing extra
caller and missing-member assertions remain intact. The Selection-only checkpoint
is also retained: its 12 functions are unchanged, while its EXPECTED tuple gains
the three Artifact members. The final package adds two sibling QA files to the
existing source-closure glob, without changing the original entry point or test
selection.

## Actual preparation checks and their limits

The unchanged `_verify_protected_files` accepted the exact nine reviewed Rust
preimages under the nine new rows. This is a scoped baseline diagnostic.

In a separate local preparation directory, 21 selected source mutation methods
were actually executed against the final prepared CALLERS and QA bytes: eight
Selection methods and thirteen Artifact methods. They passed with no skips and
unchanged input bytes. The tests remove or reverse currentness, custody, subject,
expiry and equality checks; move guards past effects or physical reads; promote
Readback to Sign; remove owner-wide claim/key consumption; and try to introduce
reconnection, key creation or file writes. Every mutation first establishes that
the original Rust file passes the unchanged source verifier, then requires that
the mutation be rejected. They do not execute the mutated Rust.

The first local mutation attempt is preserved as a real failure: one new QA
marker matched both the inner signing-claim clock check and the later readback
clock check. The fixture asserted uniqueness and failed. The correction tests
those two real locations independently with distinct exact markers. No guard,
assertion or selected method was dropped. Both the failed raw log and the later
passing raw log, their exact QA preimages and input manifests are retained.

The two new full-membership methods deliberately enumerate the whole original
Rust source surface with `_source_files` and use the original `_verify_boundary`
with exact observed/expected equality. They also inject an unregistered caller
and remove each newly admitted caller. They were not executed in the partial
local source view; no subset is presented as a closed-world caller proof.

The separately running 534-boundary/390-row diagnostic uses frozen v2, not this
v3. Its results, and the earlier e8 gate failures, must not be credited to v3.
No final source tree, complete source-closure gate, complete caller gate, Cargo
test, ordinary A/B/C execution or cold recovery acceptance is claimed here.
An exact final CALLERS hash must be registered in the existing large-blob
allowlist by the integrating owner, and a new source version must be frozen and
verified through the original gates before any such acceptance claim.

## Discovery and audit provenance

The unchanged fixed-b298 workflow
`.github/workflows/hepta-daemon-learning-native.yml` (blob
`72d4b247d90dde972ac592b2d568cd6e470f97ff`) invokes the original 600-second
`hepta_ci_exec.py` source-closure command with `--minimum-tests 1` and
`python3 -m unittest discover -s qa/b4-no-bypass -p '*source_closure.py' -v`.
Both new filenames match that original pattern. No workflow file is included
in this preparation.

Immutable audits:

- Selection: `7fb2fd1ef668e38163917fcc2b23a2036967566d`.
- Artifact callers: `a36b1e0596a80ebb55aa163fb2719a245fc5f5ee`.
- Four Artifact dependencies: `52a3bb7fcbfa97ab02b2ce5ca047860d19fcd21c`.
- Retained Selection-only checkpoint manifest:
  `5d9b8c96b7f01cca615f3af7503f196ba69013d6`.
- Required v2 preparation manifest:
  `ef16e7f1a1e413bdda7ea44e353e94edbb8f40db`.

The packet is a 13-path delta against the v2 preparation and the unchanged b298
published-read QA file. Every entry specifies its exact base blob and complete
UTF-8 postimage. Applying it to other bytes is forbidden without a new review.
It contains no production Rust and does not replace the two separately prepared
retention guards. The unchanged v2 retention-guard and Training-source-capture QA
files are recorded as retained dependencies, rather than copied over again.
