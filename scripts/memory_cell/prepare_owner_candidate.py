"""One-shot source integration, constrained to the reviewed MemoryCell PR.

This script is removed after its generated diff is reviewed and adopted. It never
writes main, installs artifacts, changes branch protection or grants runtime use.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def append_exports(path, marker, declarations):
    file = ROOT / path
    source = file.read_text()
    if marker not in source:
        source += "\n" + declarations + "\n"
        file.write_text(source)


append_exports(
    "codex-rs/hepta-bellman-operator/src/lib.rs",
    "mod memory_training;",
    """mod memory_training;
pub use memory_training::{FrozenMemoryTrainingV1, MemoryTensorCandidateV1, MemoryTrainingError,
    MemoryTrainingObservationV1, MemoryTrainingProfileV1, MemoryTrainingSourceV1,
    finish_memory_training_from_owner_v1, freeze_memory_training_from_owner_v1};""",
)
append_exports(
    "codex-rs/hepta-infer-worker-host/src/lib.rs",
    "mod memory_cell_driver;",
    """mod memory_cell_driver;
pub use memory_cell_driver::{MemoryCellBindingV1, MemoryCellDriver};""",
)
append_exports(
    "codex-rs/hepta-agentd/src/lib.rs",
    "mod shared_memory_training;",
    """mod shared_memory_training;
mod memory_trainer_process;
pub use shared_memory_training::{SharedMemoryTrainingError, SharedMemoryTrainingV1,
    SharedMemoryTensorCandidateV1, SharedMemoryTensorModelV1};
pub use memory_trainer_process::{MemoryTrainerProcessV1, MemoryTrainerProcessConfigV1};""",
)
append_exports(
    "codex-rs/hepta-agentd/tests/terminal_cell_owner.rs",
    "mod memory_training_cases;",
    """#[path = "support/memory_training_cases.rs"]
mod memory_training_cases;""",
)
p = ROOT / "codex-rs/hepta-agentd/src/shared_terminal_cell.rs"
s = p.read_text()
for field in (
    "source: Arc<CognitiveStore>",
    "consumer: FederationConsumerAccess",
    "purpose: SharedExperiencePurposeV1",
):
    s = s.replace("    " + field + ",\n", "    pub(super) " + field + ",\n")
p.write_text(s)
p = ROOT / "codex-rs/hepta-agentd/src/shared_memory_training.rs"
s = p.read_text()
s = s.replace(
    ".read_shared_experience(policy_id, &self.consumer, &self.purpose)",
    ".read_shared_experience(&self.consumer, policy_id, &self.purpose)",
)
s = s.replace("self.revalidate(", "self.revalidate_memory_source(")
s = s.replace(
    "current: &VerifiedCurrentRegistryViewV1", "current: VerifiedCurrentRegistryViewV1"
)
s = s.replace(
    "let manifest = &loaded.manifest;", "let manifest = &loaded.spec().manifest;"
)
s = s.replace(
    "loaded.payload != candidate.payload", "loaded.bytes() != candidate.payload"
)
s = s.replace(
    "pinned.with_current(current, now, |_| ())", "pinned.with_current(current, |_| ())"
)
s = s.replace(
    "model.pinned.with_current(current, now, |loaded| consume(&loaded.payload))",
    "model.pinned.with_current(current, consume)",
)
if "async fn revalidate_memory_source" not in s:
    s = s.replace(
        "impl AgentdSharedReplayHostV1 {",
        """impl AgentdSharedReplayHostV1 {
    async fn revalidate_memory_source(
        &self, source: &SharedExperienceUseV1, ledger: &LedgerWriter,
        dataset: &DatasetSnapshotReceiptV3, now: u64,
    ) -> Result<(), SharedMemoryTrainingError> {
        let current = self.source.read_shared_experience(&self.consumer, source.policy_id(), &self.purpose)
            .await.map_err(SharedTerminalCellError::Source)?;
        if &current != source { return Err(SharedMemoryTrainingError::Invalid("source use changed")); }
        ledger.revalidate_dataset_snapshot(dataset, now).map_err(SharedTerminalCellError::Ledger)?;
        Ok(())
    }
""",
    )
p.write_text(s)
p = ROOT / "codex-rs/hepta-agentd/src/memory_trainer_process.rs"
s = p.read_text().replace('"requirements.txt"]', '"requirements.txt", "sessions.py"]')
p.write_text(s)
p = ROOT / "scripts/memory_cell/native.py"
s = p.read_text()
if "from sessions import normalize_sessions" not in s:
    s = s.replace(
        "from typing import Any",
        "from typing import Any\nfrom sessions import normalize_sessions",
    )
    s = s.replace(
        "    families: dict[str, str]\n",
        "    families: dict[str, str]\n    ingress_issues: tuple[dict, ...] = ()\n",
    )
    s = s.replace(
        "    for sample in data:\n",
        "    ingress_issues = []\n    for sample in data:\n",
    )
    old = """            if not len(sessions) == len(ids) == len(dates) or len(ids) > 10_000 or len(set(ids)) != len(ids):
                raise ValueError("misaligned/duplicate sessions")
            known = set()
            for sid, date, turns in zip(ids, dates, sessions, strict=True):"""
    new = """            normalized, duplicates = normalize_sessions(sessions, ids, dates)
            ingress_issues.extend({"question_id": qid, **row} for row in duplicates)
            known = set()
            for turns, sid, date in normalized:"""
    if old not in s:
        raise ValueError("native source drift; inspect instead of guessing")
    s = s.replace(old, new).replace(
        "tuple(queries), targets, families)",
        "tuple(queries), targets, families, tuple(ingress_issues))",
    )
p.write_text(s)
p = ROOT / "scripts/memory_cell/composition.py"
s = p.read_text()
if '"output_profile"' not in s:
    s = s.replace(
        '"dimension": model.semantic.in_features,',
        '"output_profile": "relevance-state-five-v1", "dimension": model.semantic.in_features,',
    )
p.write_text(s)
p = ROOT / "scripts/memory_cell/run_native.py"
s = p.read_text()
if "export_native" not in s:
    s = s.replace(
        "from composition import fit", "from composition import export_native, fit"
    )
    s = s.replace(
        '"source-family-sha256-v1"', '"source-family-ranked-sha256-60-20-20-v2"'
    )
    s = s.replace(
        "    # LongMemEval is an external",
        '    (output / "ingress-issues.json").write_text(json.dumps(benchmark.ingress_issues, indent=2))\n    # LongMemEval is an external',
    )
    s = s.replace(
        "    composition_report = {}",
        """    if "joint" in arms:
        export_native(arms["joint"][0], output / "native-export", encoder.identity, cut,
                      digest({"purpose": "qualification-memory-circuit", "families": benchmark.families}), features)
    composition_report = {}""",
    )
    s = s.replace(
        '"all_results_reported": True,',
        '"all_results_reported": True, "evaluation_use": "exploratory-development-not-final-holdout",',
    )
p.write_text(s)
