from price4 import *
R={}
base_ap=t26.AMT0.sum()
rows=[]
for k,m in zip(range(2,8),['Apr','May','Jun','Jul','Aug','Sep']):
    billed=t26[t26[f'AMT{k}']>0]; actual=t26[f'AMT{k}'].sum(); at_old=billed.AMT0.sum()
    exp=adj(t26,t25,lambda d:d[f'AMT{k}'].sum()/d.AMT0.sum())*base_ap
    rows.append(dict(month=m,actual=actual,expected=exp,price_gain=actual-at_old,attrition_loss=at_old-exp,net=actual-exp,billed=len(billed),expected_billed=adj(t26,t25,lambda d:d[f'B{k}'].mean())*len(t26)))
rev=pd.DataFrame(rows); print(rev.round(0).to_string()); print(rev.sum(numeric_only=True).round(0))
ret26=t26.RET.mean(); ret25=adj(t26,t25,lambda d:d.RET.mean()); print('n',len(t26),'ret26',ret26,'ret25adj',ret25,'excess members',len(t26)*(ret25-ret26))
dp=t26.PT.map({295:330/295-1,340:360/340-1}).mean(); print('avg price inc',dp, 'n295',(t26.PT==295).sum(),'n340',(t26.PT==340).sum())
# tenure
w=t26.TB.value_counts()
for tb in ['0-3m','3-6m','6-12m','12-24m','24m+']:
    print(tb,(t26.TB==tb).sum(), round(t26[t26.TB==tb].RET.mean(),3), round(t25[t25.TB==tb].RET.mean(),3))
# controls
for nm,c in (('2026',c26),('2025',c25)):
    for seg in ['Founders / pre-opening (no increase)','Student (no increase)']:
        x=c[c.SEG==seg]; print(nm,seg,len(x),round(x.RET.mean(),3))
# official member flows
m=pd.read_pickle('mem.pkl'); m['S']=m.STUDIO.str.replace('Mighty Pilates ','').map(CODE)
for col in ['NEW_MEMBERS','REACTIVATED','CHURNED','ACTIVE_EOM','SUSPENDED_EOM']: m[col]=pd.to_numeric(m[col])
tt=m.groupby('MONTH')[['NEW_MEMBERS','REACTIVATED','CHURNED','ACTIVE_EOM','SUSPENDED_EOM']].sum(); tt['TOTAL']=tt.ACTIVE_EOM+tt.SUSPENDED_EOM
print(tt.loc['2025-01':].to_string())
a=tt.loc['2025-04':'2025-09'].sum(); b=tt.loc['2026-04':'2026-09'].sum(); print('Apr-Sep new 25/26',a.NEW_MEMBERS,b.NEW_MEMBERS,'churn',a.CHURNED,b.CHURNED)
same=['BK','LF','SM','WW']; s=m[m.S.isin(same)]
print('same4 new', s[s.MONTH.between('2025-04','2025-09')].NEW_MEMBERS.sum(), s[s.MONTH.between('2026-04','2026-09')].NEW_MEMBERS.sum())
mmb2=mmb.groupby('M').agg(billed=('GCK','nunique'),rev=('AMT','sum'))
print(mmb2.loc['2025-09':'2026-09'].round(0).to_string())
rev.to_pickle('rev.pkl'); tt.to_pickle('memflows.pkl')
