# Paired fixture Agentd wire subset

The exact df53 Intel paired product attempt timed out after 300 seconds. Its
catalog-contained fixture was 31,164,960 bytes, compared with a 36,729,848-byte
parent libtest executable. The recorded install and allowance phases finished
at 147.662 seconds; a subsequent release lookup took 34.409 seconds before the
warm-start marker; starting all five pairs took 113.058 seconds. Recovery began
at 299.002 seconds. Those observations do not establish a recovery deadlock or
attribute elapsed time exclusively to hashing, storage, CPU, or scheduling.

The fixture previously decoded the full `AgentdRequest` and encoded the full
`AgentdResponse`, although its only implemented Agentd methods were Health and
Drain. This change gives that private child a strict two-method envelope and
two-payload serializer. It keeps the real `AgentId`, `HealthSnapshot`, and
`DrainSnapshot` leaf types. Full protocol codecs appear only in the sibling
`cfg(test)` compatibility controls. The product client, supervisor driver,
Matrix child, registry, release catalog, program copying, and every full digest
check remain unchanged. No wrapper or executable outside the catalog is used.

Five authored controls compare complete newline-framed Health and Drain
requests and responses in both directions with the real protocol types, across
all existing lifecycle values. They also cover unknown methods, additional or
missing fields, wrong field types, duplicate fields, and unsupported response
payloads. The controls have not been executed in preparation. Existing Bazel
source globs and the binary unit-test module discover these Rust files without
dependency, Cargo, lock, or build-rule changes.

This is compatibility for the two methods actually sent by this fixture's
supervisor. It is not equivalence to the full Agentd protocol. A known but
unsupported full-protocol method previously decoded and then made the child
return an error after reading its lifecycle. It now fails during decoding;
neither path emits a successful response. The private envelope rejects unknown
methods and additional fields, including fields inside either method. The
method variants use empty structs to enforce that boundary; full-protocol
behavior outside the exact Health/Drain frame is not claimed identical. The
existing fixture parsed but did not validate the request
schema version or supplied spawn generation; those fields remain parsed and
unused. Response identity still comes from the child launch environment and
the current lifecycle file, as before. This subset adds no authority.

The existing two product scenarios, PID and generation checks, adoption,
ready/drain observations, all assertions, and the 300-second native budget are
unchanged. The catalog still copies and fully hashes both executables at every
existing admission boundary, including the second admission around revocation
frontier capture. Before recovery in the observed five-pair scenario, the
successful source path entails at least 26 complete executable hash scans,
810,288,960 payload bytes at the recorded fixture size, plus two copies. This
counts bytes presented to the hash code, not physical disk traffic.

Removing unused codec branches is a source-level reduction. No new executable
size or performance result is available. Only normal native CI can establish
the resulting artifact size, compatibility-control results, and whether both
product scenarios complete within the original budget. The separate real
Agentd test's transient healthy=false observation remains unresolved by this
change.
