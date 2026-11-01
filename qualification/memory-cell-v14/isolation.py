"""Scoped independent cells with a current-source fallback, reusing V13 ownership.

Every fitted artifact starts from fresh parameters and depends on exactly one
source. No mixed ancestor is relabelled or stripped of dependencies. This remains
a research SQLite owner; fallback is exact source use, not learned inference.
"""

import json
from pathlib import Path
import sys
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "memory-cell-v13"))
from adapter import Adapter
from lifecycle import Refused, SourceOwner, canonical, sha
from provenance_run import dataset
import tasks


def identity(kind, key):
    if kind == "skill" and key == "skills":
        return "skills"
    if kind == "project" and isinstance(key, str) and key and ":" not in key:
        return "project:" + key
    raise Refused("invalid memory type or key")


class IsolatedMemory:
    """One source per cell; explicit scope/type checks on writes, fits and reads."""

    def __init__(self, root, scope, encoder_hash):
        self.owner = SourceOwner(root)
        self.scope, self.encoder_hash = scope, encoder_hash

    def close(self):
        self.owner.close()

    def put(self, kind, key, payload, *, expected_revision, active=True):
        sid = identity(kind, key)
        body = dict(schema="hepta.memory.isolated-source.v14", scope=self.scope,
                    kind=kind, key=key, payload=payload)
        return self.owner.put(self.scope, sid, canonical(body).decode(),
                              expected_revision=expected_revision, active=active)

    def _source(self, kind, key):
        row = self.owner.source(self.scope, identity(kind, key))
        if row is None:
            raise Refused("source missing")
        body = json.loads(row["body"])
        expected = ("hepta.memory.isolated-source.v14", self.scope, kind, key)
        if tuple(body.get(k) for k in ("schema", "scope", "kind", "key")) != expected:
            raise Refused("source scope or memory type mismatch")
        if sha(row["body"].encode()) != row["body_sha256"]:
            raise Refused("source body integrity mismatch")
        return row, body["payload"]

    def fit_publish(self, kind, key, inputs, calibration_name, *, seed=713,
                    steps=240, lr=0.01, skill_floor=40):
        """Train from this source alone; publish only after actual calibration."""
        started, cpu = time.perf_counter(), time.process_time()
        sid, inputs = identity(kind, key), Path(inputs)
        with self.owner.transaction():
            cut = self.owner.cut(self.scope, [sid])
            _, payload = self._source(kind, key)
        name, indices = payload["dataset"], payload["indices"]
        X, rows = dataset(inputs, name)
        selected = [rows[i] for i in indices]
        if (sha((inputs / f"{name}_features.npz").read_bytes()) != payload["feature_file_sha256"]
                or selected != payload["rows"] or not selected
                or any(row["split"] != "train" for row in selected)):
            raise Refused("training features or rows differ from the admitted source")
        event = payload["event"]
        if kind == "project":
            if (event["project"] != key or any(row["project"] != key
                    or row["label"] != tasks.SKILLS.index(event["operation_id"])
                    or row["source_digest"] != event["digest"] for row in selected)):
                raise Refused("project training does not follow its source event")
        elif event is not None or any("project" in row for row in selected):
            raise Refused("skill source contains project dependencies")
        version = sha(canonical(cut))
        model = Adapter(X.shape[1], len(tasks.SKILLS), 8, seed,
                        encoder_hash=self.encoder_hash, source_version=version)
        before = model.state_hash()
        training = model.train(X[indices], np.asarray([r["label"] for r in selected]),
                               steps=steps, batch_size=20, lr=lr,
                               data_id=sha(canonical([r["id"] for r in selected])),
                               source_version=version)
        if steps < 1 or model.state_hash() == before:
            raise Refused("candidate did not perform an actual training update")
        artifact = self.owner.stage(self.scope, cut, model)
        XC, calibration = dataset(inputs, calibration_name)
        chosen = [i for i, r in enumerate(calibration) if kind == "skill" or r.get("project") == key]
        if not chosen or any(calibration[i]["split"] != "calibration" for i in chosen):
            raise Refused("calibration requires distinct calibration rows")
        if kind == "project" and any(calibration[i]["source_digest"] != event["digest"] for i in chosen):
            raise Refused("calibration belongs to another project source version")
        validation = {}

        def validate(candidate, sources):
            predicted = candidate.predict(XC[chosen])
            correct = sum(tasks.score_prediction(calibration[i], int(p))["correct"]
                          for i, p in zip(chosen, predicted))
            floor = skill_floor if kind == "skill" else len(chosen)
            validation.update(passed=correct >= floor, correct=correct, total=len(chosen),
                              floor=floor, source_count=len(sources), calibration_only=True)
            return dict(validation)

        prior = self.owner.db.execute("SELECT epoch FROM releases WHERE scope=? AND cell=?",
                                      (self.scope, sid)).fetchone()
        epoch, reason = (0 if prior is None else prior["epoch"]), None
        try:
            epoch = self.owner.publish(self.scope, sid, artifact, self.encoder_hash,
                                       expected_epoch=epoch, validator=validate)
            status = "published"
        except Refused as error:
            status, reason = "rejected", str(error)
        return dict(status=status, reason=reason, epoch=epoch, artifact=artifact,
                    source_cut=cut, source_version=version, validation=validation,
                    training=training, state_sha256=model.state_hash(),
                    fresh_initialization=True, parent_artifact=None,
                    checkpoint_bytes=(self.owner.root / "artifacts" / artifact / "model.npz").stat().st_size,
                    wall_seconds=time.perf_counter() - started, cpu_seconds=time.process_time() - cpu)

    def read(self, kind, key, X, *, scope, encoder_hash):
        """A read either uses a fresh learned cell, legal exact source, or refuses.

        No labels, expected outputs or test switches are accepted by this API.
        The transaction gives model/source freshness a single linearization point.
        """
        started, cpu = time.perf_counter(), time.process_time()
        result = dict(mode="refused", predictions=[], artifact=None, epoch=None,
                      source_version=None, reason=None, checkpoint_bytes_read=0)
        try:
            if scope != self.scope or encoder_hash != self.encoder_hash:
                raise Refused("request scope or encoder mismatch")
            sid = identity(kind, key)
            X = np.asarray(X)
            if X.ndim != 2 or len(X) == 0 or not np.isfinite(X).all():
                raise Refused("invalid request features")
            with self.owner.transaction():
                source, payload = self._source(kind, key)
                result.update(source_id=sid, source_revision=source["revision"],
                              source_body_sha256=source["body_sha256"], source_active=bool(source["active"]))
                if not source["active"]:
                    raise Refused("source revoked")
                cut = self.owner.cut(scope, [sid])
                result["source_version"] = sha(canonical(cut))
                release = self.owner.db.execute("SELECT * FROM releases WHERE scope=? AND cell=?",
                                                (scope, sid)).fetchone()
                unavailable = "cell has no release"
                if release is not None:
                    model, manifest = self.owner.load(release["artifact"], scope, encoder_hash)
                    result["checkpoint_bytes_read"] = (self.owner.root / "artifacts" / release["artifact"] / "model.npz").stat().st_size
                    if [r["source_id"] for r in manifest["source_cut"]["records"]] != [sid]:
                        raise Refused("release is not an isolated cell of the requested type")
                    if manifest["source_cut"] == cut:
                        result.update(mode="learned", predictions=model.predict(X).tolist(),
                                      artifact=release["artifact"], epoch=release["epoch"])
                    unavailable = "source correction invalidated learned release"
                if result["mode"] != "learned":
                    if kind != "project":
                        raise Refused(unavailable + "; no exact semantic-skill fallback")
                    event = payload["event"]
                    if event["project"] != key or event["operation_id"] not in tasks.SKILLS:
                        raise Refused("current project source has no legal operation")
                    result.update(mode="fallback", predictions=[tasks.SKILLS.index(event["operation_id"])] * len(X),
                                  reason=unavailable, fallback="current_exact_project_source")
        except (Refused, ValueError, TypeError, KeyError) as error:
            result.update(mode="refused", predictions=[], reason=str(error))
        result.update(wall_seconds=time.perf_counter() - started, cpu_seconds=time.process_time() - cpu,
                      encoder_preparation_cost_separate=True)
        return result
