"""Seal a committed dependency port without replaying its historical patch."""

import shutil

from ndu_port_candidate_common import INTEGRATION
from ndu_port_candidate_common import LOCKS
from ndu_port_candidate_common import POLICIES
from ndu_port_candidate_common import RECIPE
from ndu_port_candidate_common import SOURCE_AMENDMENT
from ndu_port_candidate_common import check_checkout
from ndu_port_candidate_common import check_toolchain
from ndu_port_candidate_common import checksum
from ndu_port_candidate_common import copy_files
from ndu_port_candidate_common import describe
from ndu_port_candidate_common import load_recipe
from ndu_port_candidate_common import validate_graph
from ndu_port_candidate_common import verify_integrated_source
from ndu_port_candidate_common import verify_tree
from ndu_port_candidate_common import verify_vendor


def generate_integrated(runner, expected_source):
    """Require exact committed bytes and real zero-drift Cargo/Bazel verification."""
    check_checkout(runner, expected_source)
    recipe = load_recipe(runner.root)
    manifest, binding, source_tree = verify_integrated_source(runner, recipe)
    runner.record.update(
        source_mode="integrated",
        source_tree=source_tree,
        integration=binding,
        recipe_sha256=checksum(runner.root / RECIPE),
        policy_inputs=describe(runner.root, POLICIES),
        lock_inputs=describe(runner.root, LOCKS),
    )
    shutil.copyfile(runner.root / RECIPE, runner.output / "recipe.json")
    shutil.copyfile(runner.root / INTEGRATION, runner.output / "integration.json")
    shutil.copyfile(runner.root / recipe["patch_path"], runner.output / "source.patch")
    amendment_artifacts = ()
    if "source_amendment" in binding:
        shutil.copyfile(
            runner.root / SOURCE_AMENDMENT, runner.output / "source-amendment.json"
        )
        amendment_artifacts = ("source-amendment.json",)
    # An explicitly declared empty delta binds this already committed source.
    # Patched mode still requires successful nonempty Git patch application.
    (runner.output / "candidate.patch").write_bytes(b"")
    verify_vendor(runner.root, recipe, source_mode="integrated")
    check_toolchain(runner, "1.96.0")
    runner.run("bazel-version", ["bazel", "--version"])
    metadata_command = [
        "cargo",
        "metadata",
        "--manifest-path",
        str(runner.root / "codex-rs/Cargo.toml"),
        "--locked",
        "--format-version",
        "1",
    ]
    before = runner.json_command("metadata-before-bazel", metadata_command)
    validate_graph(runner.root, recipe, before)
    runner.run("bazel-lock-update", ["just", "bazel-lock-update"])
    runner.run("bazel-lock-check", ["just", "bazel-lock-check"])
    after = runner.json_command("metadata", metadata_command)
    validate_graph(runner.root, recipe, after)
    if before != after:
        raise ValueError("Integrated dependency graph drifted during lock generation")
    runner.run("diff-check", ["git", "diff", "--check", "HEAD"])
    runner.record.update(files=manifest["files"], changed_paths=[])
    copy_files(runner.root, runner.output / "files", manifest["files"])
    runner.record["artifacts"] = describe(
        runner.output,
        (
            "recipe.json",
            "integration.json",
            "source.patch",
            "candidate.patch",
            "metadata-before-bazel.json",
            "metadata.json",
            *amendment_artifacts,
        ),
    )
    verify_tree(runner, runner.record, recipe)
    runner.record.update(
        status="candidate_generated",
        integration_lock_drift=False,
        qualification=(
            "Committed source and real zero-drift Cargo/Bazel lock verification only. "
            "Same-run unchanged cargo-deny, old-store reopen, behavioral tests and "
            "platform qualification remain separate."
        ),
    )
