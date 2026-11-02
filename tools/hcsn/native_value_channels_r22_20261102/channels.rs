//! Full financial value/risk channels on a bounded continuation-only profile.
//! Log-distance input is strictly above every R11 Taylor/blend interval.
use crate::dual::Dual;
use std::error::Error;
pub type Result<T> = std::result::Result<T, Box<dyn Error>>;
pub const LOWER:[f64;9]=[0.079,0.0195,0.59,0.265,6.30,61.0,0.15,0.002,0.5];
pub const UPPER:[f64;9]=[0.081,0.0205,0.61,0.275,6.48,62.4,0.4,0.04,2.0];
#[link(name="m")]
unsafe extern "C" { fn erfc(value:f64)->f64; }
const X: [f64; 8] = [
    0.0950125098376374405,
    0.281603550779258915,
    0.458016777657227370,
    0.617876244402643771,
    0.755404408355002999,
    0.865631202387831755,
    0.944575023073232600,
    0.989400934991649939,
];
const W: [f64; 8] = [
    0.189450610455068641,
    0.182603415044923639,
    0.169156519395002647,
    0.149595988816576708,
    0.124628971255534071,
    0.0951585116824926053,
    0.0622535239386474565,
    0.0271524594117541762,
];



fn ensure(condition:bool,message:&str)->Result<()> {
    if condition {Ok(())} else {Err(message.into())}
}
fn integral(f:impl Fn(f64)->Dual)->Dual {
    let mut sum=Dual::constant(0.0);
    for (node,weight) in X.iter().zip(W) {
        sum=sum+weight*(f((1.0-node)/2.0)+f((1.0+node)/2.0));
    }
    sum/2.0
}
fn density(x:Dual)->Dual {(-0.5*x*x).exp()/(2.0*std::f64::consts::PI).sqrt()}
fn cdf(x:Dual)->Dual {
    if !x.v.is_finite() || x.v.abs()>12.0 {return Dual{v:f64::NAN,g:[f64::NAN;10]};}
    // Safety: libm erfc has a scalar double ABI and accepts every finite double;
    // there are no pointers or ownership transfers. This is a Linux/libm profile.
    let value=unsafe {erfc(-x.v/std::f64::consts::SQRT_2)/2.0};
    let derivative=(-0.5*x.v*x.v).exp()/(2.0*std::f64::consts::PI).sqrt();
    Dual{v:value,g:x.g.map(|t|derivative*t)}
}
fn exp_cdf(exponent:Dual,argument:Dual)->Dual {exponent.exp()*cdf(argument)}
fn exp_density(exponent:Dual,argument:Dual)->Dual {(exponent-0.5*argument*argument).exp()/(2.0*std::f64::consts::PI).sqrt()}
fn cdf_interval(exponent:Dual,lo:Dual,hi:Dual)->Dual {
    let width=hi-lo;
    exponent.exp()*width*integral(|t|density(lo+t*width))
}
struct Hx {delta:Dual,alpha:Dual,m:Dual,s2:Dual,rate:Dual,a:Dual,z:Dual,zt:Dual,
           eta:Dual,gamma:Dual,s:Dual,c:Dual,q:Dual,discount:Dual,cost:Dual,b:Dual}
