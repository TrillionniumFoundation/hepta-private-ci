//! Fixed-width forward derivatives for all nine physical coordinates plus log-distance state.
use std::ops::{Add, Div, Mul, Neg, Sub};

#[derive(Clone, Copy, Debug)]
pub struct Dual {
    pub v: f64,
    pub g: [f64; 10],
}

impl Dual {
    pub fn constant(v: f64) -> Self {
        Self { v, g: [0.0; 10] }
    }
    pub fn variable(v: f64, index: usize) -> Self {
        let mut value = Self::constant(v);
        value.g[index] = 1.0;
        value
    }
    pub fn exp(self) -> Self {
        let v = self.v.exp();
        Self { v, g: self.g.map(|x| x * v) }
    }
    pub fn exp_m1(self) -> Self {
        Self { v: self.v.exp_m1(), g: self.g.map(|x| x * self.v.exp()) }
    }
    pub fn sqrt(self) -> Self {
        let v = self.v.sqrt();
        Self { v, g: self.g.map(|x| x / (2.0 * v)) }
    }
}

impl Add for Dual {
    type Output = Self;
    fn add(self, rhs: Self) -> Self {
        Self { v: self.v + rhs.v, g: std::array::from_fn(|i| self.g[i] + rhs.g[i]) }
    }
}
impl Sub for Dual {
    type Output = Self;
    fn sub(self, rhs: Self) -> Self {
        Self { v: self.v - rhs.v, g: std::array::from_fn(|i| self.g[i] - rhs.g[i]) }
    }
}
impl Mul for Dual {
    type Output = Self;
    fn mul(self, rhs: Self) -> Self {
        Self { v: self.v * rhs.v, g: std::array::from_fn(|i| self.g[i] * rhs.v + self.v * rhs.g[i]) }
    }
}
impl Div for Dual {
    type Output = Self;
    fn div(self, rhs: Self) -> Self {
        let v = self.v / rhs.v;
        Self { v, g: std::array::from_fn(|i| (self.g[i] - v * rhs.g[i]) / rhs.v) }
    }
}
impl Neg for Dual {
    type Output = Self;
    fn neg(self) -> Self {
        Self { v: -self.v, g: self.g.map(|x| -x) }
    }
}

macro_rules! scalar {
    ($trait:ident, $method:ident) => {
        impl $trait<f64> for Dual {
            type Output = Self;
            fn $method(self, rhs: f64) -> Self { self.$method(Dual::constant(rhs)) }
        }
        impl $trait<Dual> for f64 {
            type Output = Dual;
            fn $method(self, rhs: Dual) -> Dual { Dual::constant(self).$method(rhs) }
        }
    };
}
scalar!(Add, add);
scalar!(Sub, sub);
scalar!(Mul, mul);
scalar!(Div, div);
