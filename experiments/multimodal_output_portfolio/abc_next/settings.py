"""Fixed resource identities and prospectively separated source roles."""

from pathlib import Path

from ..abc_recovery.base_recovery import file_sha
from ..v7.evaluation import load_reward


REPO = Path(__file__).resolve().parents[3]
WORKSPACE = REPO.parent
OLD = WORKSPACE / "abc2-runs"
RUNS = WORKSPACE / "abc3-runs"
CACHE = WORKSPACE / "abc2-assets/mnist"
MANIFEST = OLD / "source-recovery-001/source-manifest.json"
MANIFEST_SHA = "60c24d44e12eb3defb3b1b8146d91879b84918b057e0524117137d7e4f793058"
SENSOR = RUNS / "public-sensor-001/sensor.pt"
SEEDS = (17, 29, 43, 59, 71)
ARMS = ("sft_continuation", "output_mean", "output_ndu")
FIXED_PLAN = ("refine_image", "refine_text")
PRIMARY = OLD / "base-recovery-001/reward-observer.pt"
SECONDARY = OLD / "qualification-001/secondary-observer.pt"
OBSERVER_SHA = {
    "primary": "8cfca1b0cd0a69bcfcc6a9d34d0a672c07c28f3342823ef8a3f6763e9430a003",
    "secondary": "b0851ce56189d159b53449cfc914cf84b9b63e82a6f0050228096666752595fe"}
SOURCE_RANGES = {"fit": {"role": "forecast_fit", "start": 480, "count": 256, "scenarios": 2},
                 "selection": {"role": "forecast_calibration", "start": 448, "count": 128, "scenarios": 2},
                 "qualification": {"role": "development", "start": 896, "count": 104, "scenarios": 2},
                 "test": {"role": "test", "start": 0, "count": 512, "scenarios": 4}}


def model_path(seed, arm):
    return OLD / f"training-001/seed-{seed}/{arm}/model.pt"


def resources():
    if file_sha(MANIFEST) != MANIFEST_SHA:
        raise ValueError("Frozen source manifest identity differs")
    return {"manifest_sha256": MANIFEST_SHA, "sensor_sha256": file_sha(SENSOR),
            "model_sha256": {f"{seed}/{arm}": file_sha(model_path(seed, arm)) for seed in SEEDS for arm in ARMS},
            "observer_sha256": OBSERVER_SHA}


def observers():
    return {name: load_reward(path, expected_file_sha256=OBSERVER_SHA[name])[0]
            for name, path in (("primary", PRIMARY), ("secondary", SECONDARY))}


def source_pins():
    here = Path(__file__).parent
    paths = [here / (name + ".py") for name in
             ("observability", "sensor_run", "value", "compact_tree", "settings", "development")]
    paths += [here.parent / folder / (name + ".py") for folder, names in (
        ("abc_recovery", ("runtime", "emission", "trees", "critic", "risk")),
        ("v6", ("data", "neural", "observer")), ("v7", ("data", "model", "snapshot", "sources", "evaluation")))
              for name in names]
    return {str(p.relative_to(REPO)): file_sha(p) for p in paths}
