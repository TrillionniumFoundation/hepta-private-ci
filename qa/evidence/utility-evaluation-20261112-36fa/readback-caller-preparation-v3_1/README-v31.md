# v3.1: actual path literals and complete caller-test scope

This is a four-path delta on the immutable v3 preparation, not a source commit.
It changes CALLERS and three newly authored QA files. Production Rust, original
verifier scripts, authority, workflow, budgets, references and all existing
boundary memberships remain unchanged.

## The v3 gap was actually reproduced

Using v3 CALLERS `21b854dd3f1bb245b42f2a57c0fd7685131430b2` and the exact original
`owner_host_registry_durable.rs` blob `26a09f65f0f78e3218f517f07f394573d25db13a`,
the original verifier accepted same-length substitutions of both directory
literals and both filename templates. Their actual function's masked body was
identical. An experiment adding only raw `required` strings also accepted the
changed templates when the old strings were retained in a comment or an unused
constant. The baseline and eight counterexample observations were actually run;
the original evidence is retained in blobs:

- Observation: `568047b7d61e15707165abd4a500a70229a29f8f`.
- Raw log: `4a594b64826b3da438944278edf0055fc90041c9`.
- Execution record: `ea19c60806d737be2288ae695d29bd6e591c7a19`.
- Reproducer: `9abcb5b7312fc46225edec88aaf0bb33c3f309f9`.

These are source-protection counterexamples; they do not execute mutated Rust.
The v3 preparation and its earlier passing source mutations are not rewritten.

## Minimal literal fix

Only one existing protected row is strengthened: zero-based row 398 for the
physical RegistryDurable reader. Its complete-body constraint remains unchanged.
A second ordered entry for the same real function uses the original verifier's
`literal_calls` support to bind `.join("payloads")` and `.join("witnesses")` to
their actual function-local code positions, ordered with the physical payload,
witness, registry and final currentness reads. No row is removed or deduplicated.

The original verifier intentionally does not support `format!` in
`literal_calls`. File-level raw substring checks cannot provide equivalent
protection. The newly authored Artifact source-closure QA therefore adds one
narrow check: find the unique real durable-reader function using the original
code masks, locate its two actual `format!` macro argument spans, and compare the
actual first argument literals with `"{}-{}.bin"` and `"{}-{}.witness"`. Comments,
string contents and code outside that function cannot supply those macro spans.
This check is combined with the unchanged complete-body source fence, which
retains the original operations and surrounding control flow.

Two new methods actually passed against the final v3.1 bytes: six directory
counterexamples rejected by the original literal verifier, and eight filename
counterexamples rejected by the new QA. The latter preserve the distinction by
first confirming that the unchanged original verifier still accepts their
same-length format changes. The cases include old literals in comments,
unrelated constants and an unrelated real `format!` call. Inputs remained
byte-identical before and after execution. The earlier twelve-case pass and its
exact QA input are also retained; the final run adds two real macro decoys.

This new macro-span check is source-closure QA, not a newly claimed capability
of the original CALLERS verifier and not a general Rust parser or runtime proof.
The inherited generic `read_response<'a>` fence also remains explicitly scoped:
it uses file-level ordered stripped code because the original function-marker
grammar does not accept a generic signature. That fallback is not equivalent to
the 37 function-level uniqueness/nested-function checks. The current actual
source was reviewed as unique; no broader formal guarantee or extra test is
claimed for the unchanged fallback.

## Training scope correction and bounded cache reuse

The newly authored v2 Training membership method previously constructed its
source dictionary from EXPECTED definition/member paths: 48 paths in the v3
preparation. It was a negative unit check within that known set, not a complete
caller-closure proof. v3.1 explicitly changes it to the original `_source_files`
collector over all declared Rust roots, with the original masks and ignored
fragments. The separate 6,597-source diagnostics remain independent; their
observations are not replaced or reassigned by this correction.

The Training and Selection methods each retain every positive, extra-caller and
missing-caller case. Both use a local cache per receiver type from their one
complete, immutable baseline source dictionary. It may be reused only when
adding the exact controlled pure function negative: the QA checks that no
field/type/alias declaration was introduced, checks the original one-file
`authority_fields` result, and checks alias discovery against every known target
or alias. The original algorithm can add aliases only through alias declarations
and fields only through struct declarations, neither of which occurs in these
fixed snippets. Existing source entries are unchanged. Removing a real file can
remove aliases or fields, so every such case still receives a fresh cache.
There is no cache shared across methods, source versions or partial source views.

Static call accounting is explicit: Training makes 17 original boundary calls,
Selection 17, and Artifact 5, for 39 complete source-index traversals and three
complete source collections. The two typed methods now make twelve full-source
field-index builds in total, plus twelve one-file purity checks. Their prior
twenty-four field-index builds mixed full Selection input with a Training subset;
the coverage expansion prevents treating those counts as a measured speedup.
No case is deleted, and every original assertion-call AST is retained.

The original nine QA files' 95 functions are independently verified byte-for-byte
and AST-identical. The historical 109-function v3 preservation record remains
historical: the newly authored Training membership method is now intentionally
changed, as is the newly authored Selection membership method. Their other
functions and all existing Artifact functions remain identical. Three narrow
Artifact functions are added: the template helper and two literal methods.

## Counts, identities and acceptance limits

The correct terminology is **399 protected rows covering 328 distinct paths**.
The inherited v2 prefix has 390 rows covering 319 distinct paths. Duplicate rows
and their order are retained. All 534 boundary rows, including their member
lists, are identical to v3. v3.1 changes only one protected row's appended
function-order entry; all other CALLERS fields are identical.

The packet requires manifest `911b0ae279c4e552224985ea2d6df23b6cebe6be` and exact
v3 preimages. No production Rust is included. The integrating owner must record
the final CALLERS SHA256 in the existing allowlist, freeze an actual new source
head, and execute the original gates.

The original source-closure discovery and **600-second budget are unchanged**.
The three full membership methods have not been executed in this partial local
preparation. Static counts and injection-purity checks do not establish budget
compliance or a full gate PASS. No complete source/caller gate, Cargo test,
independent A/B/C task improvement, authority grant or cold recovery acceptance
is claimed.
