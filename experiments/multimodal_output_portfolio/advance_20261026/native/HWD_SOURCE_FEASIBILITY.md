# HWD+ prospective source feasibility

Reviewed 2026-10-26. This is a metadata review for a possible later study. It
does not change the current candidate, allocation, qualification, or confirmation.
No HWD+ image pixels have been read, no model has been run, and no source roles
have been assigned.

## Finding

**The authors' public release is technically accessible and contains a usable
writer grouping scheme, but it has no formal dataset license and provides only
97 reported writer groups.** It is a candidate for a separately registered study,
not additional evidence for the current frozen study.

The primary references are the [author paper, sections 3.1–3.2](https://arxiv.org/html/2011.07946v3),
the [journal record](https://doi.org/10.1007/s42979-022-01494-2), the
[author's publication page](https://cedricbeaulac.github.io/publications/), and
the [author-linked public folder](https://drive.google.com/drive/folders/1f2o1kjXLvcxRgtmMMuDkA2PQ5Zato4Or?usp=sharing).
The public folder was retrieved without an account. Its captured HTML is
355,133 bytes, SHA-256
`3761ee972687fced53a827293eba2355d6922b4b221fef54296f5f6f24ea943c`.

## Observed release files

| File | Public Drive file ID | Reported bytes | What was actually read |
| --- | --- | ---: | --- |
| Images(28x28).npy | `1qBkt85sT-R0HMla4s8t6AtDSYDjaeZ6i` | 85,173,888 | 128-byte NPY header only |
| WriterInfo.npy | `1xAy5eAdM0mRTjlrmo1PIMqTp4DUCJpY0` | 489,008 | 256-byte prefix; only array header interpreted |
| ReadMe.pdf | `102-k2jiK5y6CwS-Q-KDPLIb1t4B8nCTg` | 18,998 | Complete author documentation |
| Datasheet.pdf | `1keeFlpavCr9VEl0KyvvFvwJO1oU8V8FW` | 185,040 | Complete author documentation |
| Images(500x500).npy | `1CInd1YOC0lsEq4_q089SVb7PkhxtrwyE` | 3,395,000,128 | Folder metadata only |

The verified 28px header is little-endian float64, C order,
`[13580, 28, 28]`. The metadata header is little-endian int32, C order,
`[13580, 9]`. Each size exactly matches the corresponding shape, dtype, and
128-byte header. The public download entry is
`https://drive.usercontent.google.com/download?id=FILE_ID&export=download`.
The 28px download initially presents a standard large-file scan notice; its
public confirmation form then honored `Range: bytes=0-127` with HTTP 206.
The complete image array and its whole-file hash remain unverified.

The author [ReadMe](https://drive.google.com/file/d/102-k2jiK5y6CwS-Q-KDPLIb1t4B8nCTg/view)
defines the first two metadata columns as digit and writer ID. The other seven
personal attributes are unnecessary for this project. Its stated 13,350 metadata
rows conflict with the actual 13,580-row header and byte count; the paper and
datasheet also say 13,580. This discrepancy is retained rather than silently
rewriting the source documentation.

## Writer provenance and rights

The paper describes a distinct volunteer collection: 97 writers, each providing
14 examples of each digit, with pages attached to writer IDs before image
extraction. The author datasheet recommends splits by writer for most tasks.
Thus the published ID is intended to group repeated handwriting from a person.
This review has not downloaded the full metadata values to recount the unique
IDs or per-writer balance. Anonymous IDs cannot establish natural-person
nonoverlap with another anonymous corpus; no re-identification was attempted.

The [author datasheet, section 6](https://drive.google.com/file/d/1keeFlpavCr9VEl0KyvvFvwJO1oU8V8FW/view)
assigns copyright to Cédric Beaulac and explicitly states “There is no license”.
It describes public research distribution and requests citation. This is not a
CC/BSD/MIT license or evidence of unrestricted redistribution or commercial
rights. The paper's own publication license does not supply a dataset license.
Raw arrays should not be republished as if that permission had been established.

## Limits on a later fresh split

At most 97 source-local writer groups exist before allocating development,
calibration, qualification, and confirmation roles. Fourteen replications,
multiple digits, or multiple views do not increase that independent group count.
The collection is a nonrandom volunteer sample, and source-local disjointness
does not establish representative IID sampling.

For scale only, if one had 97 independent Bernoulli trials and zero errors, the
one-sided 95% exact upper bound would be `1 - 0.05^(1/97) = 0.0304118040`.
At least 598 such zero-error trials would be needed to reach an upper bound of
0.004999. Those IID assumptions are not established here. HWD+ therefore cannot
alone provide that bound using one trial per writer, and cannot replace a
separately designed missing-request/OOD scope. Splitting the 97 groups further
reduces evaluation precision. Efficacy and calibration power require a new
prospective calculation after the split and relevant effect are defined.

The paper also describes white-background scans and uncentered digits; direct
use in a QMNIST pipeline would introduce a distribution change. A fixed
polarity, range, and preprocessing rule must precede fresh-source predictions.
No preprocessing choice has been compared on these images.

## Evidence locations

The machine-readable companion, `HWD_SOURCE_FEASIBILITY.json`, records all file
IDs, exact byte counts, observed header schemas, document and prefix SHA-256s,
access scope, assumptions, and local receipts. Raw public documentation and
HTTP receipts are under
`/tmp/hepta-ndu-advance-native/hwd-feasibility-001/`; raw documents are not added
to the repository. No login, author contact, raw-array upload, model execution,
or new source allocation occurred.
