"""Independent parsing/utility arithmetic and full delivered-byte re-audit."""

import hashlib
import io
from itertools import product
import json
from pathlib import Path
import zipfile

import numpy as np
from PIL import Image
import torch

from ...v6.data import make_batch
from ...v6.neural import ACTIONS
from ...v6.observer import METRIC_DIGEST
from .audit_statistics import audit_statistics
from .data import fresh_corpus, historical_corpus
from .protocol import PROTOCOL as P, checksum, write_json
from .run import reference_observer


def parse_caption(text):
    tokens = text.strip().split(" ")
    if (len(tokens) != 6 or tokens[0] != "left" or tokens[2] != "right" or tokens[4] != "relation"
            or tokens[1] not in tuple(str(i) for i in range(10))
            or tokens[3] not in tuple(str(i) for i in range(10))
            or tokens[5] not in {"less", "equal", "greater"}):
        return None
    return int(tokens[1]), int(tokens[3]), tokens[5]


def utility(image_digits, caption, target_digits, mse):
    parsed = parse_caption(caption)
    relation = "less" if target_digits[0] < target_digits[1] else "greater" if target_digits[0] > target_digits[1] else "equal"
    if parsed is None:
        text_error, relation_error, disagreement = 1., 1., 1.
    else:
        text_error = ((parsed[0] != target_digits[0]) + (parsed[1] != target_digits[1])) / 2
        relation_error = float(parsed[2] != relation)
        disagreement = ((parsed[0] != image_digits[0]) + (parsed[1] != image_digits[1])) / 2
    image_error = ((image_digits[0] != target_digits[0]) + (image_digits[1] != target_digits[1])) / 2
    return 1 - 2 * (.3 * text_error + .15 * relation_error + .35 * image_error + .1 * disagreement + .1 * mse)


def decode_image(raw):
    with Image.open(io.BytesIO(raw)) as image:
        if image.mode != "L" or image.size != (56, 28) or image.format != "PNG":
            raise ValueError("Unexpected actual image profile")
        return torch.from_numpy(np.array(image, copy=True)).float()[None, None] / 255


def score_batch(observer, pixels, captions, batch):
    with torch.inference_mode():
        digits = torch.stack((observer(pixels[:, :, :, :28]).argmax(1),
                              observer(pixels[:, :, :, 28:]).argmax(1)), dim=1).tolist()
        mse = (pixels - batch.target.pixels).square().flatten(1).mean(1).tolist()
    return [utility(d, caption, target, m) for d, caption, target, m in
            zip(digits, captions, batch.target.labels.tolist(), mse)]


