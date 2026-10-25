"""Produce an exact-base Agentd patch without changing the checked-out core."""

import argparse
import difflib
import hashlib
from pathlib import Path

TARGET_COMMIT = "f8c9419df6ddeb36ff8b522a50219981fb8d9345"
TARGET_BLOB = "f44c8858a55886c7997562a02ba87b9a7d359bf2"
TARGET_PATH = "codex-rs/hepta-agentd/src/plasticity_process_bootstrap.rs"


def git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def prepare(source, output):
    raw = source.read_bytes()
    if git_blob(raw) != TARGET_BLOB:
        # The text-fetch cache added one trailing newline. Accept that exact
        # transport artifact only when removing it recovers the pinned Git blob.
        if raw.endswith(b"\n") and git_blob(raw[:-1]) == TARGET_BLOB:
            raw = raw[:-1]
        else:
            raise ValueError("Bootstrap base is not the exact target Git blob")
    original = raw.decode()
    updated = original

    def replace(before, after):
        nonlocal updated
        if updated.count(before) != 1:
            raise ValueError("Target source context is not unique: " + before[:80])
        updated = updated.replace(before, after)

    replace("use codex_hepta_neuron::SparseJournal;\n", "")
    replace('const DESCRIPTOR_SCHEMA: &str = "hepta.agentd.plasticity-bootstrap.v1";', '''#[path = "neuron_chain_recovery.rs"]
mod neuron_chain_recovery;
use neuron_chain_recovery::{
    NeuronSegmentDescriptorV1, recover_neuron_chain_v1, select_neuron_segments_v1,
};

const DESCRIPTOR_SCHEMA: &str = "hepta.agentd.plasticity-bootstrap.v1";''')
    replace('''struct NeuronDescriptorV1 {
    journal_path: PathBuf,
    owner_id: String,
    scope_digest: String,
    objective_digest: String,
    max_records: usize,''', '''struct NeuronDescriptorV1 {
    journal_path: Option<PathBuf>,
    #[serde(default)]
    segment_chain: Option<Vec<NeuronSegmentDescriptorV1>>,
    owner_id: String,
    scope_digest: String,
    objective_digest: String,
    max_records: Option<usize>,''')
    replace('''    validate_process_path_separation(&descriptor)?;''', '''    let neuron_segments = select_neuron_segments_v1(
        descriptor.neuron.journal_path.as_deref(),
        descriptor.neuron.max_records,
        descriptor.neuron.segment_chain.as_deref(),
    )
    .map_err(|error| AgentdError::Invalid(format!("invalid neuron source: {error}")))?;
    validate_process_path_separation(&descriptor, &neuron_segments)?;''')
    replace('''    let neuron_file = open_existing_rw(&descriptor.neuron.journal_path, "neuron journal")?;
    let neuron_journal = SparseJournal::open_anchored(
        neuron_file,''', '''    let neuron_journal = recover_neuron_chain_v1(
        &neuron_segments,''')
    replace('''        descriptor.neuron.max_records,
        neuron_anchor,''', '''        neuron_anchor,''')
    replace('''fn validate_process_path_separation(
    descriptor: &ProcessBootstrapDescriptorV1,
) -> Result<(), AgentdError> {
    let paths = [
        descriptor.ledger.path.as_path(),
        descriptor.neuron.journal_path.as_path(),''', '''fn validate_process_path_separation(
    descriptor: &ProcessBootstrapDescriptorV1,
    neuron_segments: &[NeuronSegmentDescriptorV1],
) -> Result<(), AgentdError> {
    let mut paths = vec![
        descriptor.ledger.path.as_path(),''')
    replace('''        descriptor.topology_registry.anchor_path.as_path(),
    ];
    for (index, left)''', '''        descriptor.topology_registry.anchor_path.as_path(),
    ];
    paths.extend(neuron_segments.iter().map(|segment| segment.journal_path.as_path()));
    for (index, left)''')
    helper = Path(__file__).with_name("neuron_chain_recovery.rs").read_text()
    patch = "".join(difflib.unified_diff(original.splitlines(keepends=True), updated.splitlines(keepends=True),
                                        fromfile="a/" + TARGET_PATH, tofile="b/" + TARGET_PATH))
    patch += "".join(difflib.unified_diff([], helper.splitlines(keepends=True), fromfile="/dev/null",
        tofile="b/codex-rs/hepta-agentd/src/neuron_chain_recovery.rs"))
    output.write_text(patch)
    print(f"target={TARGET_COMMIT} blob={TARGET_BLOB} patch={output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.source, args.output)
