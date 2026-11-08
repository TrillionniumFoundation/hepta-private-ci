"""Synthetic contract exercise for four task families; no training claims."""
from pathlib import Path

from .experiment import FixtureExecutor
from .report import build_report
from .schema import ARMS, FAMILIES, PHASES, Dataset, canonical, manifest, sha


def write_json(path, value):
    Path(path).write_bytes(canonical(value) + b"\n")


def smoke(output):
    root = Path(output).resolve()
    (root / "views").mkdir(parents=True, exist_ok=True)
    sources, episodes, targets = [], [], []
    values = ("$1,200.05", "disabled", "v2:not-ready", "target@120ms")
    for split in ("train", "dev", "confirmation"):
        for family, truth in zip(FAMILIES, values):
            eid = split + "." + family
            ids = [eid + "." + str(i) for i in range(3)]
            episodes.append(dict(id=eid, group=eid, split=split, family=family, task="Return the exact critical field; synthetic family=" + family,
                                 source_ids=ids, initial_ids=[ids[0]]))
            texts = ["next:" + ids[2] + "\n", "distractor:" + eid + "\n", "answer:" + truth + "\nepisode:" + eid + "\n"]
            for i, (sid, text) in enumerate(zip(ids, texts)):
                raw, path = text.encode(), "views/" + sid + ".fixture.txt"
                (root / path).write_bytes(raw)
                loc = dict(kind="bytes", origin_sha256=sha(raw), start=0, end=len(raw), total=len(raw))
                if family == "blurred_screenshot":
                    loc = dict(kind="image", origin_sha256=sha([eid, "synthetic-origin"]), x0=0, y0=0, x1=64, y1=64, width=64, height=64)
                elif family == "distractor_video":
                    loc = dict(kind="video", origin_sha256=sha([eid, "synthetic-origin"]), x0=0, y0=0, x1=64, y1=64, width=64, height=64,
                               start_ns=100000000, end_ns=200000000, duration_ns=1000000000, first_frame=3, last_frame=6, frame_count=30)
                elif family == "asynchronous_state":
                    loc = dict(kind="state", origin_sha256=sha([eid, "synthetic-origin"]), pointer="/critical", version="v2", event_ns=1000)
                sources.append(dict(id=sid, episode_id=eid, group=eid, split=split, description="Candidate captured view " + str(i),
                                    uri="synthetic://" + sid, path=path, sha256=sha(raw), byte_length=len(raw), locator=loc,
                                    available_ns=2000 if family == "asynchronous_state" and i == 2 else 0))
            targets.append(dict(episode_id=eid, answer=truth, fields={"critical": truth}, required_evidence=[ids[2]]))
    data = dict(schema="perc1.dataset.v1", sources=sources, episodes=episodes)
    canaries = ["SEALED_EVALUATOR_CANARY_NEVER_ACTOR_7319"]
    evaluator = dict(schema="perc1.evaluator.v1", identity_sha256=sha(Path(__file__).with_name("report.py").read_bytes()),
                     rubric_sha256=sha("exact answer and all critical strings"), targets=targets, canaries=canaries,
                     receipt_sha256=sha("synthetic-evaluation-receipt"), cost={p: int(p == "evaluation") for p in PHASES})
    encoder_hash = sha(Path(__file__).with_name("experiment.py").read_bytes())
    frozen = dict(schema="perc1.manifest.v1", dataset_sha256=sha(data),
                  encoder=dict(kind="diagnostic_fixture", checkpoint_sha256=encoder_hash, preprocessor_sha256=sha(Path(__file__).with_name("schema.py").read_bytes()), dimension=2),
                  controller=dict(sha256=encoder_hash, training_runs=[dict(seed=seed, receipt_sha256=sha(["synthetic-training", seed]),
                                  cost={p: 100 if p == "training" else 0 for p in PHASES}) for seed in (11, 29)]),
                  evaluator={"identity_sha256": evaluator["identity_sha256"], "rubric_sha256": evaluator["rubric_sha256"],
                             "targets_sha256": sha(targets), "canaries_sha256": sha(canaries)}, teacher_sha256=None,
                  budget=dict(unit="microcredits_v1", cap=100000, tariff={p: 1 for p in PHASES}),
                  splits={split: [e["group"] for e in episodes if e["split"] == split] for split in ("train", "dev", "confirmation")}, thresholds=None)
    dataset = Dataset(data, root)
    manifest(frozen, dataset)
    traces = [FixtureExecutor(frozen, dataset, episode, seed, arm).run() for episode in episodes if episode["split"] == "confirmation"
              for seed in (11, 29) for arm in ARMS]
    report = build_report(frozen, dataset, traces, evaluator)
    outputs = {"dataset": data, "manifest": frozen, "traces": traces, "evaluator": evaluator, "report": report}
    for name, value in outputs.items():
        write_json(root / (name + ".json"), value)
    return {"status": "HOLD", "structural_validation": "PASS", "paired_traces": len(traces), "output": str(root),
            "note": "Synthetic text descriptors exercise image/video/state coordinate schemas; they are not captured media or learned representations."}
