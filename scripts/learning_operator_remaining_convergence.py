#!/usr/bin/env python3
"""Execute the frozen learning.operator convergence with one audited drift fix.

The full deterministic transformation remains pinned to commit
``ec66a1003e3f42b7a65631997ec3fcdd32c56a66``.  The branch acquired two
additional Agentd ranker exports before the one-shot writer ran, so the old
marker must be widened without changing any requested transformation.
"""

from __future__ import annotations

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
