# Incremental retention of original CI records

The two `controls-ci-*` directories retain the original cumulative-control ZIP
bytes using the already published `ci-008-f75bf1ac` packs plus small additional
packs. The base is pinned to commit
`82b4c06add08c5e8e96871831eb6f80464d15968` and manifest SHA-256
`f874ff5d9715413803daf9d097a6e85e9b69924bfe356945519493a5e7749a34`.
No original archive is decompressed and recompressed during retention.

| Original run | Original outcome | Original ZIP bytes | New unique pack bytes | New recipe bytes |
| --- | --- | ---: | ---: | ---: |
| 40498180354 / `60df5f93` | Failed evaluation launch | 117,757,882 | 7,415,366 | 582,152 |
| 40501186161 / `6ba1a5b3` | Completed cumulative diagnostic | 117,865,750 | 7,479,485 | 585,995 |

Both increments depend directly on the unchanged base. The second increment
does not replace or depend on the failed run's increment. Every shared chunk was
compared byte for byte when the increments were built. Every new pack and chunk
has an individual SHA-256 pin. Recipes preserve original ZIP headers, raw
compressed member data, descriptors, central-directory bytes and their order.
Region chunks are at most 256 KiB; additional packs are at most 4 MiB each.

## Reproduce byte and member verification

Use Python 3.11 or newer from the repository root:

```bash
python -I -B qualification/public-initial-v2/restore_incremental_records.py \
  --directory qualification/public-initial-v2/controls-ci-001-60df5f93
python -I -B qualification/public-initial-v2/restore_incremental_records.py \
  --directory qualification/public-initial-v2/controls-ci-002-6ba1a5b3
python -I -B qualification/public-initial-v2/test_incremental_records.py
```

The default operation constructs a seekable original-byte stream without
writing another large ZIP. It verifies the base manifest, all base and new
packs/chunks, the complete original ZIP SHA-256 and byte count, source identities,
the top-level index, the separately pinned nested original index, and every
retained member's size, SHA-256 and ZIP CRC. The nested
`reference/original/evidence-index.json` is explicitly pinned because the
original collector omitted index files from its top-level file map.

Add `--output /absolute/path/new-records.zip` to write the original bytes to a
new file. Existing files are never overwritten. A failure can leave an
unverified partial or complete output file: only a successful exit and the final
verification receipt establish completion. The tool does not extract an archive
or execute its contents. It checks the declared base commit pin and exact base
manifest bytes; it does not contact GitHub or independently resolve that commit.

These are offline readers for the listed, pinned evidence. Archive, recipe,
member and expansion limits reject unexpected sizes. Python's ZIP parser reads
the central directory before the member-count check, so this is not a general
sandbox or a pre-allocation/CPU bound for arbitrary hostile archives. Evidence
directories are assumed to be owned and stable during a run; this does not defend
against a concurrent process with permission to replace their parents or bytes.

## Scope of the results

The failed run remains failed. The successful run completed the additional
cumulative LoRA and full-tune controls. All three candidate/control comparisons
scored `1/2` on the frozen public calibration and evaluation tasks, with zero
candidate margin over the strongest cumulative control. Cumulative steps and
input/supervised token schedules match at 10/20/30, 526/1052/1578 and 40/80/120.
This does not establish equal time, FLOPs, energy, economic cost, independent
future quality or a SystemLongitudinal product qualification.

Candidate and round-one control weights were reused from the actual `f75bf1ac`
run; the successful additional run executed the two continuation rounds for
each control. It did not retrain the candidate, rewrite original results, install
children, modify CURRENT, or replace the original native/ordinary qualification
gates. The ordinary source run remains failed at its original StateLocked
reopen. The separate `45d382fe` ordinary attempt remains a compilation failure.

Separate checkpoint ZIP metadata and every omitted `.safetensors` path are
preserved in each manifest and original index. Those checkpoint ZIP bytes are
not contained here and were not downloaded locally. Their hosted artifact
retention is finite. No complete decentralized weight-storage claim follows
from these records, and the original Agentd plugin-cache/runtime-closure
limitation remains open.
