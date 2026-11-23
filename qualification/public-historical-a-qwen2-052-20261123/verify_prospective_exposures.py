"""Recompute the public exposure fingerprints without training, scoring or receiving B."""

import argparse
from pathlib import Path

import historical_a
from cell_experiments import (
    adoption,
    coding_sft,
    data,
    paired_cold,
    prospective_exposure,
)


def verify(parquet):
    root = Path(__file__).resolve().parent / "run"
    frozen = adoption.read_json(root / "FROZEN.json")
    catalog = prospective_exposure.catalog_for(frozen["candidate"])
    adoption.require(data.digest(frozen) == catalog["freeze_sha256"], "freeze differs")
    prompt, _, source = historical_a.read_source(parquet)
    origin = catalog["public_origin"]
    adoption.require(
        (origin["parquet_sha256"], origin["revision"], origin["row_zero_based"])
        == (source["file_sha256"], source["revision"], source["row_zero_based"]),
        "public row differs",
    )
    texts = {
        "historical_A": prompt,
        "old_rehearsal": historical_a.OLD_TRAIN,
        "old_retention": frozen["retention"][0]["task"]["input"],
    }
    for arm in paired_cold.ARMS:
        manifest = frozen[arm]
        tokenizer = paired_cold.frozen_tokenizer(manifest, root)
        expected = []
        for exposure, text in texts.items():
            rendered = coding_sft.prompt_text(
                text, tokenizer, manifest["runtime"]["message_protocol"]
            )
            ids = tokenizer.encode(rendered, add_special_tokens=False)
            expected.append(
                dict(
                    exposure=exposure,
                    prompt_sha256=historical_a.hashtext(text),
                    input_ids_sha256=data.digest(ids),
                )
            )
        adoption.require(expected == catalog["known_inputs"], "known inputs differ")
    retention = frozen["retention"]
    adoption.require(
        catalog["known_artifact_sources"] == [r["source"]["sha256"] for r in retention]
        and catalog["known_record_ids"]
        == [
            {key: r[key] for key in ("record_id", "source_id", "task_id")}
            for r in retention
        ],
        "retention lineage differs",
    )
    return data.digest(catalog)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("public_parquet", type=Path)
    print(verify(parser.parse_args().public_parquet))
