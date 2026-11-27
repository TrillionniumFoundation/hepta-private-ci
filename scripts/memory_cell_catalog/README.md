# Parameter memory metadata catalog

This research admission index binds typed entity/relation keys and source digests
to one checkpoint version. It stores no answer values, source text, answer
lexicon, or evaluation targets. A known key reaches the model through the existing
`ParametricOwner`; an unknown key returns `unknown` with zero model callbacks.

## Catalog contract

The UTF-8 JSON object has exactly these fields:

| Field | Required value |
| --- | --- |
| `schema` | `hepta.parametric-memory.metadata-catalog.v1` |
| `scope` | The owner's scope identifier |
| `cell_id` | The active cell identifier |
| `manifest_sha256` | Independently retained checkpoint manifest SHA256 |
| `entries` | Objects containing only `entity`, `relation`, and `source_digest` |
| `production_accepted` | `false` |

The host constructs entries from authorized source metadata. The complete catalog
must have an independently retained SHA256 pin. Computing a replacement expected
hash from an untrusted candidate during a read would discard that trust boundary.
Each checkpoint version receives its own catalog and pin.

Files are limited to 128 KiB and 512 entries. Entity identifiers contain ASCII
letters, digits, `_`, or `-`, start with a letter, and have at most 64 characters;
relations follow the same syntax with at most 32 characters. Duplicate JSON fields
and duplicate entity/relation keys are rejected. Extra fields, including `value`,
`gold`, or `lexicon`, are rejected.

## Read API

Include both `scripts/memory_cell` and `scripts/memory_cell_catalog` in `PYTHONPATH`.
The callback uses the already configured model consumer and returns its raw result:

```python
from metadata_catalog import MetadataCatalog

catalog = MetadataCatalog(catalog_path, retained_catalog_sha256)
result = catalog.read(
    owner,
    entity="Alice",
    relation="color",
    provider=current_frontier_provider,
    callback=lambda active, question: model_consumer(active, question),
)
```

The callback receives only `ActiveCell` metadata and the fixed question
`Which color did we assign to Alice?`. Arbitrary question overrides are unsupported.
A successful known read returns `{"status": "known", "response": raw_result}`.
An unlisted key returns `{"status": "unknown", "response": "unknown"}` without
calling `owner.invoke` or the model.

The catalog must match the current owner scope, cell, and checkpoint manifest.
Known reads additionally require source membership in the checkpoint and pass
their source digest to `owner.invoke(query_roots=...)`. Catalog bytes are checked
before admission, before the model callback, and after execution. Stale versions,
withdrawn sources, and changed bytes fail without releasing an answer. The owner
retains its source-frontier and version checks around model execution.

## Evidence and trust boundary

The external source authority, independently retained pins, and current frontier
provider remain trusted host inputs. This module does not authenticate them or
grant production acceptance. The underlying decoder can still generate guesses
for deleted or never-written keys. Catalog rejection does not establish learned
abstention, confidence calibration, or parameter unlearning; clean reconstruction
requires separate model and provenance evidence.

The separate `hepta-parametric-catalog-shadow.yml` workflow runs six focused tests
with real SQLite state and small safetensor fixtures. It downloads no pretrained
model and leaves the existing full confirmation workflow unchanged. The tests
cover known raw responses, unknown and withdrawn zero-callback reads, stale
versions, provenance mismatch, byte tampering, and metadata/input boundaries.
