//! Retain the physically verified immutable model material without rehashing the
//! 274 MiB encoder for every Goal. These read handles grant no use authority.
use crate::OperationalModelLeaseBindingV2;
use crate::initial_neuron_operational_source::HostResult;
use crate::initial_neuron_operational_source::Source;
use crate::operational_model_lease_gguf_v2::tokenizer_digest;
use codex_hepta_learning_ledger::open_root_review_input;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde_json::Value;
use std::collections::BTreeSet;
use std::fs::File;
use std::fs::Metadata;
use std::io::Read;
use std::io::Seek;
use std::os::unix::fs::MetadataExt;

type Identity = (u64, u64, u32, u32, u32, u64, u64, i64, i64, i64, i64);
fn identity(m: &Metadata) -> Identity {
    (
        m.dev(),
        m.ino(),
        m.uid(),
        m.gid(),
        m.mode(),
        m.nlink(),
        m.len(),
        m.mtime(),
        m.mtime_nsec(),
        m.ctime(),
        m.ctime_nsec(),
    )
}
struct VerifiedFile {
    source: Source,
    file: File,
    original: Identity,
}
impl VerifiedFile {
    fn open(source: &Source, maximum: u64) -> HostResult<Self> {
        let expected: Digest32 = source.digest.parse()?;
        if expected.is_zero() {
            return Err("empty operational material pin".into());
        }
        let mut file = open_root_review_input(&source.path)?;
        let original = identity(&file.metadata()?);
        if original.6 > maximum || Digest32::of_reader(&mut file, maximum)? != expected {
            return Err("original operational material SHA/size".into());
        }
        file.rewind()?;
        let verified = Self {
            source: source.clone(),
            file,
            original,
        };
        verified.current(source)?;
        Ok(verified)
    }
    fn current(&self, source: &Source) -> HostResult<()> {
        if source.path != self.source.path
            || source.digest != self.source.digest
            || identity(&self.file.metadata()?) != self.original
            || identity(&open_root_review_input(&source.path)?.metadata()?) != self.original
        {
            return Err("original immutable model material changed at final use".into());
        }
        Ok(())
    }
    fn read(&mut self, maximum: u64) -> HostResult<Vec<u8>> {
        if self.original.6 > maximum {
            return Err("bounded model material JSON".into());
        }
        self.file.rewind()?;
        let mut bytes = Vec::new();
        (&mut self.file).take(maximum + 1).read_to_end(&mut bytes)?;
        self.current(&self.source)?;
        if bytes.len() as u64 > maximum {
            return Err("model material grew during read".into());
        }
        Ok(bytes)
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct MaterialSources {
    pub normalization: Source,
    pub encoder_manifest: Source,
    pub encoder_gguf: Source,
    pub training_code: Source,
    pub body_implementation: Source,
}
impl MaterialSources {
    pub(super) fn validate_pins(&self, binding: &OperationalModelLeaseBindingV2) -> HostResult<()> {
        for (source, pin) in [
            (&self.normalization, binding.normalization_digest),
            (&self.encoder_manifest, binding.encoder_manifest_digest),
            (&self.training_code, binding.training_code_digest),
            (
                &self.body_implementation,
                binding.body_implementation_digest,
            ),
        ] {
            if source.digest.parse::<Digest32>()? != pin {
                return Err("operational material differs from model binding".into());
            }
        }
        if self.encoder_gguf.digest.parse::<Digest32>()?.is_zero() {
            return Err("original physical encoder SHA".into());
        }
        Ok(())
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ImplementationClosure {
    schema: String,
    worker_host: Source,
    fixed_encoder_program: Source,
    encoder_runtime: Source,
    encoder_helper_sources: Vec<Source>,
    numpy_sources: Vec<Source>,
}
impl ImplementationClosure {
    fn sources(&self) -> HostResult<Vec<&Source>> {
        if self.schema != "hepta.cpu-neuron.implementation-closure.v2"
            || !(1..=32).contains(&self.encoder_helper_sources.len())
            || !(1..=4096).contains(&self.numpy_sources.len())
        {
            return Err("bounded immutable CPU implementation closure".into());
        }
        let sources = [
            &self.worker_host,
            &self.fixed_encoder_program,
            &self.encoder_runtime,
        ]
        .into_iter()
        .chain(&self.encoder_helper_sources)
        .chain(&self.numpy_sources)
        .collect::<Vec<_>>();
        let mut unique = BTreeSet::new();
        if sources.iter().any(|s| !unique.insert(s.path.clone())) {
            return Err("duplicate implementation closure source path".into());
        }
        Ok(sources)
    }
}
pub(super) struct VerifiedMaterial {
    files: [VerifiedFile; 5],
    implementation: Vec<VerifiedFile>,
}
impl VerifiedMaterial {
    pub(super) fn inspect(
        sources: &MaterialSources,
        binding: &OperationalModelLeaseBindingV2,
    ) -> HostResult<Self> {
        sources.validate_pins(binding)?;
        let mut normalization = VerifiedFile::open(&sources.normalization, 16 * 1024)?;
        let mut manifest = VerifiedFile::open(&sources.encoder_manifest, 64 * 1024)?;
        let mut gguf = VerifiedFile::open(&sources.encoder_gguf, 1024 * 1024 * 1024)?;
        let training = VerifiedFile::open(&sources.training_code, 16 * 1024 * 1024)?;
        let mut body = VerifiedFile::open(&sources.body_implementation, 1024 * 1024)?;
        let closure: ImplementationClosure = serde_json::from_slice(&body.read(1024 * 1024)?)?;
        let mut implementation = Vec::new();
        let mut total_bytes = 0_u64;
        for source in closure.sources()? {
            let file = VerifiedFile::open(source, 1024 * 1024 * 1024)?;
            total_bytes = total_bytes
                .checked_add(file.original.6)
                .ok_or("closure byte count overflow")?;
            if total_bytes > 2 * 1024 * 1024 * 1024 {
                return Err("CPU implementation closure total byte budget".into());
            }
            implementation.push(file);
        }
        let normalization_json: Value = serde_json::from_slice(&normalization.read(16 * 1024)?)?;
        let manifest_json: Value = serde_json::from_slice(&manifest.read(64 * 1024)?)?;
        let tokenizer = tokenizer_digest(&mut gguf.file)?;
        let layers = manifest_json["layers"]
            .as_array()
            .ok_or("physical encoder manifest layers")?;
        let weights = layers
            .iter()
            .filter(|v| v["mediaType"] == "application/vnd.ollama.image.model")
            .collect::<Vec<_>>();
        if weights.len() != 1
            || weights[0]["digest"] != format!("sha256:{}", sources.encoder_gguf.digest)
            || weights[0]["size"].as_u64() != Some(gguf.original.6)
            || normalization_json["weights_sha256"] != sources.encoder_gguf.digest
            || normalization_json["tokenizer_sha256"] != tokenizer.to_string()
            || tokenizer != binding.tokenizer_digest
        {
            return Err("physical encoder/tokenizer/normalization provenance differs".into());
        }
        gguf.current(&sources.encoder_gguf)?;
        let result = Self {
            files: [normalization, manifest, gguf, training, body],
            implementation,
        };
        result.revalidate(sources, binding)?;
        Ok(result)
    }
    pub(super) fn revalidate(
        &self,
        sources: &MaterialSources,
        binding: &OperationalModelLeaseBindingV2,
    ) -> HostResult<()> {
        sources.validate_pins(binding)?;
        for (file, source) in self.files.iter().zip([
            &sources.normalization,
            &sources.encoder_manifest,
            &sources.encoder_gguf,
            &sources.training_code,
            &sources.body_implementation,
        ]) {
            file.current(source)?;
        }
        for file in &self.implementation {
            file.current(&file.source)?;
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "operational_model_lease_material_v2_tests.rs"]
mod tests;
