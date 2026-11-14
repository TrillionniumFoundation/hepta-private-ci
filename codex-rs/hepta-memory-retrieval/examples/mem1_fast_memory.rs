//! Bounded, local MEM-1 qualification driver. No fact or adoption authority.
//! The Python owner harness supplies validated training support and current cut.

use std::error::Error;
use std::io::BufRead;
use std::io::Read;
use std::io::Write;
use std::io::{self};

use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_memory_retrieval::FastMemoryConfigV1;
use codex_hepta_memory_retrieval::FastMemoryV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

fn id(value: &str) -> Result<StableId, Box<dyn Error>> {
    Ok(StableId::new(value)?)
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn snapshot(scope: &str, generation: u64) -> Result<CognitiveSnapshotKeyV1, Box<dyn Error>> {
    Ok(CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: id(scope)?,
        purpose_id: id("purpose:mem1-association")?,
        memory_ledger_frontier: generation,
        knowledge_fact_frontier: generation,
        tombstone_frontier: generation,
        source_ledger_frontier: generation,
        knowledge_graph_generation: Generation::new(generation)?,
        compact_checkpoint_generation: Generation::new(generation)?,
        prompt_registry_revision: Revision::new(1)?,
        retrieval_profile_digest: digest("mem1-fixed-profile-v1"),
        encoder_preprocessor_digest: digest("mem1-fixed-features-v1"),
        authority_epoch: generation,
        model_digest: digest("mem1-frozen-base-and-no-adapter-v1"),
        tokenizer_digest: digest("mem1-symbols-v1"),
        template_digest: digest("mem1-paired-symbols-v1"),
        tool_schema_digest: digest("mem1-stdin-v1"),
    })?)
}

fn vector(value: &str) -> Result<Vec<f64>, Box<dyn Error>> {
    let values = value
        .split(',')
        .map(str::parse)
        .collect::<Result<Vec<_>, _>>()?;
    if values.len() > 64 {
        return Err("vector exceeds 64 values".into());
    }
    Ok(values)
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn unhex(value: &str) -> Result<Vec<u8>, Box<dyn Error>> {
    if !value.len().is_multiple_of(2) || !value.is_ascii() || value.len() > 65_760 {
        return Err("invalid hex length".into());
    }
    (0..value.len())
        .step_by(2)
        .map(|offset| Ok(u8::from_str_radix(&value[offset..offset + 2], 16)?))
        .collect()
}

#[derive(Default)]
struct Driver {
    memory: Option<FastMemoryV1>,
    config: Option<FastMemoryConfigV1>,
    scope: String,
    generation: u64,
}

impl Driver {
    fn command(&mut self, line: &str) -> Result<String, Box<dyn Error>> {
        let fields = line.split_whitespace().collect::<Vec<_>>();
        match fields.as_slice() {
            [
                "new",
                state,
                scope,
                generation,
                key_width,
                value_width,
                eta,
                decay,
            ] => {
                let config = FastMemoryConfigV1 {
                    owner_id: id("owner:mem1-reference")?,
                    state_id: id(state)?,
                    base_model_digest: digest("mem1-frozen-base-v1"),
                    adapter_digest: digest("mem1-no-selected-adapter-v1"),
                    key_width: key_width.parse()?,
                    value_width: value_width.parse()?,
                    learning_rate: eta.parse()?,
                    decay: decay.parse()?,
                };
                let generation = generation.parse()?;
                let memory = FastMemoryV1::new(config.clone(), snapshot(scope, generation)?)?;
                self.scope = (*scope).to_string();
                self.generation = generation;
                self.memory = Some(memory);
                self.config = Some(config);
            }
            ["predict", generation, key] => {
                let memory = self.memory.as_ref().ok_or("new required")?;
                let result =
                    memory.predict(&snapshot(&self.scope, generation.parse()?)?, &vector(key)?)?;
                let values = result
                    .values
                    .iter()
                    .map(ToString::to_string)
                    .collect::<Vec<_>>()
                    .join(",");
                return Ok(format!(
                    "P\t{}\t{}\t{values}",
                    hex(result.state_digest.as_array()),
                    result.scalar_multiplications
                ));
            }
            ["update", generation, support, key, target] => {
                let memory = self.memory.as_mut().ok_or("new required")?;
                let result = memory.update(
                    &snapshot(&self.scope, generation.parse()?)?,
                    memory.state_digest(),
                    &vector(key)?,
                    &vector(target)?,
                    support.parse::<Digest32>()?,
                )?;
                return Ok(format!(
                    "U\t{}\t{}\t{}\t{:.17}",
                    hex(result.after.as_array()),
                    result.scalar_multiplications,
                    result.sequence,
                    result.squared_error
                ));
            }
            ["checkpoint"] => {
                let memory = self.memory.as_ref().ok_or("new required")?;
                return Ok(format!(
                    "C\t{}\t{}",
                    hex(memory.state_digest().as_array()),
                    hex(&memory.checkpoint())
                ));
            }
            ["restore", anchor, bytes] => {
                let anchor =
                    Digest32::from_array(unhex(anchor)?.try_into().map_err(|_| "anchor width")?);
                self.memory = Some(FastMemoryV1::restore(
                    self.config.clone().ok_or("new required")?,
                    snapshot(&self.scope, self.generation)?,
                    &unhex(bytes)?,
                    anchor,
                )?);
            }
            ["reset", state, generation] => {
                let generation = generation.parse()?;
                let state = id(state)?;
                self.memory = Some(
                    self.memory
                        .as_ref()
                        .ok_or("new required")?
                        .reset(snapshot(&self.scope, generation)?, state.clone())?,
                );
                self.generation = generation;
                self.config.as_mut().ok_or("new required")?.state_id = state;
            }
            _ => return Err("unknown MEM-1 command".into()),
        }
        let memory = self.memory.as_ref().ok_or("new required")?;
        Ok(format!(
            "OK\t{}\t{}",
            hex(memory.state_digest().as_array()),
            memory.checkpoint().len()
        ))
    }
}

fn main() -> Result<(), Box<dyn Error>> {
    let mut driver = Driver::default();
    let stdin = io::stdin();
    let mut reader = stdin.lock();
    let mut stdout = io::stdout().lock();
    loop {
        // Bound allocation before consuming a local protocol command.
        let mut bytes = Vec::new();
        let count = reader.by_ref().take(70_001).read_until(b'\n', &mut bytes)?;
        if count == 0 {
            break;
        }
        if count > 70_000 || !bytes.ends_with(b"\n") {
            return Err("input limit".into());
        }
        let line = std::str::from_utf8(&bytes)?.trim();
        if line == "quit" {
            break;
        }
        match driver.command(line) {
            Ok(reply) => writeln!(stdout, "{reply}")?,
            Err(error) => writeln!(stdout, "ERR\t{error}")?,
        }
        stdout.flush()?;
    }
    Ok(())
}
