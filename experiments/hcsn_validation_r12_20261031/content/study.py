"""Frozen content matrix worker CLI; parent orchestration meters fresh processes."""

import argparse
import copy
import hashlib
import inspect
import json
import math
import platform
import resource
import sys
import time
import traceback
from pathlib import Path
from importlib.metadata import version

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from .data import TASKS, DOMAINS, SPLITS, dataset
from .models import FAMILIES, WIDTH, ContentEncoder, Model, core_configs, parameter_hash


ROOT = Path(__file__).resolve().parent
SEEDS = (12031, 12032, 12033)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def configure():
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)


def freeze(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    configurations = core_configs()
    from ncps.torch import CfCCell
    cfc_source = Path(inspect.getfile(CfCCell))
    jobs = []
    for task in TASKS:
        for seed in SEEDS:
            donor = f"{task}_s{seed}_donor"
            jobs.append(dict(id=donor, task=task, seed=seed, kind="donor"))
            for mode in ("frozen_frontend", "joint"):
                for family in FAMILIES:
                    jobs.append(dict(id=f"{task}_s{seed}_{mode}_{family}", task=task, seed=seed,
                                     kind="fit", family=family, mode=mode, donor=donor))
    protocol = dict(schema="hcsn-r12.content.v1", seeds=SEEDS, tasks=TASKS,
        runtime=dict(torch=torch.__version__, numpy=np.__version__, scipy=version("scipy"),
                     ncps=version("ncps"), cfc_cell_sha256=sha(cfc_source), cfc_source_file=cfc_source.name,
                     gpu_available=torch.cuda.is_available(), compute_device="cpu"),
        domains=DOMAINS, splits=SPLITS, width=WIDTH, core_configs=configurations,
        jobs=jobs, donor_updates=128, fit_updates=128, batch_size=32, validate_every=32,
        learning_rate=.003, donor_learning_rate=.003, gradient_clip=1.,
        selection="minimum validation cross entropy (task) or reconstruction MSE (donor); include step 0; first tie",
        matching="Identical common donor, task head initialization, data, batches and update count; three dual-gate cores have identical active parameters and initialization; other real architectures use nearest active hidden-width parameter match and report gaps.",
        frozen="Freeze only the common causal current/previous-frame content encoder; dynamics and new task readout remain trainable. Joint updates all. This is not a pretrained multimodal foundation encoder.",
        analytic="Exact #4529 finite fixed-refractory renewal gate, FP64 internal arithmetic; additional ordinary write head. Fixed mu=-.25,sigma=1,reset=.8,refractory=.15; no full He-Xiong or learned physical boundary claim.",
        causality="Current/previous raw frame and elapsed prefix clock only; no labels, posterior, computed address or future total length in model inputs.",
        test_rule="No test dataset access in donor/fit. Freeze all 96 selected checkpoints before test generation/evaluation. All attempts retained; no per-family tuning.",
        interpretation="Synthetic bounded CPU development. Three fits conditional on fixed datasets; raw rows and repeated profiles are not independent fit replications. Negative and step-zero results retained.",
        primary="Analytic minus ordinary_dual for each task and training mode; report all three paired seed differences, mean and all stress results. Advantage and same-quality cost conclusions require separate uncertainty/cost review; no pass inferred from positive mean.",
        costs="Parent fresh-process wait4 receipts include import/data/fit/selection/serialization; internal costs are nested. Serial profile after all fits; CPU is not energy. GPU and joules unavailable.")
    write(output / "PROTOCOL.json", protocol)
    files = sorted(ROOT.glob("*.py")) + sorted((ROOT / "upstream").glob("*.py")) + [ROOT / "UPSTREAM.json", ROOT / "upstream/BASELINES.md"]
    write(output / "SOURCE_FREEZE.json", dict(files={str(p.relative_to(ROOT)): sha(p) for p in files},
          protocol_sha256=sha(output / "PROTOCOL.json"), created_unix=time.time()))
    return dict(output=str(output), jobs=len(jobs), fit_jobs=sum(j["kind"] == "fit" for j in jobs))


def verified(protocol_path):
    protocol_path = Path(protocol_path).resolve()
    freeze_record = json.loads((protocol_path.parent / "SOURCE_FREEZE.json").read_text())
    if sha(protocol_path) != freeze_record["protocol_sha256"]:
        raise ValueError("Protocol hash mismatch")
    for path, expected in freeze_record["files"].items():
        if sha(ROOT / path) != expected:
            raise ValueError("Frozen source mismatch: " + path)
    return json.loads(protocol_path.read_text()), protocol_path.parent


def completed(root, job_id):
    attempts = sorted((root / "jobs" / job_id).glob("attempt*/summary.json"))
    if not attempts:
        raise FileNotFoundError("No completed job: " + job_id)
    path = attempts[-1]
    record = json.loads(path.read_text())
    if not record["completed"] or sha(path.parent / "selected.pt") != record["selected_checkpoint_sha256"]:
        raise ValueError("Completed checkpoint identity mismatch")
    return path.parent, record


def tensors(values, indices=None):
    index = slice(None) if indices is None else indices
    return tuple(torch.from_numpy(values[key][index]) for key in ("x", "dt", "y"))


def evaluate(model, values, batch_size=64):
    logits = []
    model.eval()
    with torch.no_grad():
        for begin in range(0, len(values["y"]), batch_size):
            x, dt, _ = tensors(values, np.arange(begin, min(begin+batch_size, len(values["y"]))))
            logits.append(model(x, dt).numpy())
    logits = np.concatenate(logits)
    logit = torch.from_numpy(logits)
    metrics = dict(accuracy=float((logits.argmax(-1) == values["y"]).mean()),
                   ce=float(F.cross_entropy(logit, torch.from_numpy(values["y"]))),
                   brier=float(((logit.softmax(-1)-F.one_hot(torch.from_numpy(values["y"]), logits.shape[-1]))**2).sum(-1).mean()),
                   n=len(logits), input_sha256=values["sha256"])
    return metrics, logits


def worker(protocol_path, job_id, attempt):
    protocol, root = verified(protocol_path)
    job = next(j for j in protocol["jobs"] if j["id"] == job_id)
    output = root / "jobs" / job_id / f"attempt{attempt:03d}"
    output.mkdir(parents=True, exist_ok=False)
    begin_cpu, begin_wall = time.process_time(), time.perf_counter()
    write(output / "job.json", job)
    try:
        torch.manual_seed(job["seed"])
        rng = np.random.default_rng(job["seed"] + 931)
        train, val = dataset(job["task"], "train"), dataset(job["task"], "val")
        write(output / "data_identity.json", {s: dict(sha256=v["sha256"], shape=list(v["x"].shape)) for s, v in (("train", train), ("val", val))})
        donor_job = job["kind"] == "donor"
        donor_hash = None
        if donor_job:
            encoder = ContentEncoder(TASKS[job["task"]][0])
            model = nn.ModuleDict(dict(encoder=encoder, decoder=nn.Linear(WIDTH, 2*encoder.input_dim)))
            updates = protocol["donor_updates"]
        else:
            model = Model(job["task"], job["family"], job["seed"], protocol["core_configs"][job["family"]])
            donor_path, donor_summary = completed(root, job["donor"])
            donor_hash = donor_summary["selected_checkpoint_sha256"]
            donor = torch.load(donor_path / "selected.pt", map_location="cpu", weights_only=False)
            model.encoder.load_state_dict(donor["encoder_state"], strict=True)
            if job["mode"] == "frozen_frontend":
                model.encoder.requires_grad_(False)
            updates = protocol["fit_updates"]
        initial = {key: value.detach().clone() for key, value in model.state_dict().items()}
        initial_hash = parameter_hash(model)
        encoder_initial_hash = parameter_hash(model["encoder"] if donor_job else model.encoder)
        torch.save(dict(state=initial, job=job), output / "initial.pt")
        optimizer = torch.optim.Adam((p for p in model.parameters() if p.requires_grad), lr=protocol["learning_rate"])

        def loss_on(values, indices=None):
            x, dt, y = tensors(values, indices)
            if donor_job:
                target = model["encoder"].raw_features(x, dt)[..., :2*TASKS[job["task"]][0]]
                return F.mse_loss(model["decoder"](model["encoder"](x, dt)), target)
            return F.cross_entropy(model(x, dt), y)

        def val_loss():
            model.eval()
            with torch.no_grad():
                return float(loss_on(val))

        def snapshot(step):
            encoder = model["encoder"] if donor_job else model.encoder
            return dict(step=step, job=job, model_state=copy.deepcopy(model.state_dict()),
                encoder_state=copy.deepcopy(encoder.state_dict()), optimizer=copy.deepcopy(optimizer.state_dict()),
                torch_rng=torch.get_rng_state(), numpy_rng=copy.deepcopy(rng.bit_generator.state),
                config=None if donor_job else model.config, donor_sha256=donor_hash,
                protocol_sha256=sha(protocol_path), source_freeze_sha256=sha(root/"SOURCE_FREEZE.json"))

        best_loss, best = val_loss(), snapshot(0)
        validations = [dict(step=0, loss=best_loss)]
        grad_nonzero = {"encoder": 0, "core": 0, "readout": 0, "decoder": 0}
        fit_cpu = time.process_time()
        with (output / "trace.jsonl").open("x") as trace:
            for step in range(1, updates+1):
                model.train()
                indices = rng.integers(len(train["y"]), size=protocol["batch_size"])
                optimizer.zero_grad(set_to_none=True)
                loss = loss_on(train, indices)
                loss.backward()
                gradients = {key: 0. for key in grad_nonzero}
                for name, param in model.named_parameters():
                    if param.grad is not None:
                        if not bool(torch.isfinite(param.grad).all()):
                            raise FloatingPointError("Nonfinite gradient: " + name)
                        gradients[name.split(".")[0]] += float(param.grad.square().sum())
                gradients = {key: math.sqrt(value) for key, value in gradients.items()}
                for key, value in gradients.items():
                    grad_nonzero[key] += value > 0
                norm = float(torch.nn.utils.clip_grad_norm_(model.parameters(), protocol["gradient_clip"]))
                if not math.isfinite(float(loss)) or not math.isfinite(norm):
                    raise FloatingPointError("Nonfinite training")
                optimizer.step()
                trace.write(json.dumps(dict(step=step, loss=float(loss.detach()), gradient_norm=norm,
                    group_gradients=gradients, batch_indices=indices.tolist(), cpu=time.process_time()-fit_cpu)) + "\n")
                trace.flush()
                if step % protocol["validate_every"] == 0 or step == updates:
                    value = val_loss()
                    validations.append(dict(step=step, loss=value))
                    if value < best_loss:
                        best_loss, best = value, snapshot(step)
        fitting_cpu = time.process_time() - fit_cpu
        final = snapshot(updates)
        torch.save(final, output / "final.pt")
        torch.save(best, output / "selected.pt")
        model.load_state_dict(best["model_state"])
        encoder_final_hash = parameter_hash(model["encoder"] if donor_job else model.encoder)
        if not donor_job and job["mode"] == "frozen_frontend" and encoder_final_hash != encoder_initial_hash:
            raise AssertionError("Frozen encoder changed")
        val_metrics = dict(mse=best_loss) if donor_job else evaluate(model, val)[0]
        if not donor_job:
            _, raw = evaluate(model, val)
            np.savez_compressed(output / "validation_predictions.npz", logits=raw, labels=val["y"], ids=val["ids"], groups=val["group"])
        changed = {key: float((best["model_state"][key]-value).abs().max()) for key, value in initial.items()}
        summary = dict(completed=True, job=job, selected_step=best["step"], selected_validation=val_metrics,
            validations=validations, selected_checkpoint_sha256=sha(output/"selected.pt"), final_checkpoint_sha256=sha(output/"final.pt"),
            initial_sha256=sha(output/"initial.pt"), initial_parameter_hash=initial_hash,
            encoder_initial_hash=encoder_initial_hash, encoder_selected_hash=encoder_final_hash, donor_sha256=donor_hash,
            parameters=sum(p.numel() for p in model.parameters()), trainable_parameters=sum(p.numel() for p in model.parameters() if p.requires_grad),
            gradient_nonzero_steps=grad_nonzero, selected_parameter_max_changes=changed,
            body_cpu_seconds=time.process_time()-begin_cpu, body_wall_seconds=time.perf_counter()-begin_wall,
            training_including_validation_cpu_seconds=fitting_cpu, max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            energy_joules=None, energy_status="unavailable", gpu_used=False, heldout_opened=False,
            runtime=dict(python=platform.python_version(), torch=torch.__version__, numpy=np.__version__, threads=1),
            complete_process_receipt="parent wait4 receipt includes imports and serialization; nested body/train times must not be added")
        write(output / "summary.json", summary)
        return dict(job=job_id, selected_step=best["step"], validation=val_metrics, output=str(output))
    except Exception as error:
        write(output / "FAILED.json", dict(error=repr(error), traceback=traceback.format_exc(),
            body_cpu_seconds=time.process_time()-begin_cpu, body_wall_seconds=time.perf_counter()-begin_wall))
        raise


def candidates(protocol_path):
    protocol, root = verified(protocol_path)
    entries = {}
    for job in protocol["jobs"]:
        directory, summary = completed(root, job["id"])
        entries[job["id"]] = dict(path=str(directory.relative_to(root)),
            sha256=summary["selected_checkpoint_sha256"], step=summary["selected_step"])
    record = dict(protocol_sha256=sha(protocol_path), source_freeze_sha256=sha(root/"SOURCE_FREEZE.json"),
                  created_unix=time.time(), candidates=entries, heldout_opened=False)
    write(root / "CANDIDATE_FREEZE.json", record)
    return dict(candidates=len(entries), freeze_sha256=sha(root/"CANDIDATE_FREEZE.json"))


def load_selected(protocol_path, job_id):
    protocol, root = verified(protocol_path)
    frozen = json.loads((root/"CANDIDATE_FREEZE.json").read_text())
    entry = frozen["candidates"][job_id]
    path = root/entry["path"]/"selected.pt"
    if sha(path) != entry["sha256"]:
        raise ValueError("Selected checkpoint changed after freeze")
    payload = torch.load(path, map_location="cpu", weights_only=False)
    model = Model(**payload["config"])
    model.load_state_dict(payload["model_state"])
    return model, protocol, root, entry


def heldout(protocol_path, job_id):
    model, protocol, root, entry = load_selected(protocol_path, job_id)
    output = root/"heldout"/job_id
    output.mkdir(parents=True, exist_ok=False)
    results = {}
    task = model.config["task"]
    for domain in DOMAINS[task]:
        values = dataset(task, "test", domain)
        metrics, raw = evaluate(model, values)
        np.savez_compressed(output/(domain+".npz"), logits=raw, labels=values["y"], ids=values["ids"], groups=values["group"], input_sha256=values["sha256"])
        results[domain] = metrics
    write(output/"summary.json", dict(job=job_id, checkpoint=entry, results=results,
        candidate_freeze_sha256=sha(root/"CANDIDATE_FREEZE.json")))
    return dict(job=job_id, results=results)


def profile(protocol_path, job_id):
    model, protocol, root, entry = load_selected(protocol_path, job_id)
    values = dataset(model.config["task"], "val")
    model.eval()
    measurements = {}
    with torch.no_grad():
        for batch in (1, 32):
            x, dt, _ = tensors(values, np.arange(batch))
            for _ in range(3):
                model(x, dt)
            rows = []
            for _ in range(12):
                cpu, wall = time.process_time(), time.perf_counter()
                logits = model(x, dt).numpy().copy()
                rows.append(dict(cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall))
            measurements[str(batch)] = rows
    path = root/"profiles"
    path.mkdir(exist_ok=True)
    write(path/(job_id+".json"), dict(job=job_id, checkpoint=entry, measurements=measurements,
        warmups=3, threads=1, input_sha256=values["sha256"], energy_joules=None,
        scope="cached raw tensor input + causal frontend + complete core + readout + output CPU copy; parent meters whole worker; no raw-media/network/GPU claim"))
    return dict(job=job_id, measurements=measurements)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("freeze", "worker", "candidates", "evaluate", "profile"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--job")
    parser.add_argument("--attempt", type=int, default=1)
    args = parser.parse_args()
    configure()
    if args.command == "freeze":
        result = freeze(args.output)
    elif args.command == "worker":
        result = worker(args.protocol, args.job, args.attempt)
    elif args.command == "candidates":
        result = candidates(args.protocol)
    elif args.command == "evaluate":
        result = heldout(args.protocol, args.job)
    else:
        result = profile(args.protocol, args.job)
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