def audit(assets, run):
    assets, run = Path(assets), Path(run)
    torch.set_num_threads(1)
    seal = json.loads((run / "QUALIFICATION_SEAL.json").read_text())
    if seal["test_predictions_computed"] or seal["audit_observer_loaded"] or seal["protocol"] != P:
        raise ValueError("Invalid pre-test seal")
    if seal["metric_sha256"] != METRIC_DIGEST:
        raise ValueError("Scoring metric changed")
    for name, digest in seal["reference_checkpoint_file_sha256"].items():
        if checksum(assets / name) != digest:
            raise ValueError("Sealed original generator/observer file changed")
    for name, digest in seal["source_sha256"].items():
        if checksum(run / "executed-source" / name) != digest:
            raise ValueError("Executed qualification source changed")
    historical = historical_corpus(assets)
    corpus = fresh_corpus(assets, historical)
    expected_manifest = json.loads(json.dumps(corpus.manifest))
    if expected_manifest != json.loads((run / "FRESH_SOURCE_MANIFEST.json").read_text()):
        raise ValueError("Source identity reconstruction differs")
    excluded = {h for s in historical.splits.values() for h in s.pixel_hashes}
    if any(set(s.pixel_hashes) & excluded for s in corpus.splits.values()):
        raise ValueError("Historical source overlap")
    observer = reference_observer(assets, "audit")
    rows = [json.loads(line) for line in (run / "ROWS.jsonl").read_text().splitlines()]
    by_key = {(r["seed"], r["arm"], r["split"], r["condition"], r["pair"]): r for r in rows}
    if len(by_key) != len(rows):
        raise ValueError("Repeated evaluated row")
    maximum, verified = 0., 0
    for seed in P["seeds"]:
        for arm in P["arms"]:
            for split, count, conditions in (("test", P["test_pairs"], P["conditions"]),
                                              ("retention", P["retention_pairs"], ["clean"])):
                for k, condition in enumerate(conditions):
                    for start in range(0, count, 32):
                        n = min(32, count - start)
                        batch = make_batch(corpus, split, n, P["evaluation_seed"] + start + k * 10000,
                                           corruption=condition, offset=start)
                        current = [by_key[seed, arm, split, condition, start + j] for j in range(n)]
                        pixels, captions = [], []
                        for j, row in enumerate(current):
                            if tuple(row["source_ids"]) != batch.source_ids[j] or row["private_labels"] != batch.target.labels[j].tolist():
                                raise ValueError("Recorded target/source identity differs")
                            contents = {}
                            for kind, relative in row["artifacts"]["paths"].items():
                                path = (run / relative).resolve()
                                if not path.is_relative_to(run.resolve()) or path.is_symlink():
                                    raise ValueError("Unsafe artifact path")
                                raw = path.read_bytes()
                                if hashlib.sha256(raw).hexdigest() != row["artifacts"]["sha256"][kind]:
                                    raise ValueError("Delivered output changed")
                                contents[kind] = raw
                            pixels.append(decode_image(contents["image"]))
                            captions.append(contents["text"].decode("utf-8"))
                            verified += 1
                        for row, score in zip(current, score_batch(observer, torch.cat(pixels), captions, batch)):
                            maximum = max(maximum, abs(score - row["audit"]["utility"]))
    expected = len(P["seeds"]) * len(P["arms"]) * (P["test_pairs"] * len(P["conditions"]) + P["retention_pairs"])
    if verified != len(rows) or verified != expected or maximum > 1e-7:
        raise ValueError(f"Delivered score audit failed: {verified=} {maximum=}")
    oracle_receipt = json.loads((run / "ORACLE_RECEIPT.json").read_text())
    if (checksum(run / "ORACLE_OUTPUTS.zip") != oracle_receipt["archive_sha256"]
            or checksum(run / "ORACLE_ROWS.jsonl") != oracle_receipt["rows_sha256"]):
        raise ValueError("Oracle archive changed")
    oracle_rows = [json.loads(line) for line in (run / "ORACLE_ROWS.jsonl").read_text().splitlines()]
    expected_grid = {(seed, pair, condition) for seed in P["seeds"]
                     for pair in range(P["test_pairs"]) for condition in P["conditions"]}
    grid = [(r["seed"], r["pair"], r["condition"]) for r in oracle_rows]
    if len(grid) != len(expected_grid) or set(grid) != expected_grid:
        raise ValueError("Oracle source/condition grid incomplete or repeated")
    plans = tuple(product(ACTIONS, repeat=2))
    oracle_maximum, oracle_verified = 0., 0
    with zipfile.ZipFile(run / "ORACLE_OUTPUTS.zip") as packed:
        expected_members = [c["artifacts"][field] for r in oracle_rows for c in r["candidates"]
                            for field in ("image_member", "text_member")]
        if (len(expected_members) != len(set(expected_members))
                or len(packed.namelist()) != len(expected_members)
                or set(packed.namelist()) != set(expected_members)):
            raise ValueError("Oracle archive member census differs")
        target_cache = {}
        for row in oracle_rows:
            condition_index = P["conditions"].index(row["condition"])
            start = row["pair"] // 32 * 32
            n = min(32, P["test_pairs"] - start)
            key = row["condition"], start
            if key not in target_cache:
                target_cache[key] = make_batch(corpus, "test", n, P["evaluation_seed"] + start + condition_index * 10000,
                                               corruption=row["condition"], offset=start)
            batch = target_cache[key]
            j = row["pair"] - start
            if tuple(row["source_ids"]) != batch.source_ids[j]:
                raise ValueError("Oracle source identity differs")
            # Batch all sixteen oracle candidates for this one target.
            from dataclasses import replace
            target = replace(batch.target, pixels=batch.target.pixels[j:j + 1].repeat(16, 1, 1, 1),
                             labels=batch.target.labels[j:j + 1].repeat(16, 1),
                             text_tokens=batch.target.text_tokens[j:j + 1].repeat(16, 1))
            comparison = replace(batch, target=target)
            pixels, captions = [], []
            if len(row["candidates"]) != 16 or {c["plan_index"] for c in row["candidates"]} != set(range(16)):
                raise ValueError("Oracle candidate family incomplete")
            for candidate in row["candidates"]:
                if tuple(candidate["plan"]) != plans[candidate["plan_index"]]:
                    raise ValueError("Oracle semantic plan mapping differs")
                receipt = candidate["artifacts"]
                image_bytes, text_bytes = packed.read(receipt["image_member"]), packed.read(receipt["text_member"])
                if (hashlib.sha256(image_bytes).hexdigest() != receipt["image_sha256"]
                        or hashlib.sha256(text_bytes).hexdigest() != receipt["text_sha256"]):
                    raise ValueError("Oracle output byte mismatch")
                pixels.append(decode_image(image_bytes))
                captions.append(text_bytes.decode("utf-8"))
            values = score_batch(observer, torch.cat(pixels), captions, comparison)
            for candidate, value in zip(row["candidates"], values):
                oracle_maximum = max(oracle_maximum, abs(value - candidate["audit"]["utility"]))
                oracle_verified += 1
            if abs(max(values) - row["utility"]) > 1e-7:
                raise ValueError("Oracle maximum does not match candidates")
    if oracle_verified != oracle_receipt["candidate_bundles"] or oracle_maximum > 1e-7:
        raise ValueError("Oracle independent audit failed")
    result = json.loads((run / "RESULT.json").read_text())
    if result["rows_sha256"] != checksum(run / "ROWS.jsonl") or result["seal_sha256"] != checksum(run / "QUALIFICATION_SEAL.json"):
        raise ValueError("Result source binding differs")
    statistics = audit_statistics(rows, oracle_rows, result)
    receipt = {"schema": "hepta.ndu.joint-independent-audit.v1", "passed": True,
        "delivered_bundles_reopened": verified, "oracle_candidate_bundles_reopened": oracle_verified,
        "maximum_independent_delivered_utility_error": maximum,
        "maximum_independent_oracle_utility_error": oracle_maximum,
        "source_overlap_with_restored_original_corpus": 0,
        "rows_sha256": checksum(run / "ROWS.jsonl"), "result_sha256": checksum(run / "RESULT.json"),
        **statistics,
        "scope": "independent parser/arithmetic and same fixed audit recognizer; not human judgment or OS-isolated truth"}
    write_json(run / "INDEPENDENT_AUDIT.json", receipt)
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    audit(args.assets, args.run)
