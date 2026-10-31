//! Explicit typed maps for two different resident heads; no cross-head reuse.
use codex_hepta_types::StableId;
use serde_json::Value;

#[derive(Clone,Copy)]
pub enum HeadKind {Current,Future}
pub struct Geometry {
    pub layer:StableId,
    pub parameters:Vec<StableId>,
    pub span:&'static str,
    pub norm:u128,
    pub mapping:&'static str,
}

pub fn from_weights(bytes:&[u8],kind:HeadKind)->Result<Geometry,Box<dyn std::error::Error>> {
    let weights:Value=serde_json::from_slice(bytes)?;
    let (row,bias,width,layer,span,mapping)=match kind {
        HeadKind::Current=>(serde_json::from_value::<Vec<f64>>(weights["w2"].clone())?,
            weights["b2"].as_f64().ok_or("Current bias shape")?,32,"correctness.output-weight","w2.0..31",
            "32 explicit diagonal mappings from sparse eligibility to learned w2 parameters; local three-factor update, not a generator backpropagation gradient"),
        HeadKind::Future=>{
            let matrix:Vec<Vec<f64>>=serde_json::from_value(weights["w2"].clone())?;
            let bias:Vec<f64>=serde_json::from_value(weights["b2"].clone())?;
            if matrix.len()!=33 || matrix.iter().any(|r|r.len()!=64) || bias.len()!=33 {
                return Err("Future output-head shape changed".into());
            }
            (matrix[32].clone(),bias[32],33,"future-correctness.output-row32","w2.32.0..32",
                "33 explicit diagonal eligibility mappings to first33 of64 weights in future-correctness output row32; latent forecast rows0..31 unchanged; local bounded rule, not a gradient or optimality claim")
        }
    };
    if row.len()!=match kind {HeadKind::Current=>32,HeadKind::Future=>64}
        || row.iter().chain(std::iter::once(&bias)).any(|v|!v.is_finite()||v.abs()>100.0) {
        return Err("Invalid actual parameter geometry".into());
    }
    let norm=row.iter().chain(std::iter::once(&bias)).map(|v| {
        let q=(*v*(1_u64<<32) as f64).round() as i64;u128::from(q.unsigned_abs()).pow(2)
    }).sum();
    let parameters=(0..width).map(|i|StableId::new(match kind {
        HeadKind::Current=>format!("w2.{i}"),HeadKind::Future=>format!("w2.32.{i}"),
    })).collect::<Result<Vec<_>,_>>()?;
    Ok(Geometry {layer:StableId::new(layer)?,parameters,span,norm,mapping})
}
