//! Recover the actual bounded segment chain against its independent witness.
use std::fs::{File,OpenOptions};
use std::path::Path;

use codex_hepta_neuron::*;

pub type Result<T> = std::result::Result<T,Box<dyn std::error::Error>>;
pub const SEGMENT: usize = 128;

pub fn file(path: &Path) -> Result<File> {
    Ok(OpenOptions::new().read(true).write(true).create(true).truncate(false).open(path)?)
}

pub fn recover(root: &Path,native: SparseConfig,scope: JournalScope,
               config: NeuronRuntimeConfigV1,count: usize) -> Result<NeuronRuntime<FileAnchorWitnessStore>> {
    let witness=FileAnchorWitnessStore::open(file(&root.join("neuron.witness"))?,scope,native.generation,4096)?;
    let mut runtime=NeuronRuntime::recover_chain_root(file(&root.join("neuron-0000.journal"))?,
        native,scope,SEGMENT,config,witness)?;
    for index in 1..count.div_ceil(SEGMENT) {
        runtime.recover_next_segment(file(&root.join(format!("neuron-{index:04}.journal")))?,SEGMENT)?;
    }
    Ok(runtime)
}

pub fn journal(root: &Path,native: SparseConfig,scope: JournalScope,anchor: JournalAnchor) -> Result<SparseJournal> {
    let count=anchor.sequence as usize;
    if count<=SEGMENT {
        return Ok(SparseJournal::open_anchored(file(&root.join("neuron-0000.journal"))?,native,scope,SEGMENT,anchor)?);
    }
    let mut current=SparseJournal::open(file(&root.join("neuron-0000.journal"))?,native,scope,SEGMENT)?;
    for index in 1..count.div_ceil(SEGMENT) {
        let path=root.join(format!("neuron-{index:04}.journal"));
        current=if index+1==count.div_ceil(SEGMENT) {current.recover_successor(file(&path)?,SEGMENT,anchor)?}
                else {current.start_successor(file(&path)?,SEGMENT)?};
    }
    if current.current()?.map(SparseCheckpoint::digest)!=Some(anchor.checkpoint_digest) {
        return Err("Recovered segment chain differs from acknowledged final anchor".into());
    }
    Ok(current)
}
