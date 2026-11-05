# V4 independent language and new typed memory development

## What is new, and what the experiment can establish

V3's numerical monthly tables and supplied arithmetic operations did not
demonstrate learned procedural parameters or direct short-text memory. V4 adds
two explicit write/read contracts:

1. A procedural cell fits an affine map from demonstration input/output pairs.
   Its loaded artifact contains coefficients, normalizers, observed ranges,
   dimensions and type signatures. It contains no demonstration rows or hidden
   answers. Hidden function inputs differ from the written demonstration inputs.
2. An event cell writes signed quantities, prices and three short UTF-8 text
   fields from a new retail transaction source. Its loaded parameter reader
   contains fitted factors and value-free record/time addresses. Strings are
   reconstructed from length-prefixed learned byte coordinates, with no category
   vocabulary or record-to-answer table.

The affine hypothesis family, units, program IDs, typed chain order and the
`quantity * unit_price_pence` multiplication primitive are supplied. The cell
learns coefficients, not program syntax, graph topology or new algorithms.
The ordinary least-squares control fits the same family and is expected to match
the procedural cell. No algorithmic advantage over that control is claimed.
An out-of-family quadratic program is retained as a negative control.

The event writer uses the frozen V3 `FactorBank`; this is a new typed interface
and source, not a claim that the factorization algorithm itself is new. The
event experiment measures recalls of already written facts. It does not predict
unwritten transactions. Scientific or broad general memory remains unproven.

## Independently authored formal language

`held-language/query-templates.json` contains 144 supported expressions, with
24 per intent, and 72 near-neighbor unsupported expressions in 12 families.
Each expression was individually authored; changing a date or series name is
not counted as another independent language observation. The six semantics
match the frozen numeric executor. The exact schema and calendar provenance
are documented in `held-language/SCHEMA.md`.

The routing owner received only schema, counts, path and digest during model
development. No router was run on this file before formal execution. An AST
string comparison found zero verbatim overlap with V3's train, selection,
development and held templates. This is an authored English fixture collection,
not an independently sampled population of human requests.

The fixture has 112,340 bytes and SHA-256
`7c952dbcf3625200f748b7a18db432f5f4abccabae8c056eef81fe623abeb895`.
Its JSON root is an object with the templates in `rows`, not a top-level list.
Inference receives only the rendered utterance and explicit series/date slots.
Intent, family, expected operation and provenance are evaluator-only fields.

## Independent retail source and frozen extraction

