#!/usr/bin/env python3
"""Execute frozen V4 convergence, then the reviewed final roadmap transform."""

from __future__ import annotations

import base64
import subprocess
from pathlib import Path

FROZEN_SOURCE_COMMIT = "ec66a1003e3f42b7a65631997ec3fcdd32c56a66"
SCRIPT_PATH = "scripts/learning_operator_remaining_convergence.py"

source = subprocess.check_output(
    ["git", "show", f"{FROZEN_SOURCE_COMMIT}:{SCRIPT_PATH}"],
    text=True,
)
old = '''replace_once(
    "codex-rs/hepta-agentd/src/lib.rs",
    """pub use cognitive_ranker::CurrentCognitiveRegistry;\npub use cognitive_ranker::PinnedCognitiveRanker;\n""",
    """pub use cognitive_ranker::CognitiveRankerMetricsSnapshotV1;\npub use cognitive_ranker::CurrentCognitiveRegistry;\npub use cognitive_ranker::PinnedCognitiveRanker;\npub use cognitive_ranker::ReloadableCognitiveRanker;\n""",
)
'''
new = '''replace_once(
    "codex-rs/hepta-agentd/src/lib.rs",
    """pub use cognitive_ranker::CurrentCognitiveRegistry;\npub use cognitive_ranker::CurrentRankerAdmission;\npub use cognitive_ranker::PinnedCognitiveRanker;\npub use cognitive_ranker::RankerAdmissionSnapshotV2;\n""",
    """pub use cognitive_ranker::CognitiveRankerMetricsSnapshotV1;\npub use cognitive_ranker::CurrentCognitiveRegistry;\npub use cognitive_ranker::CurrentRankerAdmission;\npub use cognitive_ranker::PinnedCognitiveRanker;\npub use cognitive_ranker::RankerAdmissionSnapshotV2;\npub use cognitive_ranker::ReloadableCognitiveRanker;\n""",
)
'''
if old not in source:
    raise SystemExit("frozen convergence script no longer contains the audited Agentd marker")
source = source.replace(old, new, 1)

resolved = Path(__file__).resolve()
namespace = {
    "__name__": "__main__",
    "__file__": str(resolved),
    "__package__": None,
}
exec(compile(source, str(resolved), "exec"), namespace)

part_paths = [
    resolved.parent / f"learning_operator_roadmap_convergence.part{index:02d}.b64"
    for index in range(6)
]
if not all(part.is_file() for part in part_paths):
    raise SystemExit("final learning.operator roadmap transform parts are incomplete")
encoded = "".join("".join(part.read_text(encoding="ascii").split()) for part in part_paths)
try:
    roadmap = base64.b64decode(encoded, validate=True).decode("utf-8")
except Exception as error:
    raise SystemExit(f"final learning.operator roadmap transform is corrupt: {error}") from error
roadmap_name = str(resolved.parent / "learning_operator_roadmap_convergence.py")
exec(
    compile(roadmap, roadmap_name, "exec"),
    {
        "__name__": "__main__",
        "__file__": roadmap_name,
        "__package__": None,
    },
)
