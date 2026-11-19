use crate::AttachedListener;
use crate::Listener;

macro_rules! impl_for {
    (<$gen: ident> $($ty: ty),+) => {
        $(
            impl <$gen> ::futures_core::Stream for $ty {
                type Item = $gen;

                fn poll_next(mut self: ::std::pin::Pin<&mut Self>, cx: &mut ::std::task::Context<'_>) -> ::std::task::Poll<Option<Self::Item>> {
                    self.poll_recv(cx).map(Some)
                }
            }

            impl<$gen> ::futures_core::FusedStream for $ty {
                fn is_terminated(&self) -> bool {
                    self.rx.is_closed() && self.rx.is_empty()
                }
            }
        )+
    };
}

impl_for!(<T> Listener<T>, AttachedListener<'_, T>);
