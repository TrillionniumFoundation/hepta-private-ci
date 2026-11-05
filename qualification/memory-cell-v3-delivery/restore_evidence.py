"""Verify the two research bundles and recover a new exact-evidence worktree."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


DELIVERY = Path(__file__).resolve().parent
MIRROR = DELIVERY.parents[1]


def run(repo, *arguments):
    return subprocess.run(["git", "-C", str(repo), *arguments], check=True)


def verify(path, expected):
    payload = path.read_bytes()
    if (
        len(payload) != expected["bytes"]
        or hashlib.sha256(payload).hexdigest() != expected["sha256"]
    ):
        raise ValueError(f"bundle or part identity differs: {path}")
    return payload


def get_bundle(explicit, bundled, output, parts, expected):
    if explicit is not None:
        explicit = explicit.resolve()
        verify(explicit, expected)
        return explicit
    if bundled.exists():
        verify(bundled, expected)
        return bundled
    with output.open("xb") as stream:
        for path, receipt in parts:
            if receipt is None:
                stream.write(path.read_bytes())
            else:
                stream.write(verify(path, receipt))
    verify(output, expected)
    return output


def import_ref(repo, bundle, source_ref, destination_ref, expected):
    present = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", destination_ref],
        capture_output=True,
        text=True,
    )
    if present.returncode == 0 and present.stdout.strip() != expected:
        raise ValueError(
            f"destination research ref already has different history: {destination_ref}"
        )
    run(repo, "bundle", "verify", str(bundle))
    run(repo, "fetch", str(bundle), source_ref + ":" + destination_ref)
    actual = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", destination_ref], text=True
    ).strip()
    if actual != expected:
        raise ValueError("recovered commit identity differs")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--worktree", required=True, type=Path)
    parser.add_argument("--v1-v2-bundle", type=Path)
    parser.add_argument("--v3-bundle", type=Path)
    args = parser.parse_args()
    repo, worktree = args.repo.resolve(), args.worktree.resolve()
    if worktree.exists() or worktree.is_symlink():
        parser.error("worktree output must not already exist")
    metadata = json.loads((DELIVERY / "DELIVERY.json").read_bytes())
    previous, current = metadata["original_v1_v2_bundle"], metadata["v3_bundle"]
    run(repo, "cat-file", "-e", previous["required_repository_baseline"] + "^{commit}")
    with tempfile.TemporaryDirectory(prefix="hepta-memory-v3-recovery-") as temporary:
        temporary = Path(temporary)
        old_name = "hepta-memory-v1-v2-history-20261026.bundle"
        old_parts = [
            (
                MIRROR
                / previous["existing_delivery_path"]
                / "bundle-parts"
                / (old_name + f".part{index:03d}"),
                None,
            )
            for index in range(1, 6)
        ]
        old = get_bundle(
            args.v1_v2_bundle,
            MIRROR / "bundles" / old_name,
            temporary / old_name,
            old_parts,
            previous,
        )
        new_parts = [(MIRROR / part["path"], part) for part in current["parts"]]
        new = get_bundle(
            args.v3_bundle,
            MIRROR / "bundles" / current["filename"],
            temporary / current["filename"],
            new_parts,
            current,
        )
        import_ref(
            repo,
            old,
            "refs/heads/research/memory-cell-six-stage-20261025",
            "refs/heads/research/memory-cell-v2-exact-evidence",
            previous["required_research_commit_after_import"],
        )
        import_ref(
            repo,
            new,
            current["advertised_ref"],
            "refs/heads/research/memory-cell-v3-exact-evidence",
            metadata["original_final_evidence_commit"],
        )
    run(
        repo,
        "worktree",
        "add",
        "--detach",
        str(worktree),
        metadata["original_final_evidence_commit"],
    )
    print(
        json.dumps(
            {
                "evidence_worktree": str(worktree),
                "exact_commit": metadata["original_final_evidence_commit"],
            }
        )
    )


if __name__ == "__main__":
    main()
