use super::*;
use crate::memory_cell_test_support::request;
use pretty_assertions::assert_eq;

fn query(text: &str) -> MemoryRequestV1 {
    let mut query = request(ContractIdV1::new("owner:time-scope").unwrap());
    query.text = text.to_string();
    query.at = 1_738_368_000;
    query.since = 1_735_689_600;
    query
}

fn view(query: &MemoryRequestV1) -> Result<TimeView, TimeViewError> {
    TimeView::build(
        query,
        &BTreeSet::from([query.entity.clone()]),
        &BTreeMap::new(),
    )
}

#[test]
fn literal_date_uses_a_private_calendar_view_and_preserves_the_native_request() {
    let original = query("Read the saved sample as of 2025-02-01.");
    let selected = view(&original).unwrap();
    assert_eq!((selected.at, selected.since), (20_250_201, 20_250_101));
    selected.verify_original(&original).unwrap();
    assert!(selected.permits(&original, MemoryOperationV1::History));
    assert!(!selected.permits(&original, MemoryOperationV1::Change));
    assert!(!selected.permits(&original, MemoryOperationV1::Current));
    let mut substituted = original.clone();
    substituted.at += 86_400;
    assert!(selected.verify_original(&substituted).is_err());
    let mut non_time = original.clone();
    non_time.text.push(' ');
    assert!(selected.verify_original(&non_time).is_err());
    let mut change = original;
    change.since = change.at;
    assert!(
        view(&change)
            .unwrap()
            .permits(&change, MemoryOperationV1::Change)
    );
    assert_eq!((change.at, change.since), (1_738_368_000, 1_738_368_000));
}

#[test]
fn midnight_is_exact_and_calendar_integer_is_never_guessed_to_be_an_epoch() {
    for cutoff in [1_738_368_001, 1_738_367_999, 20_250_201] {
        let mut original = query("Read the saved sample as of 20250201.");
        original.at = cutoff;
        original.since = 0;
        assert!(
            !view(&original)
                .unwrap()
                .permits(&original, MemoryOperationV1::History)
        );
    }
    let mut no_date = query("Recall the sample at the supplied cutoff.");
    no_date.at = (1_u64 << 53) - 1;
    let unchanged = view(&no_date).unwrap();
    assert_eq!((unchanged.at, unchanged.since), (no_date.at, no_date.since));
}

#[test]
fn trusted_date_bearing_entities_and_longest_aliases_are_masked_without_rewriting_text() {
    let mut original = query("Retrieve SENSOR20250201 latest reading.");
    original.entity = ContractIdV1::new("sensor20250201").unwrap();
    let entities = BTreeSet::from([original.entity.clone()]);
    let aliases = BTreeMap::from([(
        original.entity.clone(),
        vec![
            "station".to_string(),
            "station-2025-02-01".to_string(),
            "站点２０２５０２０１".to_string(),
        ],
    )]);
    for text in [
        "Retrieve SENSOR20250201 latest reading.",
        "Read Station-2025-02-01 metadata.",
        "Read 站点20250201 attributes.",
    ] {
        original.text = text.to_string();
        let bound = TimeView::build(&original, &entities, &aliases).unwrap();
        assert_eq!((bound.at, bound.since), (original.at, original.since));
        assert!(bound.permits(&original, MemoryOperationV1::Semantic));
        bound.verify_original(&original).unwrap();
    }
    original.text = "Read SENSOR20250201 as of 2025-02-01.".to_string();
    assert!(
        TimeView::build(&original, &entities, &aliases)
            .unwrap()
            .permits(&original, MemoryOperationV1::History)
    );

    let mut historical = query("Read canonical-A as of 2025-02-01.");
    historical.entity = ContractIdV1::new("canonical-A").unwrap();
    let other = ContractIdV1::new("canonical-B").unwrap();
    let owners = BTreeSet::from([historical.entity.clone(), other.clone()]);
    let unrelated = BTreeMap::from([(other, vec!["站点20250201".to_string()])]);
    assert!(
        TimeView::build(&historical, &owners, &unrelated)
            .unwrap()
            .permits(&historical, MemoryOperationV1::History)
    );
}

#[test]
fn unicode_normalization_and_ambiguous_or_invalid_dates_fail_closed() {
    let fullwidth = query("Recall the sample as of ２０２５－０２－０１.");
    assert!(
        view(&fullwidth)
            .unwrap()
            .permits(&fullwidth, MemoryOperationV1::History)
    );
    for text in [
        "Read 2025-02-30.",
        "Read 2025-01-01 and 2025-02-01.",
        "Read ٢٠٢٥٠٢٠١.",
    ] {
        assert!(view(&query(text)).is_err(), "accepted {text}");
    }
    let repeated = query("Read 2025-02-01, that is 20250201.");
    assert!(
        view(&repeated)
            .unwrap()
            .permits(&repeated, MemoryOperationV1::History)
    );
    let original = query("Read STRASSE20250201 metadata.");
    let aliases = BTreeMap::from([(original.entity.clone(), vec!["Straße20250201".to_string()])]);
    let conservatively_dated = TimeView::build(
        &original,
        &BTreeSet::from([original.entity.clone()]),
        &aliases,
    )
    .unwrap();
    assert!(!conservatively_dated.permits(&original, MemoryOperationV1::Semantic));
}

#[test]
fn multiple_cutoffs_are_typed_unsupported_while_invalid_dates_remain_errors() {
    assert!(matches!(
        view(&query("Read samples at 2000-01-01 and 2000-02-01.")),
        Err(TimeViewError::UnsupportedMultipleCutoffs)
    ));
    assert!(matches!(
        view(&query("Read the sample at 2000-02-30.")),
        Err(TimeViewError::Invalid(_))
    ));
}
