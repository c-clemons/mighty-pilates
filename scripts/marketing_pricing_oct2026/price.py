from base import *
ap = sales[(sales.IS_AUTOPAY==1)&(sales.ITEM_TYPE=='Pricing Option')].copy()
ap['P']=ap.PRODUCT_DESCRIPTION.str.strip().str.replace(r'\s+',' ',regex=True)
mem=pd.read_pickle('memeom.pkl'); mem['DATE']=pd.to_datetime(mem.DATE); mem['M']=mem.DATE.dt.to_period('M')
roster = mem.groupby(['GCK','M']).agg(active=('IS_ACTIVE_MEMBERSHIP','max'),susp=('IS_SUSPENDED_MEMBERSHIP','max')).reset_index()
# member-month billing: total autopay net, main product (largest charge)
mmb = ap[ap.NET>0].sort_values('NET',ascending=False).groupby(['GCK','M']).agg(AMT=('NET','sum'),P=('P','first'),S=('S','first'),PRICE=('NET','first'),CAT=('REVENUE_CATEGORY','first')).reset_index()
if __name__=='__main__':
    tot=mmb.groupby('M').agg(billed=('GCK','nunique'),rev=('AMT','sum')); tot['arpm']=tot.rev/tot.billed
    r=roster.groupby('M').agg(active=('active','sum'),susp=('susp','sum'),roster=('GCK','nunique'))
    print(tot.join(r).loc['2024-10':].round(0).to_string())
    print(ap[ap.NET>0].groupby('CAT' if 'CAT' in ap else 'REVENUE_CATEGORY').NET.sum())
