"""Independently reproduce the archived greedy generations with NumPy and the frozen bytes.

Run with OPENBLAS_NUM_THREADS=1, after extracting models.zip and cold.zip in separate
directories. This reader implements the specific two-block GPT-2 and unmerged byte
tokenizer in this archive. It uses no teacher and makes no network calls.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

import numpy as np
from episode import outputs, passes, stage_prompt


def read(path):
    return json.loads(path.read_bytes())


def tensors(path):
    data = path.read_bytes()
    size = struct.unpack_from("<Q", data)[0]
    header = json.loads(data[8:8 + size])
    body = memoryview(data)[8 + size:]
    result = {}
    for key, meta in header.items():
        if key == "__metadata__":
            continue
        if meta["dtype"] != "F32":
            raise ValueError("Unsupported tensor dtype")
        a, b = meta["data_offsets"]
        result[key] = np.frombuffer(body[a:b], dtype="<f4").reshape(meta["shape"])
    return result


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Model:
    def __init__(self, path):
        self.w = tensors(path / "model.safetensors")
        self.config = read(path / "config.json")
        assert (self.config["n_layer"], self.config["n_head"], self.config["n_embd"]) == (2, 4, 32)
        tokenizer = read(path / "tokenizer.json")
        assert tokenizer["model"]["merges"] == [] and tokenizer["normalizer"] is None
        visible = list(range(33, 127)) + list(range(161, 173)) + list(range(174, 256))
        extra = [b for b in range(256) if b not in visible]
        alphabet = dict(zip(visible, map(chr, visible)))
        alphabet.update({b: chr(256 + i) for i, b in enumerate(extra)})
        self.byte_id = {b: tokenizer["model"]["vocab"][c] for b, c in alphabet.items()}
        self.id_byte = {v: k for k, v in self.byte_id.items()}
        self.cache = {}

    def norm(self, x, key):
        delta = x - x.mean(axis=-1, keepdims=True)
        z = delta / np.sqrt((delta * delta).mean(axis=-1, keepdims=True)
                            + self.config["layer_norm_epsilon"])
        return z * self.w[key + ".weight"] + self.w[key + ".bias"]

    def linear(self, x, key):
        return x @ self.w[key + ".weight"] + self.w[key + ".bias"]

    def next_id(self, ids):
        key = "transformer."
        x = self.w[key + "wte.weight"][ids] + self.w[key + "wpe.weight"][:len(ids)]
        n = len(ids)
        causal = np.triu(np.ones((n, n), dtype=bool), k=1)
        for layer in range(2):
            pref = f"{key}h.{layer}."
            qkv = self.linear(self.norm(x, pref + "ln_1"), pref + "attn.c_attn")
            q, k, v = [a.reshape(n, 4, 8).transpose(1, 0, 2) for a in np.split(qkv, 3, -1)]
            score = (q @ k.swapaxes(-1, -2)) / np.sqrt(np.float32(8))
            score[:, causal] = -np.inf
            prob = np.exp(score - score.max(axis=-1, keepdims=True))
            prob /= prob.sum(axis=-1, keepdims=True)
            attended = (prob @ v).transpose(1, 0, 2).reshape(n, 32)
            x = x + self.linear(attended, pref + "attn.c_proj")
            ff = self.linear(self.norm(x, pref + "ln_2"), pref + "mlp.c_fc")
            ff = .5 * ff * (1 + np.tanh(np.sqrt(np.float32(2 / np.pi)) *
                                        (ff + np.float32(.044715) * ff ** 3)))
            x = x + self.linear(ff, pref + "mlp.c_proj")
        hidden = self.norm(x[-1], key + "ln_f")
        head = self.w.get("lm_head.weight", self.w[key + "wte.weight"])
        return int(np.argmax(hidden @ head.T))

    def predict(self, value):
        if value in self.cache:
            return self.cache[value]
        rendered = "### User\n" + value + "\n### Assistant\n"
        ids = [self.byte_id[b] for b in rendered.encode()]
        n = len(ids)
        assert n <= 170
        produced = []
        for _ in range(80):
            token = self.next_id(ids)
            produced.append(token)
            if token == self.config["eos_token_id"]:
                break
            ids.append(token)
        answer = bytes(self.id_byte[i] for i in produced if i in self.id_byte).decode(
            errors="replace")
        result = dict(answer=answer, output_tokens=len(produced), input_tokens=n,
                      input_sha256=sha(value), rendered_input_sha256=sha(rendered))
        self.cache[value] = result
        return result


def prompt(query, state, memory, arm):
    if arm != "retrieval":
        return query
    matches = [r for r in memory if r["state"] == state]
    assert len(matches) == 1
    prior = matches[0]["target"]
    while prior:
        joined = query + "\nPrior example: " + prior
        if len(("### User\n" + joined + "\n### Assistant\n").encode()) <= 170:
            return joined
        prior = prior[:-1]
    return query


def main(model_root, cold_root):
    panel = read(cold_root / "panel.json")
    memory = read(model_root / "memory.json")
    models, checks, deltas = {}, {}, {}
    base = tensors(model_root / "parent-checkpoint/model.safetensors")
    for arm in panel["arm_order"]:
        manifest = read(model_root / (arm + ".json"))
        directory = manifest["runtime"]["base_directory"]
        if directory not in models:
            models[directory] = Model(model_root / directory)
        model = models[directory]
        deltas[arm] = dict(unchanged=sum(np.array_equal(base[k], model.w[k]) for k in base),
                           changed=[k for k in base if not np.array_equal(base[k], model.w[k])],
                           added=sorted(model.w.keys() - base.keys()))
        cold = read(cold_root / (arm + "-cold.json"))
        checked = set()

        def check(i, value, state):
            assert i not in checked
            prediction = model.predict(prompt(value, state, memory, arm))
            assert all(cold["calls"][i][k] == v for k, v in prediction.items()), (arm, i, prediction)
            checked.add(i)

        for case, row in zip(panel["cases"], cold["rows"], strict=True):
            assert case["id"] == row["id"]
            for group in ("rollout", "probes"):
                for state, i in enumerate(row[group]):
                    check(i, stage_prompt(case["query"], state), state)
        check(cold["old"], panel["old"], 4)
        assert checked == set(range(len(cold["calls"])))
        checks[arm] = len(checked)

    def score(routed):
        result = {}
        for case in panel["cases"]:
            steps = []
            for state in range(4):
                model = models["write_only" if state == 1 else "trajectory"]
                target = model.predict(stage_prompt(case["query"], state))["answer"] if routed else memory[state]["target"]
                steps.append(target)
                if state == 1:
                    if outputs(target.strip()) is None:
                        break
                elif not passes(state, target, case):
                    break
            ok = len(steps) == 4 and all(passes(s, t, case) for s, t in enumerate(steps))
            result[case["id"]] = dict(actions=steps, success=ok)
        old = models["trajectory"].predict(panel["old"])["answer"] if routed else memory[4]["target"]
        return dict(cases=result, old=old, old_correct=old.strip() == "0")

    return dict(checked=checks, total=sum(checks.values()), tensor_deltas=deltas,
                fixed_graph=score(True), replay=score(False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("models", type=Path)
    parser.add_argument("cold", type=Path)
    args = parser.parse_args()
    print(json.dumps(main(args.models, args.cold), ensure_ascii=False, indent=2))
