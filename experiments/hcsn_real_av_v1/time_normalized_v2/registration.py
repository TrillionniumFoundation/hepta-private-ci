"""Train-only validation and sealing of the replacement time-normalized profile."""

import argparse
from datetime import datetime, timezone
import gc
import json
from pathlib import Path
import resource
import time
import traceback

from ..data import digest, write_json


HERE = Path(__file__).resolve().parent
BASE, ROOT = HERE.parent, HERE.parents[2]


def sources():
    original = json.loads((BASE / "FREEZE.json").read_text())
    result = {row["path"]: row["sha256"] for row in original["files"]}
    for name, expected in result.items():
        assert digest(ROOT / name) == expected, name
    paths = list(HERE.glob("*.py")) + [HERE / name for name in
        ("PROTOCOL.json", "ADDENDUM.json", "README.md")]
    paths += [BASE / "FREEZE.json", BASE / "SUPERSEDED.json"]
    result.update({str(path.relative_to(ROOT)): digest(path) for path in paths})
    protocol, old = (json.loads(path.read_text()) for path in (HERE / "PROTOCOL.json", BASE / "PROTOCOL.json"))
    assert protocol["base_freeze_sha256"] == digest(BASE / "FREEZE.json")
    assert all(protocol[key] == old[key] for key in protocol["unchanged_fields"])
    assert all(protocol["features"][key] == old["features"][key] for key in
        ("observations_per_clip", "audio", "video", "sampling", "normalization"))
    return result


def preflight(output):
    import torch
    from .study import PairEncoder, load_split, objective

    if output.exists():
        raise FileExistsError("Preserve all train-only preflight attempts")
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    started = time.process_time()
    protocol = json.loads((HERE / "PROTOCOL.json").read_text())
    dataset = json.loads((BASE / "data/DATASET.json").read_text())
    original = json.loads((BASE / "PREFLIGHT.json").read_text())
    row = dataset["splits"]["train"]
    report = dict(passed=False, train_only=True, source_sha256=sources(), models=[],
        train_sha256=row["sha256"], torch=torch.__version__, indices=original["indices"],
        intervention="Every token duration replaced with1 before model access",
        validation_or_test_tensors_opened=False)
    try:
        data = load_split(BASE / "data" / row["path"], row["sha256"])
        assert bool((data["dt"] == 1).all()) and data["dt"].shape[1] == 32
        ids = torch.tensor(report["indices"])
        for name in protocol["models"]:
            model = PairEncoder(name, 9401)
            optimizer = torch.optim.Adam(model.parameters(), lr=protocol["learning_rate"])
            updates = []
            for _ in range(2):
                before = {id(p): p.detach().clone() for p in model.parameters()}
                optimizer.zero_grad(set_to_none=True)
                loss = objective(model(data["audio"][ids], data["video"][ids], data["dt"][ids]),
                                 data["y"][ids], protocol["temperature"])
                assert bool(torch.isfinite(loss))
                loss.backward()
                assert all(p.grad is not None and bool(torch.isfinite(p.grad).all()) for p in model.parameters())
                gradients = {key: sum(float(p.grad.square().sum()) for _, p in values)**.5
                             for key, values in model.groups().items()}
                torch.nn.utils.clip_grad_norm_(model.parameters(), 2.)
                optimizer.step()
                changes = {key: sum(float((p.detach()-before[id(p)]).square().sum()) for _, p in values)**.5
                           for key, values in model.groups().items()}
                assert all(value > 0 for value in gradients.values())
                assert all(value > 0 for value in changes.values())
                updates.append(dict(loss=float(loss.detach()), gradients=gradients, changes=changes))
            report["models"].append(dict(model=name, updates=updates,
                total_parameters=sum(p.numel() for p in model.parameters()),
                probability_checks=model.probability_checks))
            print(json.dumps(dict(preflight=name, passed=True, dt=1)), flush=True)
            del model, optimizer, before, loss
            gc.collect()
        assert report["source_sha256"] == sources()
        report["passed"] = True
    except Exception as error:
        report.update(error=f"{type(error).__name__}: {error}", traceback=traceback.format_exc())
        raise
    finally:
        report.update(cpu_seconds=time.process_time()-started,
                      peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)
        write_json(output, report)


def seal():
    closure = sources()
    report = json.loads((HERE / "PREFLIGHT.json").read_text())
    assert report["passed"] and report["source_sha256"] == closure
    closure[str((HERE / "PREFLIGHT.json").relative_to(ROOT))] = digest(HERE / "PREFLIGHT.json")
    write_json(HERE / "FREEZE.json", dict(schema="hcsn-real-av-time-normalized-freeze-v2",
        sealed_utc=datetime.now(timezone.utc).isoformat(), no_heldout_model_evaluation=True,
        original_freeze_sha256=digest(BASE / "FREEZE.json"),
        formal_profile="time_normalized_v2", original_profile_status="Superseded before any formal fit or heldout evaluation",
        publication_gate="Publish before registered training and diagnostic evaluation",
        files=[dict(path=path, sha256=sha, bytes=(ROOT / path).stat().st_size)
               for path, sha in sorted(closure.items())]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "seal", "verify"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "preflight":
        preflight(args.output or HERE / "PREFLIGHT.json")
    elif args.command == "seal":
        seal()
    else:
        frozen = json.loads((HERE / "FREEZE.json").read_text())
        for row in frozen["files"]:
            assert digest(ROOT / row["path"]) == row["sha256"], row["path"]
        print(json.dumps(dict(passed=True, files=len(frozen["files"]),
                              freeze_sha256=digest(HERE / "FREEZE.json"))))


if __name__ == "__main__":
    main()
