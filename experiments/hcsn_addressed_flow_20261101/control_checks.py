"""Independent causal-prefix and target-visibility checks for paid READ/STOP."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from unittest.mock import patch

import numpy as np
import torch

from . import addressed_models, control_study, data, study


def run(out):
    out.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    paths = [Path(__file__), Path(data.__file__), Path(control_study.__file__),
             Path(study.__file__), Path(addressed_models.__file__)]
    paths += [study.ROOT / path for path in study.source_hashes()]
    paths = list(dict.fromkeys(paths))
    source_hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    (out / "sources").mkdir()
    for path in paths:
        shutil.copyfile(path, out / "sources" / path.name)
    rows = []

    def check(name, passed, **details):
        row = dict(name=name, passed=bool(passed), **details)
        rows.append(row)
        with (out / "cases.jsonl").open("a") as stream:
            stream.write(json.dumps(row, allow_nan=False) + "\n")

    def equal(name, a, b):
        check(name, np.array_equal(a, b))

    # Inspect only namespace boundaries for confirmation: do not materialize
    # any confirmation episode before root's independent freeze.
    intervals = sorted((offset, offset + 99999999, name)
                       for name, offset in data.STREAMS.items())
    check("streams/nonoverlapping_registered_seed_ranges",
          all(intervals[i][1] < intervals[i + 1][0] for i in range(len(intervals) - 1)),
          intervals=intervals)
    training = data.batch("mqar", 16, 861119, "train")
    development = data.batch("mqar", 16, 861119, "dev")
    check("streams/train_and_dev_actual_payloads_differ",
          not np.array_equal(training["x"], development["x"]),
          scope="Namespace plus development witness; no confirmation data opened")

    for task in data.CONTENT_TASKS:
        seed, count = 861119, 16
        base = data.batch(task, count, seed, "dev")
        stop, read, prices, removed = data.read_opportunity(task, count, seed, "dev")
        query = base["x"].shape[1] - 4
        for field in ("x", "dt", "observed"):
            equal(task + "/shared_decision_prefix/" + field,
                  stop[field][:, :query + 1], read[field][:, :query + 1])
        equal(task + "/deleted_token_zero", stop["x"][np.arange(count), removed],
              np.zeros((count, 24), np.float32))
        equal(task + "/deleted_token_unobserved", stop["observed"][np.arange(count), removed],
              np.zeros(count, bool))
        equal(task + "/paid_raw_event_identity", read["x"][:, query + 1],
              base["x"][np.arange(count), removed])
        equal(task + "/raw_read_has_no_label", read["y"][:, query + 1], np.full(count, -100))
        equal(task + "/initial_query_not_scored_on_read", read["y"][:, query], np.full(count, -100))
        equal(task + "/initial_query_scored_on_stop", stop["y"][:, query], base["y"][:, query])
        equal(task + "/same_requery_payload", read["x"][:, query + 2], stop["x"][:, query])
        equal(task + "/same_requery_target", read["y"][:, query + 2], stop["y"][:, query])
        equal(task + "/only_four_read_queries_scored", (read["y"] >= 0).sum(-1), np.full(count, 4))
        equal(task + "/same_four_targets", read["y"][read["y"] >= 0], stop["y"][stop["y"] >= 0])
        equal(task + "/query_inputs_have_no_value", read["x"][read["y"] >= 0, 4:12],
              np.zeros((4 * count, 8), np.float32))
        check(task + "/read_spends_point_one_time",
              np.allclose(read["dt"].sum(-1) - stop["dt"].sum(-1), .1, atol=3e-6, rtol=0),
              maximum_time_error=float(np.max(np.abs(read["dt"].sum(-1) - stop["dt"].sum(-1) - .1))))
        equal(task + "/requery_zero_time", read["dt"][:, query + 2], np.zeros(count))
        final_flags = []
        for row, removed_index in enumerate(removed):
            event = base["x"][row, removed_index]
            address = int(event[:4].argmax())
            later_same_key_write = ((base["x"][row, removed_index + 1:query, 12] > 0)
                                    & (base["x"][row, removed_index + 1:query, address] > 0))
            final_flags.append(event[12] == 1 and removed_index < query and not later_same_key_write.any())
        check(task + "/missing_event_is_final_past_write", all(final_flags))
        check(task + "/price_in_declared_grid", np.isin(prices, [.02, .08, .16, .24, .32]).all())

        # The environment chooses an old event using observed event fields,
        # not its evaluation label. Modifying labels must not change inputs,
        # prices, or selection of the missing event.
        label_changed = copy.deepcopy(base)
        label_changed["y"][label_changed["y"] >= 0] = (
            label_changed["y"][label_changed["y"] >= 0] + 3) % 8
        with patch.object(data, "batch", return_value=label_changed):
            stop_other, read_other, prices_other, removed_other = data.read_opportunity(task, count, seed, "dev")
        for field in ("x", "dt", "observed"):
            equal(task + "/environment_label_independence/stop/" + field, stop[field], stop_other[field])
            equal(task + "/environment_label_independence/read/" + field, read[field], read_other[field])
        equal(task + "/price_label_independence", prices, prices_other)
        equal(task + "/removed_event_label_independence", removed, removed_other)

        for core in ("flow", "diagonal"):
            model = addressed_models.AddressedModel(core)
            checkpoint = Path(__file__).parent / "dev/addressing_train001" / f"{task}_{core}.pt"
            model.load_state_dict(torch.load(checkpoint, weights_only=True))
            model.eval()
            stop_logits, read_logits = study.predict(model, stop), study.predict(model, read)
            prefix_error = float(np.max(np.abs(stop_logits[:, :query + 1] - read_logits[:, :query + 1])))
            check(f"{task}/{core}/model_shared_decision_prefix", prefix_error <= 1e-5,
                  maximum_absolute_error=prefix_error)
            altered = copy.deepcopy(stop)
            altered["x"][:, query + 1:] *= -7
            altered["dt"][:, query + 1:] = altered["dt"][:, query + 1:] * 7 + .2
            altered["observed"][:, query + 1:] = ~altered["observed"][:, query + 1:]
            changed_logits = study.predict(model, altered)
            feature_base = control_study.features(stop_logits, stop)
            feature_future = control_study.features(changed_logits, altered)
            equal(f"{task}/{core}/features_ignore_future_world", feature_base, feature_future)
            changed_future_logits = stop_logits.copy()
            changed_future_logits[:, query + 1:] += np.arange(8) * 999
            equal(f"{task}/{core}/features_ignore_future_logits", feature_base,
                  control_study.features(changed_future_logits, stop))
            online = {key: stop[key] for key in ("x", "dt", "observed")}
            try:
                online_features = control_study.features(stop_logits, online)
                no_label_access = np.array_equal(online_features, feature_base)
                error_message = None
            except Exception as exc:
                no_label_access = False
                error_message = f"{type(exc).__name__}: {exc}"
            check(f"{task}/{core}/features_need_no_labels_or_metadata", no_label_access,
                  error=error_message)

        # Independent scoring fixture: the delayed first answer replaces the
        # unscored initial query; it does not become a fifth scored answer.
        perfect = np.zeros((*read["y"].shape, 8), np.float32)
        valid = np.where(read["y"] >= 0)
        perfect[valid[0], valid[1], read["y"][valid]] = 10
        quality, all4 = control_study.query_quality(perfect, read)
        equal(task + "/scoring_four_queries", quality, np.ones(count))
        equal(task + "/scoring_all4", all4, np.ones(count, bool))
        perfect[:, query + 2] = 0
        wrong = (read["y"][:, query + 2] + 1) % 8
        perfect[np.arange(count), query + 2, wrong] = 10
        quality, all4 = control_study.query_quality(perfect, read)
        equal(task + "/one_error_costs_one_quarter", quality, np.full(count, .75))
        equal(task + "/one_error_breaks_all4", all4, np.zeros(count, bool))

    # Smoke the actual study directory convention with a minimal real
    # checkpoint; no scientific model or campaign files are altered.
    with tempfile.TemporaryDirectory(dir=out) as temporary:
        run_path = Path(temporary)
        checkpoint = run_path / "fits/mqar/addressed_flow/seed17/checkpoint.pt"
        checkpoint.parent.mkdir(parents=True)
        fixture_model = torch.nn.Linear(1, 1)
        torch.save(fixture_model.state_dict(), checkpoint)
        checkpoint_sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
        manifest = dict(fits=[dict(task="mqar", arm="addressed_flow", seed=17,
                                  status="completed",
                                  checkpoint=str(checkpoint.relative_to(run_path)),
                                  checkpoint_sha256=checkpoint_sha)])
        manifest_path = run_path / "ALL_CHECKPOINTS.json"
        manifest_path.write_text(json.dumps(manifest))
        try:
            with patch.object(study, "new_model", return_value=torch.nn.Linear(1, 1)):
                loaded, checksum = control_study.load_model(run_path, "mqar", "addressed_flow", 17)
            path_ok = checksum == hashlib.sha256(checkpoint.read_bytes()).hexdigest()
            path_error = None
        except Exception as exc:
            path_ok, path_error = False, f"{type(exc).__name__}: {exc}"
        check("checkpoint_loader/actual_study_directory", path_ok, error=path_error)
        manifest["fits"][0]["checkpoint_sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest))
        try:
            control_study.load_model(run_path, "mqar", "addressed_flow", 17)
            rejects_tamper = False
        except ValueError:
            rejects_tamper = True
        check("checkpoint_loader/rejects_changed_checkpoint", rejects_tamper)

        freeze = dict(source_sha256=hashlib.sha256(Path(control_study.__file__).read_bytes()).hexdigest(),
                      data_sha256=hashlib.sha256(Path(data.__file__).read_bytes()).hexdigest(),
                      source_hashes={}, candidate_freeze_sha256="0" * 64)
        freeze_path = run_path / "POLICY_FREEZE.json"
        freeze_path.write_text(json.dumps(freeze))
        freeze_sha = hashlib.sha256(freeze_path.read_bytes()).hexdigest()
        for reason, supplied_sha in (("policy_identity", "0" * 64), ("source_identity", freeze_sha)):
            try:
                control_study.evaluate(run_path, run_path, supplied_sha)
                rejected = False
            except ValueError:
                rejected = True
            check("control_freeze/rejects_changed_" + reason, rejected)
        freeze["source_hashes"] = study.source_hashes()
        freeze_path.write_text(json.dumps(freeze))
        try:
            control_study.evaluate(run_path, run_path, hashlib.sha256(freeze_path.read_bytes()).hexdigest())
            rejected = False
        except ValueError:
            rejected = True
        check("control_freeze/rejects_changed_candidate_identity", rejected)

    unchanged = all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == sha for p, sha in source_hashes.items())
    check("audit/source_identity_unchanged", unchanged)
    summary = dict(checks=len(rows), passed=sum(r["passed"] for r in rows),
                   failed=sum(not r["passed"] for r in rows), source_sha256=source_hashes,
                   scope="Development-only causal execution/visibility checks; no confirmation data",
                   utility_scope="Four-query accuracy minus quoted READ price; no conversion of CPU seconds to utility")
    (out / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
    (out / "FAILURES.json").write_text(json.dumps([r for r in rows if not r["passed"]], indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return int(summary["failed"] > 0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    raise SystemExit(run(parser.parse_args().out))
