"""Independent historical calibration after the failed cohort is retired."""

import argparse
from copy import deepcopy
from pathlib import Path

from .acceptance_calibrate import run
from .selective_protocol import SPEC as ORIGINAL


SPEC = deepcopy(ORIGINAL)
SPEC.update({
    "schema": "hepta.ndu.selective-candidate-calibration.v2",
    "calibration_id_source": "Historical training pairs3000..3255, never used for outcome-head fit, selection, or earlier calibration",
    "calibration_ood_source": "Historical training pairs3400..3999, never used for outcome-head fit, selection, or earlier calibration",
    "source_slices": {"calibration_id": ["train", 3000], "calibration_ood": ["train", 3400]},
    "source_exclusions": "Every original head fit/validation pixel and every retired calibration001 ID/OOD pixel; qualification uses only separately allocated never-used official-test pixels",
    "new_random_namespaces": {"calibration_id": 27167001, "calibration_ood": 27177001,
        "qualification_id": 27187001, "qualification_ood": 27197001},
    "selector": "Frozen historical-only refinement002: public reward CNN confidence intersected with a fixed learned outcome head; all thresholds fixed before this cohort's generation",
    "earlier_calibration": "001 remains failed and is retired to development; it supplies neither the new calibration labels nor heldout estimates",
    "legacy_gate_values_unchanged": True,
    "additional_selective_gate_values_unchanged": True,
})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("assets", "generator", "binary", "development", "acceptance-development",
                 "head-development", "selector", "retired-calibration", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.assets, args.generator, args.binary, args.development, args.acceptance_development,
        args.head_development, args.output, SPEC, args.selector, args.retired_calibration)
