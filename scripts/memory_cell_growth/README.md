# Sequential arrival into parameter memory

This fixed research probe asks whether an existing fifteen-color memory can
acquire fifteen new shape assignments for the same entities. Shape values are
randomly assigned from a predeclared vocabulary; it tests recall of written
sources, not acquisition of an architectural cell type or unseen-fact reasoning.

This probe uses the completed lifecycle's actual clean `rebuilt-cell` parent,
after Alice's two source versions were revoked and Bob's correction replayed.
The retired original `written-cell` cannot be admitted. Independently retained
SHA-256 pins bind the clean checkpoint, exact fifteen replay sources, and epoch-1
withdrawal provenance in `growth_protocol.py` and `fixtures/`. A regenerated run
can have different receipt timestamps and cannot silently replace that parent.

## Fixed protocol

| Item | Registered value |
| --- | --- |
| Incoming relation | `shape` |
| Vocabulary | circle, square, triangle, oval, star, cube, sphere, cone |
| Arrival shuffle seed | 718203 |
| Decoder seed / LoRA rank | 2718 / 8 |
| Learning rate | 0.001 |
| Single continuation | One adapter, 480 updates on all 30 facts |
| Split candidate | Two adapters, 240 updates each, old colors / new shapes |
| Nochange | One current clean parent artifact, zero new updates |
| Final acceptance recall | At least 0.75 separately on old and new sources |

The shape vocabulary is fixed before the run. Its sixteen-item duplicated list
is shuffled with the registered seed, then the first fifteen values are used.
Token bounds are checked without
changing values in response to answers. Train, source-selection and final
wordings must be distinct after tokenization. The protocol is flushed before
training; complete source identity is recorded before and after execution.

Both trainable candidates start from the same verified parent. The shape child
inherits all color ancestry even though its new updates use shapes only. Every
source/template receives real gradient exposure. Single and split consume equal
total optimizer updates and sixteen visits per fact: 960 actual new updates
across all candidates. Split retains twice the private parameter bytes; this
is explicitly not a matched-parameter or equal-FLOP comparison. Actual tokens,
source-specific training loss, checkpoint bytes, inherited parent training,
shared base, source ledger and SQLite costs are reported separately. The 512-step
clean replay is a shared inherited cost; original and correction write costs are
also retained separately. The earlier evolution research is excluded from that
upstream-write subtotal and must not be mistaken for zero historical cost.

## Selection and reads

Selection uses source-held-out wording before final worker questions are read.
Every parent-correct old item must remain correct. Single must add at least one
correct selection answer; split must add at least two over the best eligible
cheaper arm. Equal-quality outcomes keep nochange or single. Additional split
bytes are an explicit cost vector; no monetary utility or compression is inferred.

Routing uses declared relation metadata: colors go to slot 0, shapes to slot 1
for split, and all questions go to slot 0 for the one-adapter arms. This is a typed
namespace route, not emergent or learned routing. Final scores cannot modify the
already saved choice. Every parent and candidate root must be disjoint from the
pinned revoked frontier before training or reading. A new local owner admits and
checks each final callback before and after inference, without altering the old
owner database. The frontier is an independently pinned local snapshot; this
experiment does not connect a live external source authority.

Four fresh reader processes consume only weights, scope,
provenance hashes and question strings. The nochange parent's raw answers to new
shape questions are unwritten-memory diagnostics, not admitted knowledge claims.

Final old/new recall and retention are acceptance gates. A negative result is
preserved and the program exits 1; the recipe must not be tuned after seeing it.

## Run

Use the pinned runtime in `scripts/memory_cell/requirements.txt` and the verified
base prepared by `scripts/memory_cell/prepare_parametric.py`. The clean parent
is available in the separately retained seven-checkpoint archive.

```bash
PYTHONPATH=scripts/memory_cell:scripts/memory_cell_growth \
python -B scripts/memory_cell_growth/growth_trial.py \
  --model /path/to/verified/smol135m \
  --parent /path/to/original/lifecycle/rebuilt-cell \
  --source-facts scripts/memory_cell_growth/fixtures/clean-replay-facts.json \
  --output /path/to/new/arrival-run
```

The CLI accepts paths only, with no tuning overrides. The focused tests use a
real tiny decoder, real source updates and four fresh reader processes. They also
cover tie rejection, two-answer split improvement, retention, source ancestry,
closed reader inputs, before-fit withdrawal rejection and invalid source/cost
boundaries. Production acceptance,
general memory, learned routing and storage superiority remain unproven.
