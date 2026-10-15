# Proposed near-matched Hepta Cell capacity (not a model)

**Research-only / DRAFT / DENY_ALL.** No changes to selected V1, active inference,
the original fixed-width trainer, Q24 kernel, production control, CNS or Final-use.

## Problem and proposed real operators

The existing frozen 32D trainer uses a fixed identity projection, and the
five named 2K–256K ceilings collapse to five distinct realized parameter
geometries across 20 slots. Merely naming a larger ceiling is not training a
larger Cell.

The **new, unimplemented candidate design** freezes one shared feature width
`d`, but gives each Cell a genuinely trainable dense input affine Adapter
(`d -> h`, weights `d*h` plus `h` biases), a private `h -> 1` Head
(`h + 1` scalars), and a resident fixed `h`-weight native Q24 identity
temporal-to-activation projection. The temporal mechanism's actual tensor
shapes are separately counted. No dummy, unconsumed or padded weights exist.

| Arm | Complete proposed private scalar count |
| --- | --- |
| V2 | `(d+3)*h+1` |
| V3 | `(d+6)*h+1` |
| Diagonal SSM | `(d+5)*h+1` |
| Low-rank minGRU | `(d+5+4*r)*h+1` |

For all candidates `5 <= h <= 256`, `1 <= r <= 4` by default,
and input `d=32`. The allowed gap to the same ceiling is **at most 2%**.
This is a *near* count, not equal training FLOPs, equal tensor memory, an
independent runtime model nor an equal capability claim.

### Mathematically generated 32D candidate shapes

| Ceiling | V2 (h, count) | V3 (h, count) | SSM (h, count) | minGRU (h, rank, count) | Geometry |
| ---: | --- | --- | --- | --- | --- |
| 2,048 | 58 / 2,031 | 53 / 2,015 | 55 / 2,036 | 45 / 2 / 2,026 | proposed near-match |
| 8,192 | 234 / 8,191 | 215 / 8,171 | 221 / 8,178 | 182 / 2 / 8,191 | proposed near-match |
| 16,384 | width-limited | width-limited | width-limited | width-limited | blocked |
| 65,536 | width-limited | width-limited | width-limited | width-limited | blocked |
| 262,144 | width-limited | width-limited | width-limited | width-limited | blocked |

This alternative still cannot make all five tiers comparable. In particular,
the 16K+ tiers require genuine additional model operations/architecture or
must be reported as **unequal-size cost–quality frontier observations**.

## Exact executable preflight

```sh
python -m unittest discover -s qualification/neuron-gated-sparse-v3 \
  -p 'test_near_matched_capacity_design.py' -v
python -O -m unittest discover -s qualification/neuron-gated-sparse-v3 \
  -p 'test_near_matched_capacity_design.py' -v
python qualification/neuron-gated-sparse-v3/near_matched_capacity_design.py \
  --feature-width 32 --max-rank 4 --max-gap-ppm 20000 \
  --output /tmp/new-neuron-capacity-proposal.json
```

The output is create-only, contains a deterministic planning digest,
unmaterialized tensor shapes and explicit blocked tiers; every authority and
production claim is false. The existing Neuron A0 negative-test job discovers
the standalone tests automatically.

Local Python 3.13.5 passed 11/11 normal and 11/11 optimized-mode tests for
the exact two script blobs. Hosted CI results belong to their **own exact
HEAD** and are not inferred from these local tests.

## Mandatory work before calling anything 'matched'

Implement an actual trainable input Adapter with Q24-compatible native
forward, publish physically realized safetensors, verify every shape and
SHA against this proposal, freeze the identical Encoder/input cases, and
measure actual optimizer cost, memory and task performance. The adapter and
hidden width cannot be silently introduced into historic V1 replay or a
selected live checkpoint. Independent A0, prospective negative-transfer/NDU,
full native target-host 64–4096 Cell recovery and producer/observer custody
remain blocked.

**No model winner; no automatic promotion, NDU grant, main merge or physical split.**
