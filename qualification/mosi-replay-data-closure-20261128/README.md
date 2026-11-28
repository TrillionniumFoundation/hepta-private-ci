# MOSI publication: include the exact replay data dependency

The original fresh_map ran the saved-prediction verifier with
reconstructed/data.json, but omitted that file from its publication mapping.
A receipt could therefore bind exactly to an incomplete mapping. The omitted
file determines the sealed data identity, feature-preparation cost and split
video counts used by the verifier.

## Change

Based on commit 54c8fe3c8f04b1871d64e360463fcb576a3906d4, the production change is
confined to fresh_map. It explicitly verifies the existing data manifest
against FRESH_SEAL.json, passes that same path to the original verifier and
includes it as data.json in the publication mapping. Terminal entries cannot
replace any of the seven required root objects. Source, quality, receipt,
manifest and fixed-commit object gates remain in force.

A complete future fresh publication has 166 payload entries, or 167 objects
including verified_objects.json. An older receipt binding the incomplete
mapping is preserved and rejected; the patch does not silently upgrade it or
republish after a failed resume.

## Actual controls and retained failures

| Attempt | Actual outcome | Interpretation |
| --- | --- | --- |
| Untouched existing suite | 12 pass, 3 fail of 15 | On Python 3.14 the fixture's global time.sleep patch also intercepted subprocess.wait. |
| Existing suite with fixture isolated | 15/15 pass | Only the relay module's time binding is replaced; the no-wait assertion remains. |
| Old mapper counterexample | Reproduced | The verifier receives the data path, but the old mapping, manifest and object expectations omit it. |
| First new suite | 20 pass, 1 error of 21 | The fixture returned an earlier Git commit; the receiver correctly rejected missing provenance. |
| Final candidate | 21/21 pass | The fixture now returns its new actual tree. All original fifteen test bodies remain unchanged. |

The six added methods cover the data path from the explicit hash gate through
verifier arguments and published objects, correct new publication, missing or
wrong local data, missing or wrong remote data over both API and real native Git
readback, old incomplete receipt retention, and all seven reserved-key
collisions. The collision tests use deliberately conflicting hash values;
rejection of even a same-bytes collision follows from the unconditional
membership check and is not claimed as a separately executed subtest.

These controls use recognizable synthetic publisher fixtures and real local Git
objects. Model arithmetic and the unused NumPy import are explicitly stubbed.
They are publishing integrity controls, not scientific experiments. Complete
first-failure logs, source preimages, local Git controls, final sources and
invocation records are in controls.tar.gz.

## Actual original-data recovery and original verifier replay

The original data file was recovered without modification from its producer
path. Its 3,083 bytes have the exact sealed SHA256
968dfb23d19f7ba50c9907b2146810e09922283b4b4342618e8d2eac151c4f70.
The bytes are provided as original-data-968dfb23.json; the original host,
path and file version are retained in the recovery receipt. The old missing
observation and the earlier rejection of a different ed0aff... manifest are
not rewritten.

The replay used only copies from fixed raw commit
[4b84b0431b089ccac84c75ac3ac19f96ad804fe4](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/4b84b0431b089ccac84c75ac3ac19f96ad804fe4/qualification/hcsn_sustained_20261128/mosi_fresh_raw)
and the recovered data, in a new isolated directory. All 165 original payload
objects and their original canonical index were checked by size, SHA256 and Git
blob identity. All 159 terminal entries, 36 fit receipts and 49 actual weight
objects match their sealed identities. The original raw commit remains intact;
this package supplies the missing dependency separately.

Exactly one invocation of the original
[verify.py at 4f80d069218e5416be0f51323a9db46b461d07dd](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4f80d069218e5416be0f51323a9db46b461d07dd/qualification/hcsn_mosi_three_stream_20261127/verify.py)
then ran with the same enrolled DESIGNS and SHARED constants as the sealed
fresh driver. Its source SHA256 is
bdbb45e0ad4227ef2750bb7d35ca4d2035b1c9fd8257d2c4e2c7ed7fa76b17af.
Python 3.12.3, NumPy 2.5.4, one BLAS/OpenMP thread and nice 10 were used.

The original arithmetic replay passed: 36 fit jobs, 108 eligible prefixes,
684 prediction vectors and 469,224 scalar entries across three seeds,
686 clips and 31 test videos. SUMMARY.json and all_intact_models.json are
both byte-identical to the published originals. Their SHA256 values are
b4de92a5706d9b2d89373fa1cb7e965262bd0d3c38db54d25d4189689bdc65b7
and 631692a3df88adc6c4b8490c6c6fdbafeb8024b0cfba9d3807b0b2f835f2ef11.
The invocation took 1.243905663 seconds with peak RSS 43,488 KiB. This is
arithmetic replay duration, not training duration.

original-replay.tar.gz includes the original verifier, invocation wrapper,
fixed-object inventory, actual stdout and result, copied seal/terminal/source
metadata, exact recovered data and derived outputs. No producer scientific
directory was read during this replay, and all copied inputs retained their
hashes. There was no forward inference, training or independent physical
retiming. Weight-to-prediction computation is still the producer's execution;
the original verifier reads saved predictions and compares sealed weight
identities, while the separate transfer check hashes actual weight bytes.

## Formatting and scope

The parent audit executed the exact original just fmt driver with seven
required fixed-byte fixtures and a partial synthetic Git inventory containing
four actual qualification Python candidates, including these two files.
It exited zero in 0.127479410 seconds and reported that no changed files needed
formatting. The formatter's language scope does not include qualification
Python: this is not a Python-format qualification or full-repository formatting
claim. Both candidate SHA256 values remained unchanged and parsed successfully.
The exact receipt is archived. No controls or scientific replay were rerun
after formatting.

The original executor outage is also retained. The alternate host used fixed
source bundles rather than a full repository checkout; the publication parent
and both tested source identities are explicit in RESULT.json.

This patch closes the data-dependency omission. It does not claim a coherent
immutable snapshot across every concurrent source mutation between arithmetic
verification, publication snapshot and hardlink staging. It also changes none
of the scientific quality or matched-quality speed gates. Restored arithmetic
reproducibility does not establish a new foundation model or universal
backpropagation replacement.
