use pretty_assertions::assert_eq;

use super::*;

#[test]
fn sdk_metadata_is_dropped_instead_of_retained_outside_raw_bounds() {
    let mut baseline = GapFillAccumulator::new(plan()).expect("plan");
    append(
        &mut baseline,
        page(
            "s-source",
            Some("t-target"),
            vec![event("$visible")],
            vec![],
        ),
    )
    .expect("baseline page");
    let mut enriched = page(
        "s-source",
        Some("t-target"),
        vec![event("$visible")],
        vec![],
    );
    let mut large = event("$bundled");
    large["content"]["body"] = json!("x".repeat(MAX_BYTES + 1));
    let bundled = page("unused", /*end*/ None, vec![large], vec![])
        .chunk
        .pop()
        .expect("bundle");
    assert!(bundled.raw().json().get().len() > MAX_BYTES);
    // SDK 0.19 derives the latest thread event from the raw unsigned relations.
    // Push actions remain SDK metadata outside raw(), so attach an oversized
    // value there to preserve the accepted-page retention boundary exercised here.
    enriched.chunk[0].set_push_actions(vec![
        serde_json::from_value(json!({
            "set_tweak": "sound",
            "value": bundled.raw().json().get(),
        }))
        .expect("SDK push action"),
    ]);
    assert!(
        serde_json::to_vec(enriched.chunk[0].push_actions().expect("SDK metadata"))
            .expect("metadata JSON")
            .len()
            > MAX_BYTES
    );
    let mut accumulator = GapFillAccumulator::new(plan()).expect("plan");
    assert_eq!(
        append(&mut accumulator, enriched),
        Ok(GapFillStatus::ReachedTarget)
    );
    assert_eq!(snapshot(&accumulator), snapshot(&baseline));
    assert_eq!(
        accumulator.pages[0].chunk[0].json().get().len(),
        accumulator.observation.event_bytes
    );
}
