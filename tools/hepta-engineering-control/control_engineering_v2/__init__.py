"""Public, authority-bounded Lane G engineering-control surface.

Cross-platform repository-path semantics are installed before dependent modules
are imported so every scheduler, lease, candidate and assimilation operation
uses the same alias-resistant policy.
"""
from __future__ import annotations

from . import control_plane as _control_plane
from . import path_policy as _path_policy

# Replace the legacy helpers at the owning module boundary.  Functions and
# methods defined in control_plane resolve these globals at call time, so this
# also hardens already-defined lease and scheduler operations without creating
# a second state owner.
_control_plane.canonical_repo_path = _path_policy.canonical_repo_path
_control_plane.canonical_paths = _path_policy.canonical_paths
_control_plane.paths_overlap = _path_policy.paths_overlap
_control_plane.path_sets_overlap = _path_policy.path_sets_overlap
_control_plane.path_is_within = _path_policy.path_is_within

# Preserve the package's additive convenience surface.  All authority-bearing
# decisions remain in the explicitly imported owner modules; star imports here
# do not create a second implementation or grant a capability.
from .control_plane import *  # noqa: F403,E402
from .candidate import *  # noqa: F403,E402
from .evidence import *  # noqa: F403,E402
from .assimilation import *  # noqa: F403,E402
from .facade import *  # noqa: F403,E402
