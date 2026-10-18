//! Thin compatibility for the exact original inline request representation.
use super::wire::*;
use super::*;
pub(super) fn write(p: &ParameterGeneratorProfileV3, w: &mut Writer) -> Result<()> {
    w.put(
        &codex_hepta_plasticity::encode_parameter_generator_profile_body_v3(p)
            .map_err(|_| invalid())?,
    )
}
pub(super) fn read(r: &mut Reader<'_>) -> Result<ParameterGeneratorProfileV3> {
    let (p, n) = codex_hepta_plasticity::decode_parameter_generator_profile_body_prefix_v3(
        r.remaining_bytes(),
    )
    .map_err(|_| invalid())?;
    r.take(n)?;
    Ok(p)
}
