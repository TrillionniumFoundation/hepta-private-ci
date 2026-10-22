"""Seal bounded diagnostic evidence; never snapshot known/uncertain active writer trees."""
import json
import os
from pathlib import Path

from a32_sshsig_guard import LOCKS, digest, git, inventory, require, save


def nested_child_uncertainty(evidence):
    issues = []
    for path in sorted(evidence.glob('*.no-kill.jsonl')):
        pending = None
        try:
            require(path.is_file() and not path.is_symlink(), 'nonregular adapter journal')
            for line in path.read_text().splitlines():
                event = json.loads(line).get('event')
                if event in ('native-admitted', 'version-query-admitted'):
                    require(pending is None, 'overlapping nested admission')
                    pending = event
                elif event in ('native-finished', 'version-query-finished'):
                    expected = 'native-admitted' if event == 'native-finished' else 'version-query-admitted'
                    require(pending == expected, 'nested terminal without matching admission')
                    pending = None
            if pending is not None:
                issues.append({'journal': path.name, 'unmatched_admission': pending})
        except (OSError, ValueError, RuntimeError) as error:
            issues.append({'journal': path.name, 'uncertain_journal': repr(error)})
    return issues


def external_formatter_prefixes(evidence, state):
    receipt_path = evidence / 'format-discovery/receipt.json'
    if not receipt_path.exists():
        return []
    try:
        receipt = json.loads(receipt_path.read_bytes())
        live = Path(receipt['live_logs_not_uploaded'])
        require(live.parent == evidence.parent and live.name.startswith('a32-format-live-')
                and not live.is_symlink() and live.resolve().parent == evidence.parent, 'untrusted live formatter path')
        return [(live / (name + '.log'), Path('format-discovery-live') / (name + '.log'))
                for name in ('rustfmt-version', 'input-format-check', 'generate-format-only', 'generated-format-check')
                if (live / (name + '.log')).exists()]
    except (OSError, KeyError, ValueError, RuntimeError) as error:
        state['external_formatter_prefix_gap'] = repr(error)
        return []


def collect(self):
    uncertainty = nested_child_uncertainty(self.evidence)
    if uncertainty:
        self.state['nested_child_uncertainty'] = uncertainty
        self.state['active_child_latch'] = True
    if not self.state.get("input_verified") or self.state.get("active_child_latch") or self.state.get("format_writer_may_be_active") or any("exit_code" not in x for x in self.commands):
        sealed = self.evidence.with_name(self.evidence.name + "-sealed")
        require(not sealed.exists(), "partial evidence destination already exists")
        sealed.mkdir(parents=True)
        prefixes = []
        # Only diagnostic logs/journals and receipts; never live source, locks, or native test artifacts.
        sources = [*self.evidence.glob("logs/*"), *self.evidence.glob("journal/*"),
                   *self.evidence.glob("*.no-kill.jsonl"), *self.evidence.glob("*-failure.json"),
                   *self.evidence.glob("*-counts.json"), *self.evidence.glob("token.json"),
                   *self.evidence.glob("source.json"), *self.evidence.glob("commands.json"),
                   *self.evidence.glob("format-discovery/*.log"), *self.evidence.glob("format-discovery/receipt.json")]
        for family, lanes in (("acquisition-controls", ("positive", "unchecked-create", "path-check-open")),
                              ("recovery-controls", ("positive", "shared-source", "skip-snapshot"))):
            sources.extend(path for path in [*(self.evidence / family / (lane + ".log") for lane in lanes),
                                              self.evidence / family / "manifest.json"] if path.exists())
        named_sources = [(source, source.relative_to(self.evidence)) for source in sources]
        named_sources += external_formatter_prefixes(self.evidence, self.state)
        for source, relative in sorted(named_sources):
            require(source.is_file() and not source.is_symlink(), "nonregular partial diagnostic receipt")
            before = source.stat().st_size
            with source.open("rb") as stream:
                prefix = stream.read(min(before, 256 * 1024 * 1024))
            target = sealed / "partial-prefixes" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(prefix)
            prefixes.append({"path": target.relative_to(sealed).as_posix(), "bytes": len(prefix),
                             "sha256": digest(prefix), "observed_before_bytes": before,
                             "observed_after_bytes": source.stat().st_size, "complete": False})
        save(sealed / "PARTIAL-NOT-SETTLED.json", {"steps": self.commands,
             "state": self.state, "live_source_and_artifact_tree_not_copied": True,
             "qualification": False, "active_or_unrecorded_child_outcome": True,
             "diagnostic_prefixes_only": prefixes, "settled_inventory_created": False})
        return
    self.evidence.mkdir(parents=True, exist_ok=True)
    for path in LOCKS:
        output = self.evidence / "observed-current-locks" / path
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes((self.root / path).read_bytes())
    for name, args in {"final-status.txt": ("status", "--porcelain", "--untracked-files=all"),
                       "final-diff.patch": ("diff", "--binary", "HEAD"),
                       "final-index-flags.txt": ("ls-files", "-v", "-f"),
                       "final-index.index": ("ls-files", "--stage")}.items():
        (self.evidence / name).write_bytes(git(self.root, *args))
    self.state["steps"] = json.loads(os.environ.get("STEP_RESULTS", "{}"))
    self.state["final_head"] = git(self.root, "rev-parse", "HEAD").decode().strip()
    self.state["final_source_clean"] = False
    for record in self.commands:
        self.state.setdefault("command_plan", {})[record["name"]] = record["status"]
    try:
        self.guard()
        self.state["final_source_clean"] = True
    finally:
        self.flush()
        save(self.evidence / "inventory.json", inventory(self.evidence, ("inventory.json",)))
        seal(self)

def seal(self):
    sealed = self.evidence.with_name(self.evidence.name + "-sealed")
    require(not sealed.exists(), "sealed evidence already exists; never overwrite an attempt")
    sealed.mkdir()
    snapshots = []
    for source in sorted(self.evidence.rglob("*")):
        require(not source.is_symlink(), "evidence symlink forbidden")
        if not source.is_file():
            continue
        length = source.stat().st_size
        require(length <= 256 * 1024 * 1024, "evidence file exceeds bounded snapshot size")
        target = sealed / source.relative_to(self.evidence)
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as incoming, target.open("xb") as outgoing:
            data = incoming.read(length)
            require(len(data) == length, "evidence shrank while snapshotting")
            outgoing.write(data)
        snapshots.append({"path": target.relative_to(sealed).as_posix(), "prefix_bytes": length,
                          "sha256": digest(data), "source_bytes_after": source.stat().st_size})
    save(sealed / "snapshot-receipt.json", {"immutable_prefix_snapshots": snapshots,
         "no_native_result_inferred_from_unfinished_commands": True,
         "incomplete_commands": [x["name"] for x in self.commands if "exit_code" not in x]})
    save(sealed / "sealed-inventory.json", inventory(sealed, ("sealed-inventory.json",)))
