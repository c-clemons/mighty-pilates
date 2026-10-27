from base import *
# ---- per-new-client outcomes
s = sales.merge(new[['GCK','D0']],on='GCK'); s['DAY']=(s.SALE_DATE-s.D0).dt.days; s=s[s.DAY>=0]
def cum(days): return s[s.DAY<=days].groupby('GCK').NET.sum()
for d in (30,90,180,270,365,730,1095): new[f'R{d}']=new.GCK.map(cum(d)).fillna(0)
new['RTD']=new.GCK.map(s.groupby('GCK').NET.sum()).fillna(0)
rep=s[(s.ITEM_TYPE=='Pricing Option')&(s.NET>0)&(s.DAY>=1)&(s.DAY<=90)].groupby('GCK').size()
new['REPEAT90']=new.GCK.isin(rep.index)
nonintro=s[(s.ITEM_TYPE=='Pricing Option')&(s.NET>0)&(s.IS_INTRO_OFFER==0)&(s.DAY>=1)&(s.DAY<=120)].groupby('GCK').size()
new['FULLPRICE120']=new.GCK.isin(nonintro.index)
ap=s[(s.IS_AUTOPAY==1)&(s.NET>0)]
new['MEMBER180']=new.GCK.isin(ap[ap.DAY<=180].GCK.unique()); new['MEMBER_EVER']=new.GCK.isin(ap.GCK.unique())
# activity by month index (visit or purchase)
act=pd.concat([vm[['GCK','M']], sales[sales.NET>0][['GCK','M']]]).drop_duplicates().merge(new[['GCK','M0']],on='GCK')
act['MI']=(act.M-act.M0).apply(lambda x:x.n)
new['ACT_M4_6']=new.GCK.isin(act[act.MI.between(4,6)].GCK.unique())
new['ACT_M7_9']=new.GCK.isin(act[act.MI.between(7,9)].GCK.unique())
recent=pd.concat([vm[vm.M>='2026-08'][['GCK']], sales[(sales.SALE_DATE>='2026-08-01')&(sales.NET>0)][['GCK']]]).GCK.unique()
new['ACT_RECENT']=new.GCK.isin(recent)
new.to_pickle('new.pkl')
if __name__=='__main__':
    # LTV curves by cohort quarter
    g=new[new.D0>='2022-01-01'].groupby('Q0').agg(n=('GCK','count'),r30=('R30','mean'),r90=('R90','mean'),r180=('R180','mean'),r270=('R270','mean'),r365=('R365','mean'),r730=('R730','mean'),r1095=('R1095','mean'),
        repeat90=('REPEAT90','mean'),full120=('FULLPRICE120','mean'),mem180=('MEMBER180','mean'),a46=('ACT_M4_6','mean'),a79=('ACT_M7_9','mean'),intro=('INTRO0','mean'),cp=('CP_FIRST','mean'))
    print(g.round(2).to_string())
    q4=new[new.Q0=='2025Q4']
    t=q4.groupby('S0').agg(n=('GCK','count'),intro=('INTRO0','sum'),cp=('CP_FIRST','sum'),r90=('R90','mean'),r270=('R270','mean'),rtd=('RTD','mean'),repeat90=('REPEAT90','mean'),full120=('FULLPRICE120','mean'),mem180=('MEMBER180','mean'),a46=('ACT_M4_6','mean'),a79=('ACT_M7_9','mean'),recent=('ACT_RECENT','mean'))
    a=ADS[ADS.M.between('2025-10','2025-12')].groupby('S').SPEND.sum(); m=MKT[MKT.M.between('2025-10','2025-12')].groupby('S').SPEND.sum()
    t['ads']=a; t['mkt']=m; t['cac']=t.ads/t.n; t['roas90']=t.n*t.r90/t.ads; t['roas270']=t.n*t.r270/t.ads
    print(t.round(2).to_string()); print('HO ads',a.get('HO'),'mkt',m.get('HO'), 'tot ads',a.sum(),'mkt',m.sum(), 'n',len(q4))
    print(q4[['R30','R90','R180','R270','RTD']].mean(), q4[['REPEAT90','FULLPRICE120','MEMBER180','MEMBER_EVER','ACT_M4_6','ACT_M7_9','ACT_RECENT','INTRO0','CP_FIRST']].mean())
    # intro vs non intro
    print(q4.groupby('INTRO0')[['R90','R270','REPEAT90','MEMBER180','ACT_M4_6']].mean().join(q4.groupby('INTRO0').size().rename('n')))
    print(q4.P0.str.slice(0,45).value_counts().head(12))
