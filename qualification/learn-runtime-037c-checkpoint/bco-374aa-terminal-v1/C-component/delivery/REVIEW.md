# Published CURRENT within one actual read

## Scope and evidence

This isolated component is based on commit `57b27c81d0d5321b873ee751fd0e58e1d905b988`, tree `3db894ee96d358c583bbf4ea15163a0d2bd96258`. It changes five production Rust files and four test files. It does not change the Observer's original 500 ms exchange deadline, the old C withdrawal case, any wire schema, role signatures, Source owner, request limit, connection limit, or effect admission.

The original C failure reached the actual owner. In the retained native evidence, the request arrived at 925 µs, owner read began at 2,117 µs, and ended at 1,114,671 µs. The client returned at 501,652 µs. This is an owner-read cost problem within the original exchange, rather than an idle server timeout. The old source was not the new Candidate Current13 or SourceBound T9 path.

No native or timing result exists for this component. Ordinary qualification remains zero.

## Production change

`OriginalPublishedReadCurrent` is a private, borrowed state machine used only within the synchronous original Published read service. It holds references to the same actual Cell and Task allocations. Both Arc identities are checked at each old CURRENT position. The references keep those allocations alive, and the `Rc` marker prevents moving the proof to another thread. It has no Clone, serialization, public constructor, external current callback, transport handle, signature, or journal mutation.

The service performs the original full CURRENT check in the first and final original slots. Between those checks, it performs every existing Version selection, Source input, Source publication, Cell journal lookup, checkpoint comparison and final authentication. The intermediate CURRENT positions validate the still-borrowed original allocations. All public Cell entry points create an Individual state and retain every physical CURRENT check.

| Original read | Initial input | Initial selection | Inner NextUse | Following input | Repeated selection | Final input | Physical CURRENT |
|---|---:|---:|---:|---:|---:|---:|---|
| Selection | 1–2 | 3–4 | — | 5–6 | 7–8 | 9–10 | 1 and 10 |
| NextUse | 1–2 | 3–4 | 5–9 | 10–11 | 12–13 | 14–15 | 1 and 15 |

The actual mode becomes known after the first four slots, at the same point where the original service selected its mode. It can be selected once. Each state is replaced with Refused before identity checks or physical I/O. A wrong owner, incomplete path, failed final read, extra slot, or repeated purpose cannot leave a completed state reusable. The service consumes the finished state before returning the ordinary read value, and response authentication still runs afterward.

The complete C read statically consists of four Selection frames and two NextUse frames. Explicit Task CURRENT calls decrease from 70 to 12. The 14 actual Version selection reads, 18 Source input reads, eight Source publication reads, two Cell committed lookups and six original Training fixture reads remain. Inner journal CURRENT guards are unchanged. These are call-count facts, not elapsed-time measurements.

## Exact equivalence and format provenance

`IO_EQUIVALENCE_PREFMT_V2.json` reverses only the private helper/current-call substitutions and proves that five original function bodies are byte-identical. It also proves 19 remaining owner/service functions are unchanged, and that the Task parent only gains its private module mount.

The sole actual Rust 1.96 formatter invocation succeeded with an empty raw log. Seven of nine files changed mechanically. The three authorized formatter artifacts were collected from their fixed directory through a read-only Python process. Each file was read through a no-follow file descriptor, checked for stable identity, size and hash, then read again to prove unchanged bytes. All PTY page hex and chunk hashes are preserved.

All nine postimages match the actual formatter manifest by byte length, SHA-256 and Git blob. The actual combined patch matches the locally reconstructed patch exactly. Both strict replay routes passed without offset or fuzz:

1. Exact base → combined actual patch.
2. Exact base → frozen preformat patch → actual formatting patch.

The second route connects the exact body-equivalence proof to the actual formatted source without treating preformat tests as actual-format tests.

## Tests and source guards

Two added native mechanism cases use actual sealed Cell/Task owners. They check withdrawal after the first real CURRENT and before the final slot, compare the final refusal with the existing public error, reject another actual owner, and reject incomplete, repeated-purpose and extra-slot continuations. The existing Clone view is accepted only when both underlying original allocations are identical. These mechanism cases are unexecuted and do not substitute for the unchanged complete C withdrawal/performance case.

The new source suite contains ten tests. It attacks exact caller sets, first/final I/O, slot bounds, private fields, same-allocation binding, poisoning, active mode selection, original Source/Version/Cell reads, old Individual/writer behavior, unused closures and escape mechanisms. The first run retained one real old guard omission and six overly broad fixture-field locators. The guard was strengthened for the unchanged writer scope/admission checks; field mutations were narrowed to the actual struct. No product check was relaxed.

Five existing suites receive minimal migrations. All 74 old test names remain, with 70 bodies unchanged. Changes follow the extracted physical helper, preserve the public Individual wrapper and final finish checks, move the service's actual NextUse edge to its private typed boundary, and add one real function to the Version function inventory. An unchanged Selection suite and the new ten tests form the 88-test compatibility run.

The row delta changes four old protected rows, adds one protected row, changes two existing public boundaries, adds eight private boundaries and eight inventory identifiers. Every old forbidden entry, its order and repetitions are preserved. The delta uses the exact 57b registry as its base. Its disposable combined registry preserves all three separately repaired d397-era caller additions unchanged; it does not replace the central registry or allowlist.

## Remaining acceptance

The required next check is the original native C withdrawal case under the unchanged 500 ms exchange, together with the two new slot mechanisms and the relevant original Published reads. The native cost of the remaining actual Version/Source/Cell checks is not yet measured. A positive source gate and a successful formatter do not establish compilation, owner execution, timing success, complete ordinary NoUpdate, or cold recovery qualification.
