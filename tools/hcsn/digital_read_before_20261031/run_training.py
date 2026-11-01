"""Formal fit entrypoint: source freeze first, confirmation data never created."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from .data import prepare_fit
from .task import save, sha
from .train import train_fit

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def verify_sources(freeze):
    for name, digest in freeze["source_sha256"].items():
        if sha(REPO/name) != digest:
            raise ValueError(("frozen source changed", name))


def run(fit, runs, freeze_path):
    freeze = json.loads(Path(freeze_path).read_text())
    verify_sources(freeze)
    protocol = json.loads((HERE/"protocol.json").read_text())
    if fit not in protocol["fits"]:
        raise ValueError("fit not registered")
    runs = Path(runs).resolve()
    folder = runs/f"fit_{fit}"
    folder.mkdir(parents=True, exist_ok=False)
    save(folder/"RUN_STARTED.json", dict(fit=fit, started_at=datetime.now(timezone.utc).isoformat(),
                                       source_commit=freeze["source_commit"], freeze_sha256=sha(freeze_path),
                                       confirmation_generated=False))
    print(json.dumps(dict(stage="preparing_actual_content_data", fit=fit)), flush=True)
    prepare_fit(folder/"data", fit, protocol)
    result = train_fit(folder/"data"/f"fit_{fit}_data.json", protocol, folder/"models")
    verify_sources(freeze)
    save(folder/"RUN_COMPLETE.json", dict(fit=fit, source_commit=freeze["source_commit"],
                                        finished_at=datetime.now(timezone.utc).isoformat(), total=result["total"]))
    print(json.dumps(dict(stage="fit_complete", fit=fit, total=result["total"])), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fit", type=int, required=True)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, default=HERE/"SOURCE_FREEZE.json")
    args = parser.parse_args()
    run(args.fit, args.runs, args.freeze)


if __name__ == "__main__":
    main()
