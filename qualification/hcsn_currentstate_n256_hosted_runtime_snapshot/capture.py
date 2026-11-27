"""Capture one GitHub-hosted zero-model runtime/resource observation."""

import json
import os

from qualification.hcsn_currentstate_n256_firststep_resource_snapshot import (
    snapshot_source,
)


IDENTITY = "hcsn-n256-hosted-runtime-snapshot-20261118-c06d-001"


def capture():
    observation = snapshot_source.observe()
    if any(observation["counts"].values()):
        raise ValueError("unexpected numerical execution count")
    if observation["resource_admitted"] or observation["all_closed"]:
        raise ValueError("unexpected admission")
    return {
        "schema": "hcsn-n256-hosted-runtime-snapshot-v1",
        "identity": IDENTITY,
        "github": {
            name: os.environ.get(name)
            for name in (
                "GITHUB_ACTION",
                "GITHUB_JOB",
                "GITHUB_REF",
                "GITHUB_REPOSITORY",
                "GITHUB_RUN_ATTEMPT",
                "GITHUB_RUN_ID",
                "GITHUB_RUN_NUMBER",
                "GITHUB_SHA",
                "RUNNER_ARCH",
                "RUNNER_NAME",
                "RUNNER_OS",
            )
        },
        "observation": observation,
        "runtime_admitted": False,
        "resource_admitted": False,
        "n256_numerical_execution_allowed": False,
        "all_closed": False,
    }


if __name__ == "__main__":
    print(json.dumps(capture(), allow_nan=False, separators=(",", ":"), sort_keys=True))
