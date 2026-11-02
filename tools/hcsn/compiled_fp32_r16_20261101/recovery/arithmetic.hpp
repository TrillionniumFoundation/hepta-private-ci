#pragma once
#include <array>
#include <cfloat>
#include <cmath>
#include <cstddef>
#include <limits>
#include <stdexcept>
#include <type_traits>

namespace hx {
static_assert(sizeof(float)==4 && std::numeric_limits<float>::digits==24);
static_assert(std::numeric_limits<float>::is_iec559 && FLT_EVAL_METHOD==0);

// Double participates only in compile-time preparation of FIXED coefficients.
// Pair financial inputs can enter only through an explicit float constructor.
struct Fixed {
    double native;
    float hi,lo;
    consteval Fixed(double v):native(v),hi(static_cast<float>(v)),lo(static_cast<float>(v-static_cast<double>(hi))){}
    consteval Fixed(double v,float h,float l):native(v),hi(h),lo(l){}
};

struct Pair {
    float hi=0.0f,lo=0.0f;
    constexpr Pair()=default;
    explicit constexpr Pair(float h,float l=0.0f):hi(h),lo(l){}
    explicit constexpr Pair(Fixed v):hi(v.hi),lo(v.lo){}
    Pair(double)=delete;
    float rounded() const {return hi+lo;}
};

inline Pair two_sum(float a,float b){
    float s=a+b,v=s-a;
    return Pair(s,(a-(s-v))+(b-v));
}
inline Pair two_product(float a,float b){
    float p=a*b,ac=4097.0f*a,bc=4097.0f*b;
    float ah=ac-(ac-a),bh=bc-(bc-b),al=a-ah,bl=b-bh;
    return Pair(p,((ah*bh-p)+ah*bl+al*bh)+al*bl);
}
inline Pair operator+(Pair a,Pair b){Pair s=two_sum(a.hi,b.hi);float e=s.lo+(a.lo+b.lo);return two_sum(s.hi,e);}
inline Pair operator-(Pair a){return Pair(-a.hi,-a.lo);}
inline Pair operator-(Pair a,Pair b){return a+(-b);}
inline Pair operator*(Pair a,Pair b){
    Pair p=two_product(a.hi,b.hi);float e=(p.lo+a.hi*b.lo)+a.lo*b.hi;e=e+a.lo*b.lo;return two_sum(p.hi,e);
}
inline Pair operator/(Pair a,Pair b){
    Pair q(a.hi/b.hi);
    for(int i=0;i<2;++i){Pair residual=a-b*q;q=q+Pair((residual.hi+residual.lo)/b.hi);}
    return q;
}
inline bool operator<(Pair a,Pair b){return a.hi<b.hi || (a.hi==b.hi && a.lo<b.lo);}
inline bool operator<=(Pair a,Pair b){return !(b<a);}
inline bool operator>(Pair a,Pair b){return b<a;}
inline bool operator>=(Pair a,Pair b){return !(a<b);}
inline bool finite(Pair x){return std::isfinite(x.hi)&&std::isfinite(x.lo);}
inline bool finite(float x){return std::isfinite(x);}
inline bool finite(double x){return std::isfinite(x);}
template<class R> inline R fixed(Fixed x){if constexpr(std::is_same_v<R,Pair>)return Pair(x);else return static_cast<R>(x.native);}
template<class R> inline R integer(int x){if constexpr(std::is_same_v<R,Pair>)return Pair(static_cast<float>(x));else return static_cast<R>(x);}
template<class R> inline R absolute(R x){return x<integer<R>(0)?-x:x;}
template<class R> inline R power(R x,int n){
    if(n<0)return integer<R>(1)/power(x,-n);
    R result=integer<R>(1);
    while(n){if(n%2)result=result*x;x=x*x;n/=2;}
    return result;
}
}
#include "constants.hpp"
namespace hx {

inline Pair real_exp(Pair x){
    if(!finite(x))throw std::runtime_error("Nonfinite compensated exponential input");
    if(x<Pair(-104.0f))return Pair(0.0f);
    if(x>Pair(88.0f))throw std::runtime_error("FP32 exponential range exceeded");
    int k=static_cast<int>(std::nearbyint(x.hi*1.4426950408889634f));
    Pair r=x-Pair(static_cast<float>(k))*Pair(LN2),result=Pair(1.0f)/Pair(FACTORIAL[16]);
    for(int n=15;n>=0;--n)result=result*r+Pair(1.0f)/Pair(FACTORIAL[n]);
    return Pair(std::ldexp(result.hi,k),std::ldexp(result.lo,k));
}
inline Pair real_expm1(Pair x){
    if(absolute(x)<Pair(0.5f)){
        Pair result=Pair(1.0f)/Pair(FACTORIAL[16]);
        for(int n=15;n>0;--n)result=result*x+Pair(1.0f)/Pair(FACTORIAL[n]);
        return result*x;
    }
    return real_exp(x)-Pair(1.0f);
}
inline Pair real_sqrt(Pair x){Pair y(std::sqrt(x.hi));return y+(x-y*y)/(Pair(2.0f)*y);}

// Float-only seed for compensated log. This avoids calling a libm logf whose
// private implementation is allowed to use double internally. The correction
// below is the frozen pair algorithm; this seed replacement is disclosed.
inline float log_seed(float x){
    if(!(x>0.0f))return std::numeric_limits<float>::quiet_NaN();
    int exponent=0;float m=std::frexp(x,&exponent)*2.0f;--exponent;
    float t=(m-1.0f)/(m+1.0f),square=t*t,polynomial=1.0f/17.0f;
    for(int n=15;n>=1;n-=2)polynomial=polynomial*square+1.0f/static_cast<float>(n);
    return (2.0f*t)*polynomial+static_cast<float>(exponent)*0.69314718055994530942f;
}
inline Pair real_log(Pair x){Pair y(log_seed(x.hi));Pair r=x/real_exp(y)-Pair(1.0f);return y+r-r*r/Pair(2.0f);}
inline Pair real_log1p(Pair x){
    if(absolute(x)<Pair(Fixed(.1))){
        Pair result=Pair(-1.0f)/Pair(16.0f);
        for(int n=15;n>0;--n)result=result*x+Pair(n%2?1.0f:-1.0f)/Pair(static_cast<float>(n));
        return result*x;
    }
    return real_log(Pair(1.0f)+x);
}
inline float real_exp(float x){return std::exp(x);}
inline double real_exp(double x){return std::exp(x);}
inline float real_expm1(float x){return std::expm1(x);}
inline double real_expm1(double x){return std::expm1(x);}
inline float real_sqrt(float x){return std::sqrt(x);}
inline double real_sqrt(double x){return std::sqrt(x);}
inline float real_log(float x){return std::log(x);}
inline double real_log(double x){return std::log(x);}
inline float real_log1p(float x){return std::log1p(x);}
inline double real_log1p(double x){return std::log1p(x);}

template<class R,std::size_t N>inline R polynomial(R x,const std::array<Fixed,N>& coefficients){
    R result=fixed<R>(coefficients[0]);for(std::size_t i=1;i<N;++i)result=result*x+fixed<R>(coefficients[i]);return result;
}
template<class R>inline R erfc_ratio(R x){
    if(x<integer<R>(8))return polynomial(x,CDF_P)/polynomial(x,CDF_Q);
    return polynomial(x,CDF_R)/polynomial(x,CDF_S);
}
template<class R>inline R real_cdf(R x){
    R z=x*fixed<R>(INV_SQRT2);
    if(absolute(z)<integer<R>(1))return (integer<R>(1)+z*polynomial(z*z,CDF_T)/polynomial(z*z,CDF_U))/integer<R>(2);
    R tail=real_exp(-z*z)*erfc_ratio(absolute(z))/integer<R>(2);
    return x>integer<R>(0)?integer<R>(1)-tail:tail;
}
template<class R>inline R real_logcdf(R x){
    R z=x*fixed<R>(INV_SQRT2);
    if(absolute(z)<integer<R>(1))return real_log(real_cdf(x));
    R logtail=-z*z+real_log(erfc_ratio(absolute(z)))-fixed<R>(LN2);
    return x>integer<R>(0)?real_log1p(-real_exp(logtail)):logtail;
}

template<class R>struct Dual{
    R v{};std::array<R,10>g{};
    Dual()=default;
    explicit Dual(R value):v(value){}
    explicit Dual(Fixed value):v(fixed<R>(value)){}
    static Dual input(float value,int column){Dual result{R(value)};result.g[column]=integer<R>(1);return result;}
};
template<class R>inline Dual<R> operator+(Dual<R>a,const Dual<R>&b){a.v=a.v+b.v;for(int i=0;i<10;++i)a.g[i]=a.g[i]+b.g[i];return a;}
template<class R>inline Dual<R> operator-(Dual<R>a){a.v=-a.v;for(auto&v:a.g)v=-v;return a;}
template<class R>inline Dual<R> operator-(Dual<R>a,const Dual<R>&b){return a+(-b);}
template<class R>inline Dual<R> operator*(const Dual<R>&a,const Dual<R>&b){
    Dual<R>r(a.v*b.v);for(int i=0;i<10;++i)r.g[i]=a.g[i]*b.v+a.v*b.g[i];return r;
}
template<class R>inline Dual<R> operator/(const Dual<R>&a,const Dual<R>&b){
    Dual<R>r(a.v/b.v);for(int i=0;i<10;++i)r.g[i]=(a.g[i]-r.v*b.g[i])/b.v;return r;
}
#define HX_SCALAR(OP) \
template<class R>inline Dual<R>operator OP(const Dual<R>&a,Fixed b){return a OP Dual<R>(b);} \
template<class R>inline Dual<R>operator OP(Fixed a,const Dual<R>&b){return Dual<R>(a) OP b;}
HX_SCALAR(+)
HX_SCALAR(-)
HX_SCALAR(*)
HX_SCALAR(/)
#undef HX_SCALAR
template<class R>inline Dual<R> number(int n){return Dual<R>(integer<R>(n));}
template<class R>inline Dual<R> pow(const Dual<R>&x,int n){
    if(n==0)return number<R>(1);
    Dual<R>r(power(x.v,n));R slope=integer<R>(n)*power(x.v,n-1);
    for(int i=0;i<10;++i)r.g[i]=slope*x.g[i];
    return r;
}
template<class R>inline Dual<R> exp(const Dual<R>&x){Dual<R>r(real_exp(x.v));for(int i=0;i<10;++i)r.g[i]=r.v*x.g[i];return r;}
template<class R>inline Dual<R> expm1(const Dual<R>&x){Dual<R>r(real_expm1(x.v));R slope=real_exp(x.v);for(int i=0;i<10;++i)r.g[i]=slope*x.g[i];return r;}
template<class R>inline Dual<R> log(const Dual<R>&x){Dual<R>r(real_log(x.v));R slope=integer<R>(1)/x.v;for(int i=0;i<10;++i)r.g[i]=slope*x.g[i];return r;}
template<class R>inline Dual<R> sqrt(const Dual<R>&x){Dual<R>r(real_sqrt(x.v));R slope=fixed<R>(.5)/r.v;for(int i=0;i<10;++i)r.g[i]=slope*x.g[i];return r;}
template<class R>inline Dual<R> Phi(const Dual<R>&x){
    Dual<R>r(real_cdf(x.v));R slope=real_exp(-fixed<R>(.5)*x.v*x.v)*fixed<R>(INV_SQRT2PI);
    for(int i=0;i<10;++i)r.g[i]=slope*x.g[i];
    return r;
}
template<class R>inline Dual<R> logPhi(const Dual<R>&x){
    Dual<R>r(real_logcdf(x.v));R slope=real_exp(-fixed<R>(.5)*x.v*x.v-fixed<R>(LOG_SQRT2PI)-r.v);
    for(int i=0;i<10;++i)r.g[i]=slope*x.g[i];
    return r;
}
template<class R>inline Dual<R> exp_cdf(const Dual<R>&e,const Dual<R>&a){return exp(e+logPhi(a));}
template<class R>inline Dual<R> exp_phi(const Dual<R>&e,const Dual<R>&a){return exp(e-.5*a*a)/2.5066282746310002;}
template<class R>inline Dual<R> cdf_interval(const Dual<R>&e,const Dual<R>&lo,const Dual<R>&hi){
    Dual<R>big=lo.v>integer<R>(0)?logPhi(-lo):logPhi(hi);
    Dual<R>small=lo.v>integer<R>(0)?logPhi(-hi):logPhi(lo);
    return exp(e+big)*(-expm1(small-big));
}
}
