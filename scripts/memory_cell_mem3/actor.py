"""Three current-information readers and one shared value-blind fenced composer."""

from collections import Counter
import json
import math
import random

from fixture import digest, encoded, gate, metadata
from native import NativeMemory, argmax


class MeteredMemory(NativeMemory):
    def __init__(self, *args, trace, **kwargs):
        self.trace, self.request_bytes = trace, 0
        super().__init__(*args, **kwargs)

    def command(self, text):
        self.request_bytes += len((text + "\n").encode())
        record = {"request": text}
        self.trace.write(json.dumps({"event": "attempt", **record}) + "\n")
        self.trace.flush()
        try:
            reply = super().command(text)
            record.update(status="completed", reply=reply)
            return reply
        except Exception as error:
            record.update(status="failed", error=repr(error))
            raise
        finally:
            self.trace.write(json.dumps({"event": "receipt", **record}) + "\n")
            self.trace.flush()


class Reader:
    def __init__(self, arm, stage, features, seed, binary, directory):
        self.arm, self.features = arm, features if arm == "native" else None
        self.versions = (
            {f["source"]: f["version"] for f in stage["facts"]}
            if arm == "native"
            else None
        )
        self.memory, self.trace = None, None
        self.cost = Counter(
            provided_information_bytes=len(
                encoded({"stage": stage, "features": features})
            ),
            owner_metadata_bytes=len(encoded(metadata(stage["facts"]))),
            native_updates=0,
            native_predictions=0,
            replay_payload_bytes=0,
            retrieval_calls=0,
            retrieval_candidates_scored=0,
            retrieval_payload_bytes=0,
            teacher_calls=0,
            teacher_bytes=0,
            teacher_multiplications=0,
        )
        if arm != "native":
            self.facts = {
                f["source"]: (
                    f
                    if arm == "bm25"
                    else {"value": f["value"], "version": f["version"]}
                )
                for f in stage["facts"]
            }
            self.docs = (
                {
                    s: [
                        f"node{f['node']}",
                        f"relation{f['relation']}",
                        f"target{f['value']}",
                        f"version{f['version']}",
                    ]
                    for s, f in self.facts.items()
                }
                if arm == "bm25"
                else {}
            )
            self.cost["stored_payload_bytes"] = len(encoded(self.facts)) + (
                len(encoded(self.docs)) if self.docs else 0
            )
            return
        self.trace = (directory / "native.jsonl").open("w")
        try:
            self.memory = MeteredMemory(
                binary,
                f"cell:mem3:{seed}:{stage['generation']}",
                stage["generation"],
                trace=self.trace,
            )
            meta = metadata(stage["facts"])
            eligible = [
                f
                for f in stage["facts"]
                if gate(meta, f["source"], f["version"], stage["tick"]) is None
            ]
            order = eligible * 8
            random.Random(seed * 101 + stage["generation"]).shuffle(order)
            for fact in order:
                key = features[fact["source"]]
                target = [float(i == fact["value"]) for i in range(8)]
                support = digest(
                    {"generation": stage["generation"], "fact": fact, "key": key}
                )
                self.memory.update(key, target, support)
                self.cost["native_updates"] += 1
                self.cost["replay_payload_bytes"] += len(
                    encoded({"fact": fact, "key": key})
                )
            checkpoint = self.memory.checkpoint()
            (directory / "state.bin").write_bytes(bytes.fromhex(checkpoint[1]))
            self.cost["stored_payload_bytes"] = len(bytes.fromhex(checkpoint[1])) + len(
                encoded({"features": features, "versions": self.versions})
            )
        except Exception:
            self.close()
            raise

    def read(self, source):
        if source not in (self.versions if self.arm == "native" else self.facts):
            return None
        if self.arm == "native":
            self.cost["native_predictions"] += 1
            return {
                "value": argmax(self.memory.predict(self.features[source])),
                "version": self.versions[source],
            }
        self.cost["retrieval_calls"] += 1
        selected = source
        if self.arm == "bm25":
            relation, node = source.split(":")
            terms = [f"node{node}", f"relation{relation}"]
            df = Counter(
                term for document in self.docs.values() for term in set(document)
            )
            average = sum(map(len, self.docs.values())) / len(self.docs)
            scores = {}
            for identity, document in self.docs.items():
                frequencies = Counter(document)
                scores[identity] = sum(
                    math.log(1 + (len(self.docs) - df[t] + 0.5) / (df[t] + 0.5))
                    * frequencies[t]
                    * 2.2
                    / (frequencies[t] + 1.2 * (0.25 + 0.75 * len(document) / average))
                    for t in terms
                )
            self.cost["retrieval_candidates_scored"] += len(scores)
            selected = next(
                (
                    s
                    for s in sorted(scores, key=lambda s: (-scores[s], s))
                    if self.facts[s]["relation"] == relation
                    and self.facts[s]["node"] == int(node)
                ),
                None,
            )
        if selected is None:
            return None
        fact = self.facts[selected]
        result = {"value": fact["value"], "version": fact["version"]}
        self.cost["retrieval_payload_bytes"] += len(encoded(result))
        return result

    def transition_diagnostic(self):
        before = self.memory.checkpoint()
        key = ",".join(map(repr, self.features["A:0"]))
        commands = (f"predict 2 {key}", f"update 2 {'1' * 64} {key} 1,0,0,0,0,0,0,0")
        records = []
        for command in commands:
            try:
                self.memory.command(command)
                records.append({"command": command, "rejected": False})
            except ValueError as error:
                records.append(
                    {"command": command, "rejected": True, "error": str(error)}
                )
        after = self.memory.checkpoint()
        return {
            "records": records,
            "checkpoint_unchanged": before == after,
            "before": before[0],
            "after": after[0],
        }

    def close(self):
        if self.memory is not None:
            self.cost.update(
                native_multiplications=self.memory.multiplications,
                native_calls=self.memory.calls,
                native_ipc_wall_ns=self.memory.wall_ns,
                native_request_bytes=self.memory.request_bytes,
            )
            self.memory.close()
            self.memory = None
        if self.trace is not None:
            self.trace.close()
            self.trace = None


def compose(reader, meta, task, tick):
    result = {
        "task_id": task["task_id"],
        "value": None,
        "steps": [],
        "abstain_reason": None,
    }
    if len(task["program"]) > task["budget"]:
        result["abstain_reason"] = "constraint_budget"
        return result
    node = task["start"]
    for relation in task["program"]:
        source = f"{relation}:{node}"
        prediction = reader.read(source)
        if prediction is None:
            result["abstain_reason"] = "unknown"
            return result
        reason = gate(
            meta,
            source,
            prediction["version"],
            tick,
            task.get("required_versions", {}).get(source),
        )
        result["steps"].append(
            {"source": source, **prediction, "gate": reason, "used": reason is None}
        )
        if reason is not None:
            result["abstain_reason"] = reason
            return result
        node = prediction["value"]
    if "allowed_end" in task and node not in task["allowed_end"]:
        result["abstain_reason"] = "constraint_endpoint"
        return result
    result["value"] = node
    return result
