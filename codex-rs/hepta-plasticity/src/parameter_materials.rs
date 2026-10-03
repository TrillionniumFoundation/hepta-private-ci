//! Bounded complete raw profile/admission transport. Decoding grants no authority.
use crate::parameter_material_wire::*;
use crate::*;
use codex_hepta_types::Generation;
pub const MAX_PARAMETER_ROLE_MATERIAL_BYTES_V1: usize = MAX;
const PROFILE: &[u8] = b"HPTPGP03";
const ADMISSION: &[u8] = b"HPTPAD01";

pub fn encode_untrusted_parameter_generator_profile_v3(
    p: &ParameterGeneratorProfileV3,
) -> Result<Vec<u8>> {
    generate_parameter_candidates_v3(p.clone()).map_err(|_| invalid())?;
    let mut w = Writer(PROFILE.to_vec());
    crate::parameter_profile_wire_v3::write(p, &mut w)?;
    w.finish()
}
pub fn decode_untrusted_parameter_generator_profile_v3(
    bytes: &[u8],
) -> Result<ParameterGeneratorProfileV3> {
    let mut r = Reader::new(bytes, PROFILE)?;
    let p = crate::parameter_profile_wire_v3::read(&mut r)?;
    r.finish()?;
    if encode_untrusted_parameter_generator_profile_v3(&p)? != bytes {
        return Err(invalid());
    }
    Ok(p)
}
pub fn encode_untrusted_plasticity_admission_v1(
    a: &PlasticityAdmissionEvidenceV1,
) -> Result<Vec<u8>> {
    let mut w = Writer(ADMISSION.to_vec());
    write_admission(a, &mut w)?;
    w.finish()
}
pub fn decode_untrusted_plasticity_admission_v1(
    bytes: &[u8],
) -> Result<PlasticityAdmissionEvidenceV1> {
    let mut r = Reader::new(bytes, ADMISSION)?;
    let a = read_admission(&mut r)?;
    r.finish()?;
    if encode_untrusted_plasticity_admission_v1(&a)? != bytes {
        return Err(invalid());
    }
    Ok(a)
}
/// Original inline request representation; no magic/checksum or authentication.
#[doc(hidden)]
pub fn encode_parameter_generator_profile_body_v3(
    p: &ParameterGeneratorProfileV3,
) -> Result<Vec<u8>> {
    let mut w = Writer(Vec::new());
    crate::parameter_profile_wire_v3::write(p, &mut w)?;
    Ok(w.0)
}
#[doc(hidden)]
pub fn decode_parameter_generator_profile_body_prefix_v3(
    bytes: &[u8],
) -> Result<(ParameterGeneratorProfileV3, usize)> {
    let mut r = Reader::raw(bytes)?;
    let p = crate::parameter_profile_wire_v3::read(&mut r)?;
    Ok((p, bytes.len() - r.remaining()))
}
#[doc(hidden)]
pub fn encode_plasticity_admission_body_v1(a: &PlasticityAdmissionEvidenceV1) -> Result<Vec<u8>> {
    let mut w = Writer(Vec::new());
    write_admission(a, &mut w)?;
    Ok(w.0)
}
#[doc(hidden)]
pub fn decode_plasticity_admission_body_prefix_v1(
    bytes: &[u8],
) -> Result<(PlasticityAdmissionEvidenceV1, usize)> {
    let mut r = Reader::raw(bytes)?;
    let a = read_admission(&mut r)?;
    Ok((a, bytes.len() - r.remaining()))
}
pub(super) fn write_admission(a: &PlasticityAdmissionEvidenceV1, w: &mut Writer) -> Result<()> {
    w.id(&a.baseline_id)?;
    for d in [
        a.objective_digest,
        a.selected_artifact_digest,
        a.artifact_registry_binding,
        a.artifact_registry_head_digest,
        a.qualification_evidence_head_digest,
        a.owner_evidence_set_digest,
    ] {
        w.digest(d)?;
    }
    w.window(&a.window)?;
    w.u64(a.baseline_generation.get())?;
    w.u64(a.candidate_generation.get())?;
    for d in [
        a.dataset_digest,
        a.update_rule_digest,
        a.modulator_digest,
        a.modulator_broadcast_digest,
        a.eligibility_digest,
        a.generator_digest,
    ] {
        w.digest(d)?;
    }
    Ok(())
}
pub(super) fn read_admission(r: &mut Reader<'_>) -> Result<PlasticityAdmissionEvidenceV1> {
    Ok(PlasticityAdmissionEvidenceV1 {
        baseline_id: r.id()?,
        objective_digest: r.digest()?,
        selected_artifact_digest: r.digest()?,
        artifact_registry_binding: r.digest()?,
        artifact_registry_head_digest: r.digest()?,
        qualification_evidence_head_digest: r.digest()?,
        owner_evidence_set_digest: r.digest()?,
        window: r.window()?,
        baseline_generation: Generation::new(r.u64()?).map_err(|_| invalid())?,
        candidate_generation: Generation::new(r.u64()?).map_err(|_| invalid())?,
        dataset_digest: r.digest()?,
        update_rule_digest: r.digest()?,
        modulator_digest: r.digest()?,
        modulator_broadcast_digest: r.digest()?,
        eligibility_digest: r.digest()?,
        generator_digest: r.digest()?,
    })
}
