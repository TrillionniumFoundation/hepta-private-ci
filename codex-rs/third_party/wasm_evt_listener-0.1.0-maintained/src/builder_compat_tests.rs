use super::ListenerBuilder;
use std::marker::PhantomData;

// No Clone/Debug/Eq bounds may leak onto the event parameter.
struct EventWithoutTraits;

#[test]
fn builder_traits_keep_unbounded_event_parameter_and_field_order() {
    let builder = ListenerBuilder::<EventWithoutTraits> {
        passive: true,
        capture: false,
        once: true,
        _arg: PhantomData,
    };
    let cloned = builder.clone();
    assert_eq!(builder, cloned);
    assert_eq!(
        format!("{builder:?}"),
        "ListenerBuilder { passive: true, capture: false, once: true }"
    );
    assert_ne!(
        builder,
        ListenerBuilder {
            once: false,
            ..cloned
        }
    );
}
