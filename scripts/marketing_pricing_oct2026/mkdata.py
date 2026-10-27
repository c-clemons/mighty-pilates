from base import *
import json
M=pd.read_pickle('model.pkl'); new=pd.read_pickle('new.pkl'); net=M['net']
NAME={v:k for k,v in CODE.items()}
months=pd.period_range('2025-01','2026-09',freq='M')
mk=MKT.groupby('M').SPEND.sum(); ad=ADS.groupby('M').SPEND.sum()
D={'months':[m.strftime('%b %y') for m in months],
   'ads':[round(float(ad[m])) if m in ad.index else None for m in months],
   'mkt':[round(float(mk[m])) if m in mk.index else None for m in months],
   'actual':[int(net.y[m]) for m in months],
   'expected':[round(float(net.cf[m]),1) for m in months]}
# studio table
q4=new[new.Q0=='2025Q4']
g=q4.groupby('S0').agg(new=('GCK','count'),a46=('ACT_M4_6','mean'),mem=('MEMBER180','mean'),r270=('R270','mean'))
f=pd.read_pickle('fill.pkl'); f['S']=f.STUDIO.str.replace('Mighty Pilates ','').map(CODE)
for c in ['SIGNED_IN','CAPACITY']: f[c]=f[c].astype(float)
f3=f[f.M.between('2026-07','2026-09')].groupby('S')[['SIGNED_IN','CAPACITY']].sum(); f4=f[f.M.between('2025-10','2025-12')].groupby('S')[['SIGNED_IN','CAPACITY']].sum()
g['fill']=f3.SIGNED_IN/f3.CAPACITY; g['fill_q4']=f4.SIGNED_IN/f4.CAPACITY
g['mkt_q4']=MKT[MKT.M.between('2025-10','2025-12')].groupby('S').SPEND.sum()
g=g.drop(index='WP')
D['studios']=[dict(code=s,name=NAME[s],mkt=round(float(r.mkt_q4)),new=int(r.new),a46=round(r.a46*100),mem=round(r.mem*100),v270=round(float(r.r270)),fill=round(r.fill*100),fill_chg=round((r.fill-r.fill_q4)*100)) for s,r in g.sort_values('r270',ascending=False).iterrows()]
for k in ['pct','pct_lo','pct_hi','lost','lost_lo','lost_hi','pre12','post_mk','dsp','cac','cac_lo','cac_hi','yoy_drop','dsp_yoy','cac100','v90','v180','v270','mult24','v24','q4mk','base_q','cur_q']:
    D[k]=float(M[k])
D['q4n']=len(q4)
rev=pd.read_pickle('rev.pkl'); D['price_net']=[round(float(x)) for x in rev.net]
json.dump(D,open('data.json','w'),indent=0)
print(json.dumps({k:D[k] for k in ['cac','cac100','v24','base_q','cur_q','q4n']}), sum(s['mkt'] for s in D['studios']))
for s in D['studios']: print(s)
