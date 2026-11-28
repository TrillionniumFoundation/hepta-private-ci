/* Enclose a Taylor polynomial of the complex normal CDF at one decimal
   point. MPFI and MPFR use directed rounding. Python separately adds the
   analytic complex Taylor remainder and the radius of the supplied input. */
#include <gmp.h>
#include <math.h>

#if __has_include(<mpfi.h>)
#include <mpfi.h>
#else
/* Runtime-only Debian installation. These are the public MPFR/MPFI 64-bit
   ABI declarations; distributions shipping headers use those above. */
typedef struct { long _mpfr_prec; int _mpfr_sign; long _mpfr_exp; mp_limb_t *_mpfr_d; } fr;
typedef struct { fr left,right; } FI;
typedef FI mpfi_t[1];
extern void mpfi_init2(FI*,long),mpfi_clear(FI*);
extern int mpfi_set_d(FI*,double),mpfi_mul(FI*,const FI*,const FI*),
mpfi_sub(FI*,const FI*,const FI*),mpfi_add(FI*,const FI*,const FI*),mpfi_set(FI*,const FI*),
mpfi_mul_ui(FI*,const FI*,unsigned long),mpfi_div_ui(FI*,const FI*,unsigned long),
mpfi_neg(FI*,const FI*),mpfi_const_pi(FI*),mpfi_sqrt(FI*,const FI*),mpfi_div(FI*,const FI*,const FI*);
extern double mpfr_get_d(const fr*, int);
extern int mpfr_snprintf(char*,size_t,const char*,...);
extern int mpfi_set_str(FI*,const char*,int);
#endif

int cdf_poly(const char *x,const char *y,int n,char *out) {
    mpfi_t t[13];
    for(int i=0;i<13;i++) mpfi_init2(t[i],320);
    /* t0,t1 = -z^2; t2,t3 = term; t4,t5 = running sums. */
    mpfi_set_str(t[2],x,10); mpfi_set_str(t[3],y,10);
    mpfi_set(t[4],t[2]); mpfi_set(t[5],t[3]);
    mpfi_mul(t[6],t[3],t[3]); mpfi_mul(t[7],t[2],t[2]); mpfi_sub(t[0],t[6],t[7]);
    mpfi_mul(t[1],t[2],t[3]); mpfi_mul_ui(t[1],t[1],2); mpfi_neg(t[1],t[1]);
    for(int k=1;k<=n;k++){
        mpfi_mul(t[6],t[0],t[2]); mpfi_mul(t[7],t[1],t[3]); mpfi_sub(t[8],t[6],t[7]);
        mpfi_mul(t[6],t[1],t[2]); mpfi_mul(t[7],t[0],t[3]); mpfi_add(t[9],t[6],t[7]);
        mpfi_mul_ui(t[6],t[8],2*k-1); mpfi_div_ui(t[2],t[6],2*k*(2*k+1));
        mpfi_mul_ui(t[6],t[9],2*k-1); mpfi_div_ui(t[3],t[6],2*k*(2*k+1));
        mpfi_add(t[4],t[4],t[2]); mpfi_add(t[5],t[5],t[3]);
    }
    mpfi_const_pi(t[6]); mpfi_mul_ui(t[6],t[6],2); mpfi_sqrt(t[6],t[6]);
    mpfi_div(t[4],t[4],t[6]); mpfi_set_d(t[7],0.5); mpfi_add(t[4],t[4],t[7]);
    mpfi_div(t[5],t[5],t[6]);
    /* MPFR_RNDD=3, MPFR_RNDU=2. */
    mpfr_snprintf(out,120,"%.72RDe",&t[4]->left); mpfr_snprintf(out+120,120,"%.72RUe",&t[4]->right);
    mpfr_snprintf(out+240,120,"%.72RDe",&t[5]->left); mpfr_snprintf(out+360,120,"%.72RUe",&t[5]->right);
    for(int i=0;i<13;i++) mpfi_clear(t[i]);
    return 0;
}
