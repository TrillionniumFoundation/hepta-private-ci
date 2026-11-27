use super::*;

#[test]
fn desktop_catalog_has_only_six_finite_tools_and_preserves_legacy_catalog() {
    let before = crate::original_notes_thread_tools();
    let tools = original_desktop_thread_tools();
    let names = tools
        .iter()
        .map(|tool| {
            let DynamicToolSpec::Function(function) = tool else {
                panic!("the finite Desktop profile contains only fixed functions");
            };
            function.name.as_str()
        })
        .collect::<Vec<_>>();
    assert_eq!(
        names,
        [
            "hepta_notes_state",
            "hepta_notes_replace",
            "hepta_notes_status",
            "hepta_calculator_state",
            "hepta_calculator_evaluate",
            "hepta_calculator_status"
        ]
    );
    for tool in tools {
        let DynamicToolSpec::Function(function) = tool else {
            unreachable!()
        };
        assert_eq!(function.input_schema["additionalProperties"], false);
        assert!(!function.defer_loading);
    }
    assert_eq!(crate::original_notes_thread_tools(), before);
}
