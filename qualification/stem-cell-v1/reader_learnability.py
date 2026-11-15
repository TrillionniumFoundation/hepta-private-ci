"""Train-only optimization gate, before opening public validation outcomes."""
import argparse
import json
from pathlib import Path

import torch

from group_encoder import FrozenTokenEncoder, file_digest
from group_reader import Reader
from group_reader_training import fit_reader
from multirc_data import load_jsonl, partition_cases, score_multirc
from reader_campaign_utils import gate_cases, predict_batch, select_paragraphs, write_json
from reader_features import SentenceBank


def run(args):
    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    torch.manual_seed(41)
    train = load_jsonl(args.source / "train.jsonl", "train")
    cases = select_paragraphs(partition_cases(train.cases, seed=41)["train"], 32)
    small = gate_cases(cases, questions=8)
    encoder = FrozenTokenEncoder(args.snapshot, max_tokens=256)
    bank = SentenceBank(encoder, batch_size=16)
    bank.restore_local(args.feature_cache)
    bank.register(small)
    batch = bank.batch(small)
    sources = {name: file_digest(Path(__file__).parent / name) for name in
               ("reader_learnability.py", "reader_features.py", "group_reader.py", "group_reader_training.py",
                "multirc_data.py", "reader_campaign_utils.py", "group_encoder.py")}
    protocol = dict(case_ids=[case.case_id for case in small],
        feature_sha256=[bank.public(case)["feature_sha256"] for case in small],
        steps=1000, hidden_dim=48, learning_rate=.01, max_depth=3, seed=41,
        min_f1_a=.95, min_exact_match=.8, official_validation_accessed=False,
        source_sha256=sources, dataset_train_sha256=train.sha256)
    write_json(args.output, "protocol.json", protocol)
    print(json.dumps(dict(stage="train_only_fit_start", candidates=len(small), questions=8)), flush=True)
    model, receipt = fit_reader(Reader(384, 48), batch, None, steps=1000, seed=41,
        max_depth=3, learning_rate=.01, wall_time_ns=600_000_000_000, diagnostic_interval=100)
    predictions, work = predict_batch(model, batch, 3)
    metrics = score_multirc(small, predictions)
    passed = receipt["completed_steps"] == 1000 and metrics["f1_a"] >= .95 and metrics["exact_match"] >= .8
    write_json(args.output, "training.json", receipt)
    write_json(args.output, "predictions.json", [dict(case_id=case.case_id, target=case.label, prediction=prediction)
               for case, prediction in zip(small, predictions)])
    report = dict(passed=passed, metrics=metrics, training_steps=receipt["completed_steps"],
        inference_work=work, scope="train_only_optimization_learnability_not_generalization",
        official_validation_accessed=False, source_sha256=sources)
    write_json(args.output, "report.json", report)
    print(json.dumps(dict(passed=passed, metrics=metrics)), flush=True)
    return 0 if passed else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "snapshot", "feature-cache", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    import torch._dynamo
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
