#!/usr/bin/env python3
"""Add the private diagnostic cfg only to two exact library compilations."""

import json
import os
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
CFG = "hepta_ci_phase_diagnostic"
ADDED = ["--cfg", CFG, "--check-cfg", f"cfg({CFG})"]
PAIRS = {
    "codex_hepta_agentd": ROOT / "codex-rs/hepta-agentd/src/lib.rs",
    "codex_hepta_contracts": ROOT / "codex-rs/hepta-contracts/src/lib.rs",
}


def transform(arguments, cwd):
    if any(CFG in argument for argument in arguments):
        raise ValueError("the diagnostic cfg must originate only from this wrapper")
    names = []
    for position, argument in enumerate(arguments):
        if argument == "--crate-name":
            if position + 1 == len(arguments):
                raise ValueError("crate name has no value")
            names.append(arguments[position + 1])
        elif argument.startswith("--crate-name="):
            names.append(argument.split("=", 1)[1])
    if len(names) > 1:
        raise ValueError("ambiguous crate name")
    name = names[0] if names else None
    sources = [
        str((cwd / argument).resolve())
        for argument in arguments
        if argument.endswith(".rs") and not argument.startswith("-")
    ]
    expected = PAIRS.get(name)
    inject = expected is not None and sources == [str(expected.resolve())]
    # Agentd's main.rs also normalizes to codex_hepta_agentd. Name alone must
    # never inject into that binary, a different checkout, or another crate.
    return {
        "crate": name,
        "sources": sources,
        "injected": inject,
        "originalArguments": list(arguments),
        "executedArguments": [*arguments, *ADDED] if inject else list(arguments),
    }


def main():
    if len(sys.argv) < 2:
        raise ValueError("Cargo did not supply its compiler executable")
    directory = Path(os.environ["HEPTA_PHASE_WRAPPER_RECORDS"])
    if (
        not directory.is_absolute()
        or directory.is_symlink()
        or directory.resolve().is_relative_to(ROOT)
        or not directory.is_dir()
    ):
        raise ValueError("wrapper records must be outside the source checkout")
    compiler, arguments = sys.argv[1], sys.argv[2:]
    cwd = Path.cwd().resolve()
    record = transform(arguments, cwd)
    record.update(
        schemaVersion=1,
        pid=os.getpid(),
        cwd=str(cwd),
        root=str(ROOT),
        compiler=compiler,
        recordedAtNs=time.time_ns(),
        stage=os.environ.get("HEPTA_PHASE_STAGE"),
        status="dispatch_recorded_not_compiler_completion",
    )
    path = directory / f"compiler-{os.getpid()}-{record['recordedAtNs']}.json"
    with path.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    # Replacing this wrapper preserves the compiler's exit and signal result.
    # No subprocess deadline, signal, feature, optimization or lint override.
    os.execvpe(compiler, [compiler, *record["executedArguments"]], os.environ)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        print(f"diagnostic compiler wrapper refused: {error}", file=sys.stderr)
        raise SystemExit(1) from error
