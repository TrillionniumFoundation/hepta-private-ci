# Physical material for the original Root checkpoint

This change is source-only until its command/source/result records exist.
It does not qualify a production writer, cold recovery or the original
500ms checkpoint exchange budget.

`HostAuthorityService::with_registered_material_archive` is a trusted Root
launch call, absent from the peer wire. It fixes the service's original agent
layout, actual checkpoint peer UID and protected archive once. The original
active-generation parser and retained database/parent/pointer descriptors
select the source. Capture cannot register a replacement generation or inode.

Assembly first reads the independent full protected Current, captures and
validates its physical image, then compares the same full head and retained
canonical writer proof under the original live registry fence. It performs a
final original clock/head check before returning. The sole recovered owner
must still be quiescent; checkpoint binding and Session release follow this
acknowledgement. Missing/Dirty/Fenced state is not fresh initialization.

Images use the original Hepta agent geometry beneath a Root0700 archive.
The directory key hashes the complete serialized logical cut; this is an
index, not Current authority or another operation ledger. Original bounded
retained-descriptor copying, schema-before-expression admission, complete cut,
integrity, consolidation and file/directory fsync remain mandatory. Every new
ancestor is synced. An existing partial image is never overwritten or repaired
from the current live database. Retained images receive only the original
read-only full verifier and fsync; Commit does not reconsolidate Current bytes.

For each original Prepare/Commit, the backend inspects its complete predecessor
and original validation rules. Large copy/SQLite work happens outside the
registry writer fence. An opaque non-Clone/non-Serde image capability binds
the exact original request bytes and complete prospective cut. Under the
original fence, the handler repeats the original request/expected-token/state
checks, validates the held Root-private image identity and metadata, then uses
the same original durable CAS/readback and post-I/O clock check. Valid mutation
or duplicate acknowledgement without matching material becomes Unknown and
permanently fences this publisher. No large hash/copy occurs under that fence.

The original public backend `exchange` remains the Root metadata protocol
primitive used by its existing isolated state-machine fixtures. Actual service
dispatch always uses `exchange_with_material`; open-only CLI service without
the trusted archive registration refuses valid Prepare/Commit. No peer request
can install an archive, source path, image, key, grant or new generation.

The existing read-only BEGIN IMMEDIATE owner barrier was disproved by an actual
competing commit. Its repair and exact owner exclusion remain separate required
acceptance. Physical-copy metadata checks alone do not prove coherent SQLite
pages or effect safety. The original 500ms client deadline stays unchanged;
moving work outside a lease lock does not establish that runtime budget.

Root-private images cannot be directly opened by the Host's CurrentUser60001
guard. Trusted cold bootstrap must separately prove the previous publisher is
retired, revalidate the independently retained Current image and safely install
a new owner-owned candidate using the original recovery/active-pointer protocol.
Old Dirty files and original issuer/consumer state remain. No installer,
Dirty adoption, fresh-store initializer, effect replay, native daemon or
persistent CPU G2 qualification follows from this source alone.
