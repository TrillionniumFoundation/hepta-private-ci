"""One ARM job: same-run producer restore, online materialization, offline qualification."""

from pathlib import Path
from types import SimpleNamespace

from .contract import reject_compiler_overrides
from .files import checksum, describe, physical, read_json, write_json
from .orchestrate import host_commands, run
from .prepare import preparation
from .source import restore_source


def ci(args):
    import os

    output = physical(Path(args.output).absolute())
    checkouts = physical(Path(args.worktree_parent).absolute())
    record = {
        "schema": "hepta.synapse.linux.ci.v1",
        "status": "started",
        "scope": "native-linux-arm64",
        "source_commit": args.source_commit,
        "producer_result_sha256": args.producer_result_sha256,
        "macos_qualification": False,
        "windows_qualification": False,
        "production_approval": False,
        "promotion_allowed": False,
        "host_rust_toolchain_required": False,
    }
    write_json(output / "CI_STARTED.json", record)
    try:
        reject_compiler_overrides(os.environ)
        if checkouts.is_relative_to(
            Path(args.restored_root).resolve()
        ) or output.is_relative_to(Path(args.restored_root).resolve()):
            raise ValueError(
                "CI evidence and qualification checkouts must be outside the input checkout"
            )
        checkouts.mkdir(mode=0o700, exist_ok=False)
        restore_output = output / "restore"
        restore_output.mkdir(mode=0o700)
        commands = host_commands(args, restore_output)
        tree = restore_source(
            Path(args.restored_root).resolve(),
            Path(args.producer).resolve(),
            args.producer_result_sha256,
            args.source_commit,
            restore_output,
            commands,
        )
        prep_args = SimpleNamespace(
            **{
                **vars(args),
                "phase": "prepare",
                "output": str(output / "preparation"),
                "worktree": str(checkouts / "preparation"),
            }
        )
        prepared = preparation(prep_args)
        prep = Path(prep_args.output)
        if (
            prepared["status"] != "prepared_not_qualified"
            or prepared["source_candidate_tree"] != tree
            or prepared["source_producer_result_sha256"] != args.producer_result_sha256
        ):
            raise ValueError("Preparation did not use this exact restored candidate")
        run_args = SimpleNamespace(
            **{
                **vars(args),
                "phase": "run",
                "output": str(output / "qualification"),
                "worktree": str(checkouts / "qualification"),
                "builder_seal": str(prep / "BUILDER_SEAL.json"),
                "builder_seal_sha256": checksum(prep / "BUILDER_SEAL.json"),
                "builder_archive": str(prep / "builder-image.tar.gz"),
                "tool_bundle": str(prep / "tool-bundle"),
                "cargo_seed": str(prep / "prefetch/cargo-home"),
                "seed_ledger": str(prep / "prefetch/SEED_LEDGER.json"),
                "seed_ledger_sha256": checksum(prep / "prefetch/SEED_LEDGER.json"),
            }
        )
        qualified = run(run_args)
        source = read_json(Path(run_args.output) / "source/SOURCE_SEAL.json")
        if (
            qualified["status"] != "qualified_native_linux_arm64_only"
            or source["candidate_tree"] != tree
            or source["producer_result_sha256"] != args.producer_result_sha256
        ):
            raise ValueError(
                "Offline execution did not qualify this exact producer tree"
            )
        record.update(
            status="qualified_native_linux_arm64_only",
            candidate_tree=tree,
            restored_source=describe(restore_output / "RESTORED_SOURCE.json"),
            preparation_result=describe(prep / "PREPARATION_RESULT.json"),
            qualification_result=describe(Path(run_args.output) / "RESULT.json"),
            builder_seal=describe(prep / "BUILDER_SEAL.json"),
            seed_ledger=describe(prep / "prefetch/SEED_LEDGER.json"),
            executing_qualification_commit=source["qualification_commit"],
            statement="Normal macOS/Windows compilation, cargo-deny and production activation remain independent unchanged gates.",
        )
    except BaseException as error:
        record.update(
            status="failed", error_type=type(error).__name__, error=str(error)
        )
        raise
    finally:
        write_json(output / "CI_RESULT.json", record)
    return record
