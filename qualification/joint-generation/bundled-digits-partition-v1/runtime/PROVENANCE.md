# Bundled optical digits: provenance and non-training qualification

Audit date: 2026-11-04 UTC. Status: metadata/source-only feasibility audit.
This document does not authorize data decoding, training, evaluation, or opening
any newly sealed test partition. No digit values or labels were inspected.

## Fixed local source identity

Package root:
`/opt/codex/runtimes/codex-primary-runtime/dependencies/python/lib/python3.12/site-packages/`

Installed package metadata identifies scikit-learn 1.8.0.

| Relative path under package root | Identity |
| --- | --- |
| `sklearn/datasets/data/digits.csv.gz` | 57,523 bytes; SHA256 `09f66e6debdee2cd2b5ae59e0d6abbb73fc2b0e0185d2e1957e9ebb51e23aa22` |
| `sklearn/datasets/descr/digits.rst` | SHA256 `8e7e58d612958f7d9b0de1931ed68b211703eeb239e808f3d82c5f0837cc0222` |
| `sklearn/datasets/_base.py` | SHA256 `cbd9ccf882e660f0d4ab0665af8c92f17bf50da78ed24efff7ae6b1b96d618d6` |
| `scikit_learn-1.8.0.dist-info/METADATA` | SHA256 `95a8f42f4170fc940a71fedfed4fd9353723eb44126130a971a072fe5305d967` |

Only filename, stat, and compressed-byte hashing were used for the data asset.
It was not decompressed. Hashing is an identity check, not a sample inspection
or verification that the local data equal an independently downloaded original.

## Documentary dimensions and loader

The bundled description and `load_digits` docstring report 1,797 samples,
10 digit classes, 64 features, and 8 by 8 images of integer counts from 0 to 16.
These counts have not been independently verified by loading the local asset.

`sklearn/datasets/_base.py` defines `load_digits` and
`load_gzip_compressed_csv_data`. Source inspection shows the former passes
`digits.csv.gz` and `digits.rst` to the latter. The helper opens the package
resource using `importlib.resources`, decompresses it with `gzip`, and parses
with `numpy.loadtxt`. The final column becomes the target and the other 64
columns become the image. This documented route needs no download. Neither
function was invoked; no package import was used for this audit.

## Provenance and dataset license

The bundled description identifies the data as a copy of the **original TEST
subset** of UCI Optical Recognition of Handwritten Digits. It describes NIST
preprocessing of handwritten forms: 32 by 32 bitmaps were divided into 4 by 4
blocks, yielding an 8 by 8 matrix of on-pixel counts. The original source split
uses 30 writers for training and 13 different writers for test.

Official metadata inspected without following any data/download link:

- Dataset: [UCI Optical Recognition of Handwritten Digits](https://archive.ics.uci.edu/dataset/80/optical+recognition+of+handwritten+digits).
- Citation: Alpaydin, E. and Kaynak, C. (1998), *Optical Recognition of Handwritten Digits* [Dataset], UCI Machine Learning Repository. [DOI 10.24432/C50P49](https://doi.org/10.24432/C50P49).
- The UCI dataset page explicitly lists **CC BY 4.0**. The [license deed](https://creativecommons.org/licenses/by/4.0/) describes the requirements to credit the source, link the license, and indicate modifications.

The dataset license conclusion is based on this dataset-specific UCI statement,
not the package's separate BSD-3-Clause code license. The local bundle does not
by itself establish a complete chain of historical licensing. Remote metadata
was inspected; remote dataset bytes were not retrieved or compared.

Any later permitted derivatives should retain the citation and license link,
identify the scikit-learn-bundled subset, and disclose corruption, scaling,
partitioning, and other modifications. This audit did not create derivatives.

## Scoped prior-use search

Workspace filename searches found no digit-named experiment files. Relevant
Markdown and protocol searches in
`publish-isolated-utility-20261030/qualification/joint-generation` and relevant
source/doc searches in `remote-joint-source-integration-review-v1` found no
matches indicating `load_digits`, `digits.csv`, Optical Recognition, or
handwritten-digit experiments. The original joint-generation README describes
controlled synthetic colored square/cross scenes; the Fashion README describes
a different, unexecuted natural-data task.

The filename inventory excluded `objective-reconstruction` and paths matching
`authority_source_assessment`; restricted owner sources were not inspected.
No historical result payloads or raw sample/label files were searched.
This is **no prior use found within the stated scope**, not proof that the data
have never been used, exposed, or evaluated anywhere in workspace history.

## Proposed non-training qualification checklist

The following checks can be completed without decoding the data:

1. Recheck the exact compressed asset path, byte count, and SHA256 against the
   fixed identity above. A mismatch fails closed; no fallback downloader,
   alternate mirror, or replacement asset is permitted.
2. Recheck the source and description hashes. Inspect source as text only;
   do not import sklearn, call `load_digits`, decompress the asset, or inspect
   images, row values, labels, distributions, or empirical duplicate counts.
3. Freeze a protocol identity distinct from Fashion and old synthetic/FIT
   studies. Preserve all earlier failures and data-access holds unchanged.
4. Specify partition construction, duplicate grouping, fixed corruption,
   seeds, budgets, candidate/static comparison families, objective, metrics,
   selection gates, and once-only evaluation conditions before data access.
   Rules can be reviewed now; actual partition creation is future authorized
   data processing and is not accomplished by writing this checklist.
5. Design isolated development and evaluation interfaces. Development must
   receive only training/selection records; evaluation data and labels must
   remain inaccessible to model selection. Any partition-builder access to
   all records must be explicitly recorded rather than called zero exposure.
6. Review the split/loader/fail-closed logic with hand-constructed synthetic
   fixtures only, if separately implemented. Tests must not resolve or open
   the real asset, invoke the real loader, train a content model, or create
   an evaluation-open marker. No such tests were run in this audit.
7. Keep all corruption variants and exact duplicate images in one partition
   under a preregistered rule. Duplicate discovery itself requires authorized
   future decoding; it is not established by metadata inspection.
8. Before any data execution, require an explicit parent decision that the
   independent domain is authorized and the protocol is frozen. Do not treat
   successful source qualification as permission to train or open test.

## Claim boundaries

A new sealed split would be untouched **by the new experiment**, subject to the
recorded partitioning procedure, not the original UCI untouched benchmark TEST.
The data were already public benchmark material. The documented loader exposes
no writer identifiers; an ordinary row split does not establish writer-disjoint
generalization. No model performance, dataset novelty across all prior history,
general multimodal capability, or original Fashion completion is established.

No Fashion endpoint, alternate mirror, restricted owner source, runtime model,
remote computation, training process, or sealed test was accessed for this audit.