The official source is [UCI Online Retail](https://archive.ics.uci.edu/dataset/352/online+retail),
attributed to Chen (2015), DOI [10.24432/C5BW33](https://doi.org/10.24432/C5BW33),
under the source's CC BY 4.0 license. The source describes transactions from a
UK non-store retailer, spanning December 2010 to December 2011. Quantity is
signed item count; UnitPrice is denominated in sterling.

The downloaded [official ZIP](https://archive.ics.uci.edu/static/public/352/online%2Bretail.zip)
is retained as `sources/retail/online-retail.zip`: 23,715,478 bytes,
SHA-256 `f5385cbb54bbebf7196389109c6b0621faab0c304e3702548165e71c84aede8b`.
The original workbook member is bound separately in `SOURCE_MANIFEST.json`.
The parser uses the standard-library ZIP and XML readers and verifies the
original ZIP digest before extraction.

The extraction policy was fixed before model experiments: select the first
eligible row at or after each of 1,024 equally spaced positions between the
first and last original event rows. It does not use a training seed, prediction
or model error. Rows missing required fields, nonintegral quantities or prices
not exactly expressible in pence are skipped by advancing to the next row.
There were 162 such selected-position price/quantity skips. Signed quantities,
cancellation invoice IDs and zero prices are retained; 25 of the 1,024 selected
records are cancellation/return records. Description and CustomerID are not
included in the selected memory source. No claim concerns compression of the
complete original workbook.

UnitPrice is converted exactly from decimal GBP to integer pence. InvoiceDate
uses Excel epoch 1899-12-30 and nearest-second, half-up conversion to an ISO
local timestamp, without inferring a time zone. The first 384 selected records
are the development source; the remaining 640 are the formal source. The
source file hashes and extraction rules are in `SOURCE_MANIFEST.json`.

| Partition | Events | Observed months | Canonical bytes |
| --- | ---: | --- | ---: |
| Development | 384 | 2010-12 through 2011-05 | 77,258 |
| Formal source | 640 | 2011-05 through 2011-12 | 128,918 |

The source was fixed and parsed before model development. Formal source values
were not used for development training or model selection. Source preparation
and reporting date coverage do not constitute a formal model evaluation.

Invoice timestamps are charged explicit addressing metadata and are excluded
from parameter-recall targets. The five target fields are `quantity`,
`unit_price_pence`, `stock_code`, `country` and `invoice_no`. Three targets are
direct UTF-8 text. Root's joint language experiment may create a separate,
charged month-to-event-ID view by choosing the first selected source row in
each month. That view represents one selected event per month, not all monthly
transactions or a monthly aggregate. It reuses the trained event artifact.

## Interfaces and artifact boundaries

```python
cell, write = LearnedAffineCell.fit(
    demo_inputs, demo_outputs,
    program_id="program_0", input_type="gross_pence", output_type="discounted_pence",
)
cell.save(path)
loaded = LearnedAffineCell.load(path, expected_sha256=write["artifact_sha256"])
loaded.read([amount])
compose([first, second, third], input_matrix)

receipt = write_event_memory(source, directory, seed=seed, max_rank=None)
memory = EventMemory.load(
    directory, mode="parameter", expected_metadata_sha256=receipt["metadata_sha256"],
)
memory.read(record_id, "stock_code")
```

An event read returns `{"kind": "integer" | "text", "value": ..., "support": [...]}`
or abstains when a learned byte sequence is invalid. It does not silently repair
or clamp invalid UTF-8. `read(record_id, "invoice_at")` is rejected because that
timestamp belongs to the explicit address schema rather than the recalled
target inventory.

`mode="residual_exact"` requires the separately bound residual manifest and
archives. This arm reconstructs the exact source through the matching loaded
model and explicit signed residuals. The residual and its decoded runtime
arrays are charged. It is never reported as a pure parameter read. The complete
selected source, including time/address metadata, can be reconstructed for
replay without retaining another uncompressed copy in the deployed memory.

Pure parameter deployment includes every field's factor artifact and the full
record/time/schema/model-binding JSON. Exact deployment adds every residual
archive and its binding JSON. The conventional controls store complete records
or packed numeric/UTF-8 columns, each using raw, zlib or LZMA storage; the
strongest actual serialized control is selected by bytes, not a weak raw-only
comparison. Every control is decoded and checked against all selected records.

Affine artifacts use magic `HMAFF4\0\0`, a canonical JSON header and little-endian
float64 arrays in declared order. Every normalization/range/type/header byte
is charged. Serving needs the three loaded models and the supplied chain
manifest. The durable/retrainable cost also includes the retained compressed
demonstration archives. Ordinary OLS receives the same examples and retains
its own serialized coefficients, type/range schema and the same replay cost.

## Runner and fixed development protocol

```python
run_transfer(protocol, output, source_commit, seeds, development=False)
```

`protocol["transfer"]` may specify these bounded, predeclared settings:

```json
{
  "event_rank_caps": [2, null],
  "event_queries_per_field": 64,
  "event_chain_queries": 128,
  "procedure_demo_count": 24,
  "procedure_queries": 128,
  "procedure_tolerance": 1e-7,
  "chain_tolerance": 0.005
}
```

The two event ranks are fixed comparisons, not a hidden-query selection grid.
Both fit the same full SVD before retaining their declared factors. Twenty-four
examples identify each affine map, including the two endpoints of the declared
input range. Ninety-six hidden inputs lie inside that range and 32 outside.
The three affine maps have separately generated coefficients for each seed.

Development seeds are 8011 and 8017. Formal seeds 401, 409, 419, 421 and 431 may
run only after root freezes the entire source/protocol. Event SVD models are
deterministic across seeds; repeated seeds are not independent factorization
trials. Seeds change procedural examples/parameters and hidden read addresses.

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  python qualification/memory-cell-v4/transfer_study.py \
  --output qualification/memory-cell-v4/results/development/transfer-example \
  --seeds 8011 8017 --development --source-commit BASE_COMMIT
```

Each seed writes `full_rank/memory/parameters/` and `full_rank/memory/exact/`,
along with the `rank_2` comparison, procedure artifacts, all conventional
controls, target-free fresh-process requests and separate evaluator targets.
`transfer-summary.json` has `results[i].event_arms.full_rank.write` with the
manifest digests and storage counts. The joint runner must reuse this memory
instead of training another hidden duplicate.

Each event arm runs both read modes in new Python processes, with only model
paths, explicit addresses and query arguments. No source path or target array
is passed to the reader. This is a fresh process and a strict input interface,
not an operating-system sandbox claim. The reader reports parameter array
bytes, residual array bytes, wall time, process CPU and peak process RSS where
the platform exposes it. Shared Python/NumPy infrastructure is identified
separately from incremental storage; inference source-code bytes are also
reported. The raw source, canonical source, research artifacts and replay state
remain visible in the cost ledger.

## Initial development result, before final source freeze

The immutable development run `transfer-initial-8011-8017` completed both seeds
and eight fresh reader processes. Its exact executed-file snapshots accompany
the run. The recorded `ddd2ec4` is the then-declared Git base, not a claim that
all executed V4 source already existed in that V3 commit. Later bookkeeping,
module extraction, bootstrap-order and audit changes are recorded in a new
development run rather than modifying the old evidence.

| Event arm | Pure parameter exact, each field | Parameter state | Model + residual exact state | Strong complete exact control |
| --- | --- | ---: | ---: | ---: |
| Full rank | All five fields 100%, both seeds | 48,730 B | 50,642 B | 6,017 B |
| Rank 2 | Numeric fields 100%; all three text fields 0%, both seeds | 28,915 B | 33,092 B | 6,017 B |

Each field had 64 hidden read coordinates per seed. Both residual arms read all
five fields exactly. Full-rank model-plus-residual storage is 8.4165 times the
strong column/LZMA control; rank 2 plus residual is 5.4998 times the control.
These are clear storage failures, despite successful full-rank parameter reads.

The three-cell affine chain answered all 128 previously unwritten function
inputs per seed within absolute tolerance `1e-7`. Maximum errors were
`8.73e-11` and `7.28e-11`. Ordinary OLS also passed, with maximum prediction
difference `2.91e-11` relative to the procedural cells. The retail-fact-to-program
chain had mean errors around `1e-12` pence. The quadratic negative control had
MSE `1.68e11` and `1.63e11`; an affine writer does not learn arbitrary programs.

Each seed performed 10 event SVDs, SVD work proxy 284,928, and seven least-squares
solves including ordinary controls and the negative program. Actual training,
source-codec searches, process reads and all retained artifacts are reported.
These results establish a bounded mechanism for new typed facts and a declared
program family. They do not establish compression superiority or reliable
general-language transfer.

## Read-only audit

`v4.typed_memory_audit.audit_transfer(run_directory, output, source_directory=None)`
accepts either a standalone transfer directory or an integrated run containing
`transfer/`. Output must be a new file outside that immutable run. It validates
fixed source and executed-file identities, all retained file bytes/hashes,
complete conventional/residual source roundtrips, and model/replay/metadata
costs. It recomputes integer factor reads with Python integer dot products and
procedural reads with scalar affine arithmetic, rather than calling the serving
prediction methods. It regenerates the synthetic coefficient truth, checks
demonstrations and all hidden metrics, and verifies actual work arithmetic.
Historical wall-time receipts are not presented as independent timing evidence.

```bash
PYTHONPATH=qualification/memory-cell-v4:qualification/memory-cell-v3 \
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m v4.typed_memory_audit \
  PATH_TO_RUN --output qualification/memory-cell-v4/validation/typed-audit.json
```

Seven independent mechanism tests cover learned multivariate coefficients,
save/load/type checks, family limits, fresh-process target-free reading, direct
UTF-8 readout, residual separation, exact-source codecs, byte accounting and
signed retail source parsing. The initial audit passed 2,666 checks; expanded
audit checks are validated in a later development artifact before formal freeze.

The final pre-freeze development run `transfer-pre-freeze-8011-8017` retained
the same model predictions and storage conclusions after code organization and
cost-ledger additions. Its expanded independent audit passed **2,826 checks with
zero failures**, saved outside the run as `validation/transfer-pre-freeze-audit.json`.
Seven owner mechanism tests and scoped Ruff checks passed before root's final
formatting/source freeze. No formal seed or formal router evaluation was run by
this owner during development.

The later entry-point review also closed the standalone formal bypass:
`run_transfer` rejects before opening any source or creating output unless a
formal request has a literal frozen flag and the protocol's complete ordered
five seeds. The standalone formal CLI reads the current `PROTOCOL.json`, rejects
an alternate byte-different protocol or mismatched commit, and verifies all
source bytes against that exact Git commit before writing. Two additional
entry tests exercise these pre-write failures with held/source reads blocked.
