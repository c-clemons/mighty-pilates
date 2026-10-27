from brk import *
import json
new=pd.read_pickle('new.pkl')
# ---- chosen model: E
F='y ~ C(S) + C(moy) + C(agebin) + nbrs + jan26 + post'
r=smf.glm(F,data=P,family=sm.families.Poisson()).fit(cov_type='cluster',cov_kwds={'groups':pd.factorize(P.M)[0]})
b,se=r.params['post'],r.bse['post']
P['fit']=r.predict(P); P0=P.copy(); P0['post']=0; P['cf']=r.predict(P0)
net=P.groupby('M')[['y','fit','cf']].sum()
postm=net.index>=pd.Period('2026-04','M')
actual_post=net.y[postm].mean(); cf_post=net.cf[postm].mean()
lost=cf_post-net.fit[postm].mean()
pct=np.exp(b)-1; pct_lo,pct_hi=np.exp(b+1.96*se)-1,np.exp(b-1.96*se)-1   # lo = smaller drop
fitpost=net.fit[postm].mean()
lost_lo=fitpost*(1/(1+pct_lo)-1); lost_hi=fitpost*(1/(1+pct_hi)-1)
mk=MKT.groupby('M').SPEND.sum(); ad=ADS.groupby('M').SPEND.sum()
pre12=mk['2025-04':'2026-03'].mean(); post_mk=mk['2026-04':'2026-08'].mean(); dsp=pre12-post_mk
cac=dsp/lost; cac_lo=dsp/lost_hi; cac_hi=dsp/lost_lo
# 100% attribution: YoY Apr-Sep new clients, Apr-Aug spend
nm=new.groupby('M0').size()
yoy_drop=nm['2025-04':'2025-09'].mean()-nm['2026-04':'2026-09'].mean()
dsp_yoy=mk['2025-04':'2025-08'].mean()-post_mk
cac100=dsp_yoy/yoy_drop
# values per client
q4=new[new.Q0=='2025Q4']
v90,v180,v270=q4.R90.mean(),q4.R180.mean(),q4.R270.mean()
m=new[(new.D0>='2022-10-01')&(new.D0<'2024-10-01')]; mult24=m.R730.mean()/m.R270.mean(); v24=v270*mult24
print(f"model: effect {pct:.3f} ({pct_lo:.3f} to {pct_hi:.3f}); lost/mo {lost:.1f} ({lost_lo:.1f}-{lost_hi:.1f}); actual post {actual_post:.1f} cf {cf_post:.1f}")
print(f"spend pre12 {pre12:.0f} post {post_mk:.0f} delta {dsp:.0f}; CAC {cac:.0f} ({cac_lo:.0f}-{cac_hi:.0f})")
print(f"100%: yoy drop {yoy_drop:.1f}/mo, spend delta {dsp_yoy:.0f}, CAC {cac100:.0f}")
print(f"values: 90d {v90:.1f} 180d {v180:.1f} 270d {v270:.1f} mult24 {mult24:.3f} v24 {v24:.0f}; n q4 {len(q4)}")
q4mk=mk['2025-10':'2025-12'].sum(); print('Q4 2025 S&M',q4mk,'paid ads',ad['2025-10':'2025-12'].sum())
base_q=nm['2026-07':'2026-09'].sum(); print('Q3 2026 new clients',base_q, 'Q4 2025 new', len(q4))
cur_q=post_mk*3; add=105000-cur_q; print('current quarterly pace',cur_q,'added',add)
for lab,c in (('model',cac),('100%',cac100),('model_lo_cost',cac_lo),('model_hi_cost',cac_hi)):
    n=add/c; print(f"{lab}: +{n:.0f} clients; 90d {n*v90:,.0f} ({v90/c:.2f}x) 180d {n*v180:,.0f} ({v180/c:.2f}x) 9mo {n*v270:,.0f} ({v270/c:.2f}x) 24mo {n*v24:,.0f} ({v24/c:.2f}x)")
    n2=q4mk/c; print(f"   Q4 2025 retro: {n2:.0f} clients ({n2/len(q4):.0%})")
specs=[]
for lab,f in [('Seasonality and studio launch ramp only','y ~ C(S) + C(moy) + C(agebin) + post'),('+ January 2026 price change','y ~ C(S) + C(moy) + C(agebin) + jan26 + post'),('+ common time trend','y ~ C(S) + C(moy) + C(agebin) + t + post'),('+ new studios nearby','y ~ C(S) + C(moy) + C(agebin) + nbrs + post'),('Chosen: price change + new studios nearby',F),('Chosen, studios open 12+ months only','y ~ C(S) + C(moy) + nbrs + jan26 + post')]:
    d=P if '12+' not in lab else P[P.age>=12]
    rr=fit(f,d,lab); specs.append(rr)
pd.to_pickle(dict(net=net,P=P,specs=specs,pct=pct,pct_lo=pct_lo,pct_hi=pct_hi,lost=lost,lost_lo=lost_lo,lost_hi=lost_hi,pre12=pre12,post_mk=post_mk,dsp=dsp,cac=cac,cac_lo=cac_lo,cac_hi=cac_hi,
  yoy_drop=yoy_drop,dsp_yoy=dsp_yoy,cac100=cac100,v90=v90,v180=v180,v270=v270,mult24=mult24,v24=v24,q4mk=q4mk,base_q=base_q,cur_q=cur_q,coef=r.params,bse=r.bse),'model.pkl')
