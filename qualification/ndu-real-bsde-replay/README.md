# Independent real-mmBERT / finite-BSDE original-artifact replay

**Shadow evidence only. No newly executed pretrained model. DENY_ALL.** This
checks completed Actions artifacts from PR #1550 at exact historical source
`a31321e8c95872d2239afcc1d42fb1c4f2c1f03f`, run
[38532946146](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38532946146).
The separate P0 Granite 97M/mmBERT-heavy study is still queued on #1923; this
replay does not change its HEAD and does not call the model worker.

## Evidence and immutable input inventory

Six original ZIPs, pinned by **full outer SHA-256**, are required. No historical
result is silently substituted if an artifact expires or download fails.

| Research arm | Artifact ID | ZIP SHA-256 |
| --- | --- | --- |
| Independent targets composition V3, real frozen mmBERT | 11883369189 | fe4e431223d31f92c9ce62b5906e8159bdfd262464bdb59d85fc39822324e928 |
| Independent targets V2, real frozen mmBERT | 11883734135 | 700dcf2e370e648dec3249954e7394b09bca84cf1ae93d061d8149f2fdd27017 |
| Label balanced V1, real frozen mmBERT | 11884466452 | f989b01b4c9ada906648eb95aa5f50761cbd9e31b2ddc12ea6aa9068f4f79b6e |
| Hash reference / banking budget failure | 11883753667 | a6ff38082a4169fd69a02bde4b448c240552743b09381021acea94afdc104d98 |
| mmBERT / travel guard budget failure | 11896021005 | 88f5f4d012153c7697ccdeb8f07217b16493cc9dbf9c80f02d5beb0210ffc47b |
| mmBERT / banking budget failure | 11889260783 | f53229b650e2f8e25db78f892d750323495fb06446cb7a0ed9916be40fc15df4 |

The auditor uses only Python standard library. It recomputes each **test**
closed-form AND/OR probability from the original public formula and original
leaf-belief arrays. It independently checks per-row source digest, case coverage,
sealed answer probability/English decoding, raw CPU counters, finite-tree
BSDE edge residuals, full historical summary reconciliation, and production
NO-GO flags. It verifies every archived failure attempt, all CPU phase sums,
linked attempt IDs, the unchanged 100 ms view cap, and the original terminal
failure record. The historic journal hash chain is **not externally signed**;
matching a self-reported digest only proves internal consistency of the pinned ZIP.

## Actually observed historical outcomes

| 192-case profile | Closed-form correct | Finite-tree BSDE correct | Closed-form CPU ms | BSDE CPU ms | Extra BSDE CPU ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| Composition V3 | 192 | 192 | 27.231053 | 42.038915 | 14.807862 |
| Independent targets V2 | 192 | 192 | 10.277391 | 14.853562 | 4.576171 |
| Label balanced V1 | 192 | 192 | 10.858489 | 26.731115 | 15.872626 |

The **maximum** cross-arm prediction discrepancy is `2.220446049250313e-16`.
These CPU figures are sums of all 192 individual prediction CPU measurements,
not model loading, end-to-end rollout, measured p99, energy or quality-matched
full lifecycle costs. The finite BSDE with zero generator and independent
read-once leaves is an algebraically equivalent *more expensive* computation;
there is no justified incremental FBSDE reasoning-quality gain in these tasks.
The generated questions reuse source utterances and public training data; there
are no independently authenticated future source families or natural-world
reasoning annotations. There is no proof of FBSDE global solvability.

Failed original view observations (the same unrevised `100,000,000 ns` budget):

| Arm | Failed view CPU ms | Dominant phase | Completed experiment? |
| --- | ---: | --- | --- |
| Hash/banking compiled Head | 114.131173 | Head | NO |
| mmBERT/travel guard | 213.011573 | Encoder | NO |
| mmBERT/banking | 232.095564 | Encoder | NO |

The source clock auditors explicitly state that tail *cause is not established*.
The measured dominant phase describes **where time was charged**, not proof
of an isolated causal explanation for timing spikes. Tail replay repeated a
small controlled set of inputs; it cannot establish overall request p99.
No post hoc relaxation or treating unfinished/failing arms as zero-cost successes.

## Reproduction

```bash
# Under the workflow, six complete GitHub artifact ZIP files are acquired with
# source SHA verification and stored only in runner-private temporary storage.
python3 -W error::ResourceWarning -m unittest discover \
    -s qualification/ndu-real-bsde-replay -p 'test_*.py' -v
python3 -O -W error::ResourceWarning -m unittest discover \
    -s qualification/ndu-real-bsde-replay -p 'test_*.py' -v
python3 qualification/ndu-real-bsde-replay/independent_audit.py \
    --archives /absolute/archived-zip-directory \
    --output /new/independent-replay.json
```

Inputs must be `artifact-<id>.zip` for **exactly** the six pinned IDs. The
report is create-only. Tests have purely synthetic ZIPs and are never
misrepresented as pretrained model efficacy. The hosted job does replay real
completed historical artifacts, without executing any model.

All permissions remain read-only; `blocking-ci`, architecture, original
security owners, P0 physical selection, continuous P5 qualification, and
Neuron/FinalUse production authority are independent. `production_accepted`
remains false even after a successful evidence replay.
