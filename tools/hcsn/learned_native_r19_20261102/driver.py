"""Independent Rust vs unchanged Torch forward parity on fresh owner tapes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
import torch
from experiments.hcsn_learned_core_r19_20261102.models import ContentNetwork, replace
from experiments.hcsn_learned_core_r19_20261102.task import dataset, DURATIONS
from tools.hcsn.addressed_decision_r15_20261101.law import Law

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[2]
LEARNED = PROJECT / "experiments/hcsn_learned_core_r19_20261102"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_export(profile):
    original = LEARNED / "run_01" / f"weights_{profile['name']}.pt"
    assert digest(original) == profile["checkpoint_sha256"]
    state = torch.load(original, weights_only=True)
    lines = (HERE / profile["profile"]).read_text().splitlines()
    header = lines[0].split()
    assert header[:3] == ["LEARNED2", profile["checkpoint_sha256"], profile["control"]]
    assert np.float32(header[3]) == np.float32(profile["threshold"])
    fields = {row.split()[0]: np.array([float(x) for x in row.split()[1:]]) for row in lines[1:]}
    mapping = dict(Q="Q", PHASE="phase_prior", SYMBOL="symbol.weight", H0W="head.0.weight",
        H0B="head.0.bias", H2W="head.2.weight", H2B="head.2.bias", CHANNEL="channel", DURATIONS="durations")
    expected = {field: state[key].numpy() for field, key in mapping.items()}
    expected.update(GAMMA=state["log_scale"].exp().reshape(1).numpy(),
        ENCODED=state["symbol.weight"].T.contiguous().softmax(-1).numpy(),
        EMISSION=(.01 + .96 * state["symbol.weight"].softmax(-1)).numpy())
    for name, array in expected.items():
        assert np.array_equal(fields[name].astype(array.dtype), array.flatten()), name


def reference(name, data, threshold):
    model = ContentNetwork("analytic", Law())
    model.load_state_dict(torch.load(LEARNED / "run_01" / f"weights_{name}.pt", weights_only=True))
    arrays = {k: torch.from_numpy(v).float() if k == "fees" else torch.from_numpy(v).long()
              for k, v in data.items() if k not in ("owner_ids", "seeds", "aliases")}
    state, transitions = model.initial(arrays["initial"]), model.transitions()
    arange = torch.arange(len(state))
    rows = []
    for q in range(arrays["keys"].shape[1]):
        wk, wv = arrays["writes"][:, q].unbind(-1)
        state = replace(state, wk, model.event_update(state[arange, wk.clamp_min(0)], wv, 0), wk >= 0)
        state = model.advance(state, arrays["duration_indices"][:, q], transitions)
        key = arrays["keys"][:, q]
        before = model.logits(state[arange, key]); p = before.softmax(-1)
        future = torch.stack([model.event_update(state[arange, key], torch.full_like(key, y), 1)
                              for y in range(4)], 1)
        post = model.logits(future); pp = post.softmax(-1)
        value = ((p @ model.channel) * pp.max(-1).values).sum(-1)
        signed = value - arrays["fees"][:, q] - p.max(-1).values
        read = signed > 0 if "_value_" in name else arrays["fees"][:, q] <= threshold
        token = torch.where(read, arrays["tokens"][:, q], torch.zeros_like(key))
        logits = torch.where(read[:, None], post[arange, token], before)
        state = replace(state, key, future[arange, token], read)
        gap = signed.abs() if "_value_" in name else (arrays["fees"][:, q] - threshold).abs()
        heads = torch.cat((before[:, None], post), 1).topk(2, dim=-1).values
        min_head = (heads[..., 0] - heads[..., 1]).min(-1).values
        rows.append(torch.cat((read[:, None], logits.argmax(-1)[:, None], state.flatten(1),
            before, p, post.flatten(1), pp.flatten(1), value[:, None], gap[:, None],
            min_head[:, None]), -1).detach().numpy())
    return np.stack(rows, 1).reshape(-1, 205)


def run(output, development):
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    protocol = json.loads((HERE / "PROTOCOL.json").read_text())
    manifest = json.loads((HERE / "PROFILE_MANIFEST.json").read_text())
    if not development:
        freeze = json.loads((HERE / "SOURCE_FREEZE.json").read_text())
        for name, sha in freeze["files"].items():
            assert digest(HERE / name) == sha, name
        for name, sha in freeze["dependencies"].items():
            assert digest(PROJECT / name) == sha, name
        receipt = json.loads((HERE / "PUBLICATION.json").read_text())
        assert receipt["readback_verified"] is True
        assert receipt["source_freeze_sha256"] == digest(HERE / "SOURCE_FREEZE.json")
    output.mkdir(exist_ok=False)
    for profile in manifest["profiles"]:
        verify_export(profile)
    binary = output / "forward"
    compilation = subprocess.run(["rustc", "--edition=2024", "-O", str(HERE / "main.rs"), "-o", str(binary)],
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output / "compile.stdout").write_bytes(compilation.stdout)
    (output / "compile.stderr").write_bytes(compilation.stderr)
    compilation.check_returncode()
    results = []
    for domain, count, queries, namespace in (protocol["development"] if development else protocol["formal"]):
        data, owner_id = dataset(namespace, count, "ood" if domain == "ood" else "iid", queries)
        np.savez_compressed(output / f"data_{domain}.npz", **data)
        tape = []
        for w in range(count):
            tape.append("WORLD " + " ".join(map(str, data["initial"][w])))
            for q in range(queries):
                wk, wv = data["writes"][w, q]
                tape.append(f"QUERY {wk} {wv} {DURATIONS[data['duration_indices'][w,q]]:.17g} "
                    f"{data['keys'][w,q]} {np.float32(data['fees'][w,q]):.9g} {data['tokens'][w,q]}")
        tape_path = output / f"{domain}.tape"
        tape_path.write_text("\n".join(tape) + "\n")
        profiles = manifest["profiles"]
        for profile in profiles:
            assert digest(HERE / profile["profile"]) == profile["profile_sha256"]
            assert digest(LEARNED / "run_01" / f"weights_{profile['name']}.pt") == profile["checkpoint_sha256"]
            native_path = output / f"{domain}_{profile['name']}.tsv"
            process = subprocess.run([str(binary), str(HERE / profile["profile"]), str(tape_path), str(native_path)],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if process.returncode:
                raise RuntimeError(f"Native fail-closed: {profile['name']}: {process.stderr.decode()}")
            actual = np.loadtxt(native_path, ndmin=2)
            with torch.no_grad():
                expected = reference(profile["name"], data, profile["threshold"])
            np.savez_compressed(output / f"pair_{domain}_{profile['name']}.npz", native=actual, torch=expected)
            assert actual.shape == expected.shape
            errors = np.abs(actual - expected)
            state_error = float(errors[:, 2:162].max())
            logits_error = float(max(errors[:,162:166].max(),errors[:,170:186].max()))
            probs_error = float(max(errors[:,166:170].max(),errors[:,186:202].max()))
            exact = bool(np.array_equal(actual[:,:2], expected[:,:2]))
            assert state_error <= 5e-9 and logits_error <= 1e-5 and probs_error <= 2e-6 and exact
            results.append(dict(domain=domain, name=profile["name"], queries=len(actual), owner_id=owner_id,
                state_max_error=state_error, logits_max_error=logits_error, probs_max_error=probs_error,
                read_value_max_error=float(errors[:,202].max()), exact_actions_answers=exact,
                min_action_gap=float(actual[:,203].min()), min_head_gap=float(actual[:,204].min()),
                native_sha256=digest(native_path)))
    (output / "RESULTS.json").write_text(json.dumps(dict(status="PASS", development=development,
        results=results, binary_sha256=digest(binary), no_python_native_callbacks=True,
        no_new_training=True), indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--development", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.worker:
        run(args.output, args.development)
    else:
        started = time.perf_counter()
        command = [sys.executable,"-m",__package__+".driver","--worker","--output",str(args.output)]
        if args.development: command.append("--development")
        with args.output.with_suffix(".stdout").open("x") as stdout, args.output.with_suffix(".stderr").open("x") as stderr:
            child = subprocess.Popen(command,stdout=stdout,stderr=stderr)
            _, status, usage = os.wait4(child.pid,0)
            code = os.waitstatus_to_exitcode(status); child.returncode=code
        args.output.with_suffix(".process.json").write_text(json.dumps(dict(exit_code=code,
            cpu_seconds=usage.ru_utime+usage.ru_stime,wall_seconds=time.perf_counter()-started,
            max_rss_linux_kib=usage.ru_maxrss,scope="Whole worker including imports, compile, all Rust children and Torch/reference/output; export/developer/audit separate"),indent=2)+"\n")
        raise SystemExit(code)
