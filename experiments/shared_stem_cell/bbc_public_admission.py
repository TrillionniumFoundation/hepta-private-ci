"""Label-free BBC publisher admission against the exact historical AG archive.

New publisher TEXT only, no BBC gold. Previous archived AG data has labels,
but only historical text and SHA identity are consumed for exclusions.
Never trains models, compares labels or grants production authority.
"""
from __future__ import annotations

import argparse
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile

from experiments.shared_stem_cell import external_bbc_shift as b
from experiments.shared_stem_cell.bbc_source_attestation import attest

ARCHIVE_SHA = "05b6ec4b33a7563ea368f7d5be212ad1dbf1220bbccb9195ac900ac5adde34a6"
PRODUCER = "hepta-public-study/dataset.jsonl"
OLD_COHORT = "hepta-fresh-confirmation/cohort.json"


def prior_texts(archive):
    """Require the externally pinned original ZIP before any provenance claim."""
    path = Path(archive)
    b.require(path.is_file() and not path.is_symlink() and
              0 < path.stat().st_size < 32 * 1024**2,
              "missing ordinary historical source archive")
    data = path.read_bytes()
    b.require(b.digest(data) == ARCHIVE_SHA,
              "historical AG source archive changed")
    with ZipFile(BytesIO(data)) as z:
        names = z.namelist()
        b.require(len(names) <= 512 and len(set(names)) == len(names)
                  and z.testzip() is None,
                  "invalid historical source ZIP inventory")
        for key in (PRODUCER, OLD_COHORT):
            b.require(key in names and
                      0 < z.getinfo(key).file_size < 16 * 1024**2,
                      "missing required historical text source")
        raw_producer, raw_previous = z.read(PRODUCER), z.read(OLD_COHORT)
    original = [json.loads(line) for line in raw_producer.splitlines()]
    previous = json.loads(raw_previous)
    b.require(len(original) == 128 and type(previous) is list
              and len(previous) == 1024,
              "unexpected old producer/confirmation cohort size")
    exclusions = []
    for row in original:
        b.require(type(row) is dict and type(row.get("text")) is str
                  and type(row.get("case_id")) is str,
                  "old producer text/identity missing")
        exclusions.append(row["text"])
    for row in previous:
        b.require(type(row) is dict and type(row.get("text")) is str and
                  b.digest(row["text"].encode()) == row.get("text_sha256")
                  and b.digest(b.normalized(row["text"]).encode()) ==
                  row.get("normalized_sha256"),
                  "old frozen confirmation source changed")
        exclusions.append(row["text"])
    b.require(len(exclusions) == 1152,
              "incomplete previous-source exclusion")
    return exclusions, {
        "schema": "hepta.shared-stem.bbc-prior-exclusions.v1",
        "historical_archive_sha256": ARCHIVE_SHA,
        "original_producer_rows": 128,
        "older_fresh_confirmation_and_eval_rows": 1024,
        "exclusion_sha256": b.digest(b.canonical([
            b.digest(b.normalized(s).encode()) for s in exclusions])),
        "label_fields_used": False, "production_accepted": False,
    }


def run(archive, output):
    """Separate actual BBC TEXT-only public acquisition, no Encoder or model."""
    from datasets import load_dataset
    from huggingface_hub import HfApi
    from experiments.shared_stem_cell.wire import write_once
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    try:
        excluded, previous = prior_texts(archive)
        b.require(HfApi().dataset_info(b.SOURCE, revision=b.REVISION).sha ==
                  b.REVISION, "official BBC publisher immutable revision changed")
        dataset = load_dataset(b.SOURCE, revision=b.REVISION, split="test",
                               cache_dir=str(output / "hf-cache"))
        texts = b.public_text_column(dataset)
        b.require(len(texts) == 1000, "BBC publisher test split not exactly 1000")
        cohort = b.public_cohort(b.sample(texts, excluded))
        selection = attest(texts, excluded, cohort)
        write_once(output / "historical-exclusions.json", previous)
        selection_sha = write_once(output / "source-selection.json", selection)
        write_once(output / "cohort.json", cohort)
        write_once(output / "result.json", {
            "schema": "hepta.shared-stem.bbc-public-source-admission.v1",
            "source_selection_sha256": selection_sha,
            "publisher_test_rows": len(texts),
            "selected_source_rows": len(cohort),
            "bbc_category_fields_read": False,
            "new_model_forward_calls": 0,
            "original_source_gold_used": False,
            "model_qualification": False, "production_accepted": False,
        })
        return selection
    except Exception as error:
        write_once(output / "failure.json", {
            "type": type(error).__name__, "error": str(error),
            "source_labels_read": False, "production_accepted": False,
        })
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.archive, args.output)
    print(json.dumps({"publisher_text_rows": result["full_text_column_rows"],
                      "selected": result["selected_rows"],
                      "production_accepted": False}, sort_keys=True))


if __name__ == "__main__":
    main()