impl Hx {
    fn b_function(&self,y:Dual)->Dual {
        let tail=cdf(-self.z*self.s);
        integral(|t|{
            let at=-self.z+t*(self.z+y);
            self.s*density(at*self.s)+at*self.s*self.s*
                (0.5*(self.z-at)*(self.z+at)*self.s*self.s).exp()*tail
        })
    }
    fn first_hit(&self,x:Dual)->(Dual,Dual) {
        let f=cdf(-x/self.s-self.a*self.s)+exp_cdf(-2.0*self.a*x,-x/self.s+self.a*self.s);
        let g=exp_cdf((-self.a+self.zt)*x,-x/self.s-self.zt*self.s)
            +exp_cdf((-self.a-self.zt)*x,-x/self.s+self.zt*self.s);
        (f,g)
    }
    fn a_numerator_derivative(&self,x:Dual,u:Dual)->Dual {
        let exponent=0.5*(self.z*self.z-u*u)*self.s*self.s;
        let common=-cdf_interval(exponent-self.gamma*x,self.z*self.s-x/self.s,self.z*self.s)
            +exp_cdf(exponent+self.eta*x,-x/self.s-self.z*self.s);
        let positive=exp_cdf(-(self.a+u)*x,-x/self.s+u*self.s);
        let negative=exp_cdf(-(self.a-u)*x,-x/self.s-u*self.s);
        self.s*exp_density(-self.gamma*x,u*self.s)-u*self.s*self.s*common
            +x*positive-self.s*exp_density(-(self.a+u)*x,-x/self.s+u*self.s)
            -x*negative+self.s*exp_density(-(self.a-u)*x,-x/self.s-u*self.s)
    }
    fn a_function(&self,x:Dual,y:Dual)->Dual {
        let mut total=Dual::constant(0.0);
        for u in [y,-y] {
            // N(z)=0, hence N(u)/(z-u)=-integral N'(z-t(z-u))dt.
            // This representation removes both denominator branches entirely.
            let denominator=self.z-u;
            total=total-integral(|t|self.a_numerator_derivative(x,self.z-t*denominator));
        }
        total
    }
    fn equity(&self,x:Dual)->Dual {
        let mut value=self.b*x.exp()-self.delta*self.b/(self.z*self.s2)*(-self.gamma*x).exp()/(self.gamma+1.0);
        value=value-self.cost/(self.z*self.s2)*(1.0/self.eta-(-self.gamma*x).exp_m1()/self.gamma);
        value+(self.discount*self.q*self.a_function(x,self.a)
            -(self.alpha*self.b/self.m-self.c/self.rate)*self.a_function(x,self.zt))/(self.z*self.s2)
    }
}
pub fn evaluate(values:[f64;10])->Result<[Dual;5]> {
    for index in 0..9 {
        ensure(values[index].is_finite() && values[index]>=LOWER[index] && values[index]<=UPPER[index],"physical parameter outside profile")?;
    }
    ensure(values[9].is_finite() && (0.005..=0.6).contains(&values[9]),"log-distance outside continuation-only profile")?;
    let [r,delta,alpha,tax,coupon,principal,sigma,liquidity,m,x]=std::array::from_fn(|i|Dual::variable(values[i],i));
    let s2=sigma*sigma;
    let rate=r+liquidity;
    let a=(r-delta-s2/2.0)/s2;
    let z=(a*a+2.0*r/s2).sqrt();
    let zt=(a*a+2.0*rate/s2).sqrt();
    let eta=if a.v>=0.0 {2.0*r/(s2*(z+a))} else {z-a};
    let gamma=2.0*r/(s2*eta);
    let s=sigma*m.sqrt();
    let c=coupon/m;
    let q=principal/m-c/rate;
    let discount=(-rate*m).exp();
    let cost=(1.0-tax)*coupon-(-rate*m).exp_m1()*q;
    let mut model=Hx{delta,alpha,m,s2,rate,a,z,zt,eta,gamma,s,c,q,discount,cost,b:Dual::constant(0.0)};
    let bs=model.b_function(-zt)+model.b_function(zt);
    let denominator=0.5*s2*(gamma+1.0)+alpha/m*bs;
    ensure(denominator.v.is_finite() && denominator.v>0.0,"boundary denominator invalid")?;
    model.b=(cost/eta+q*discount*(model.b_function(-a)+model.b_function(a))+c/rate*bs)/denominator;
    let flow=delta*model.b-(1.0-tax)*coupon+(alpha*model.b-principal)/m;
    let scale=(delta.v*model.b.v).abs()+((1.0-tax.v)*coupon.v).abs()+((alpha.v*model.b.v).abs()+principal.v.abs())/m.v;
    ensure(model.b.v.is_finite() && model.b.v>0.0 && flow.v< -64.0*f64::EPSILON*scale.max(1.0),"static boundary inadmissible")?;
    let equity=model.equity(x);
    let (f,g)=model.first_hit(x);
    let debt=c/rate+discount*q*(1.0-f)+(alpha*model.b/m-c/rate)*g;
    let outputs=[model.b,equity,f,g,debt];
    ensure(outputs.iter().all(|v|v.v.is_finite() && v.g.iter().all(|x|x.is_finite())),"nonfinite output or CDF argument outside profile")?;
    Ok(outputs)
}
