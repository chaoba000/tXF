#!/usr/bin/env python3
import csv, io, json, math, re, urllib.request
from datetime import datetime
from pathlib import Path

csv.field_size_limit(10**9)

URLS = {
    '市值型':'https://raw.githubusercontent.com/huangtop/ETF_Engine/main/charts_output/MarketCap_etf_comparison_unified.csv',
    '產業型':'https://raw.githubusercontent.com/huangtop/ETF_Engine/main/charts_output/Industry_etf_comparison_unified.csv',
    '高股息':'https://raw.githubusercontent.com/huangtop/ETF_Engine/main/charts_output/HighDividend_etf_comparison_unified.csv',
    '主動式':'https://raw.githubusercontent.com/huangtop/ETF_Engine/main/charts_output/Active_etf_comparison_unified.csv',
}
BUY_FEE=0.001425
SELL_FEE=0.001425
SELL_TAX=0.001
EXCLUDE_RE=re.compile(r'(正\s*2|正二|反\s*1|反一|反向|槓桿|2X|-1X|Inverse|Leveraged|ETN)',re.I)
SIGNALS=['20250630','20250731','20250829','20250930','20251031','20251128','20251231','20260130','20260226','20260331','20260430','20260529']
PREV=['20250529']+SIGNALS[:-1]
ENTRIES=['20250701','20250801','20250901','20251001','20251103','20251201','20260102','20260202','20260302','20260401','20260504','20260601']
EXITS=ENTRIES[1:]+['20260612']

def fetch_text(url):
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
    with urllib.request.urlopen(req,timeout=60) as r:
        return r.read().decode('utf-8-sig')

def parse_series(s):
    out={}
    for item in (s or '').split('|'):
        if ':' not in item: continue
        d,v=item.split(':',1)
        try: out[d]=float(v)
        except Exception: pass
    return out

def load_universe():
    uni={}
    excluded=[]
    for cat,url in URLS.items():
        text=fetch_text(url)
        for row in csv.DictReader(io.StringIO(text)):
            raw=row.get('證券代碼','').strip()
            code=raw.replace('.TW','').replace('.TWO','')
            name=row.get('名稱','').strip()
            if not code:
                continue
            if code.endswith(('L','R')) or EXCLUDE_RE.search(name):
                excluded.append({'code':code,'name':name,'category':cat,'reason':'槓桿/反向/ETN'})
                continue
            ser=parse_series(row.get('趨勢數據',''))
            if len(ser)<2: continue
            if code not in uni or len(ser)>len(uni[code]['series']):
                cats=set(uni.get(code,{}).get('categories',[]))
                cats.add(cat)
                uni[code]={'code':code,'name':name,'series':ser,'categories':sorted(cats)}
            else:
                uni[code]['categories']=sorted(set(uni[code]['categories'])|{cat})
    return uni,excluded

def px(rec,date):
    return rec['series'].get(date)

def eligible_rows(uni,i):
    rows=[]
    for code,rec in uni.items():
        a,b,e,x=px(rec,PREV[i]),px(rec,SIGNALS[i]),px(rec,ENTRIES[i]),px(rec,EXITS[i])
        if None in (a,b,e,x) or min(a,b,e,x)<=0: continue
        rows.append({'code':code,'name':rec['name'],'categories':'/'.join(rec['categories']),
                     'momentum':b/a-1,'forward':x/e-1})
    rows.sort(key=lambda r:(r['momentum'],r['code']),reverse=True)
    return rows

def rebalance_cost(prev_weights,target):
    keys=set(prev_weights)|set(target)
    buys=sum(max(target.get(k,0)-prev_weights.get(k,0),0) for k in keys)
    sells=sum(max(prev_weights.get(k,0)-target.get(k,0),0) for k in keys)
    return buys*BUY_FEE+sells*(SELL_FEE+SELL_TAX),0.5*(buys+sells),buys,sells

def max_dd(vals):
    peak=vals[0]; m=0
    for v in vals:
        peak=max(peak,v); m=min(m,v/peak-1)
    return m

def sample_stdev(vals):
    vals=[float(v) for v in vals]
    if len(vals)<2: return 0.0
    avg=sum(vals)/len(vals)
    return math.sqrt(sum((v-avg)**2 for v in vals)/(len(vals)-1))

def metrics(periods):
    navs=[1.0]+[p['nav'] for p in periods]
    rets=[p['net_return'] for p in periods]
    total=navs[-1]-1
    days=(datetime.strptime(EXITS[-1],'%Y%m%d')-datetime.strptime(ENTRIES[0],'%Y%m%d')).days
    cagr=(navs[-1]**(365/days)-1) if days>0 else total
    sd=sample_stdev(rets)
    vol=sd*math.sqrt(12)
    sharpe=(sum(rets)/len(rets)/sd*math.sqrt(12)) if sd>0 else 0
    mdd=max_dd(navs)
    return {'periods':len(periods),'total_return':total,'cagr':cagr,'mdd_period_end':mdd,
            'return_mdd':total/abs(mdd) if mdd<0 else None,'annualized_volatility':vol,
            'sharpe_rf0':sharpe,'positive_period_rate':sum(r>0 for r in rets)/len(rets),
            'worst_period':min(rets),'best_period':max(rets),
            'cumulative_one_way_turnover':sum(p.get('turnover',0) for p in periods),
            'estimated_cost_fraction':sum(p.get('cost',0) for p in periods)}

def simulate_topn(allrows,n):
    nav=1.0; prev={}; periods=[]
    for i,rows in enumerate(allrows):
        picks=rows[:n]
        if len(picks)<n: continue
        target={r['code']:1/n for r in picks}
        cost,turn,buys,sells=rebalance_cost(prev,target)
        gross=sum(r['forward'] for r in picks)/n
        net=(1-cost)*(1+gross)-1
        nav*=1+net
        periods.append({'signal_date':SIGNALS[i],'entry_date':ENTRIES[i],'exit_date':EXITS[i],
                        'eligible_count':len(rows),'gross_return':gross,'cost':cost,'net_return':net,
                        'turnover':turn,'buys':buys,'sells':sells,'nav':nav,
                        'picks':[{'rank':j+1,**r} for j,r in enumerate(picks)]})
        growth={r['code']:(1/n)*(1+r['forward']) for r in picks}
        den=sum(growth.values()); prev={k:v/den for k,v in growth.items()}
    return periods

def simulate_equal(allrows):
    nav=1.0; prev={}; periods=[]
    for i,rows in enumerate(allrows):
        n=len(rows)
        if n==0: continue
        target={r['code']:1/n for r in rows}
        cost,turn,buys,sells=rebalance_cost(prev,target)
        gross=sum(r['forward'] for r in rows)/n
        net=(1-cost)*(1+gross)-1; nav*=1+net
        periods.append({'signal_date':SIGNALS[i],'entry_date':ENTRIES[i],'exit_date':EXITS[i],
                        'eligible_count':n,'gross_return':gross,'cost':cost,'net_return':net,
                        'turnover':turn,'buys':buys,'sells':sells,'nav':nav})
        growth={r['code']:(1/n)*(1+r['forward']) for r in rows}
        den=sum(growth.values()); prev={k:v/den for k,v in growth.items()}
    return periods

def simulate_0050(uni):
    rec=uni['0050']; nav=1.0; periods=[]
    for i in range(len(SIGNALS)):
        e,x=px(rec,ENTRIES[i]),px(rec,EXITS[i])
        if e is None or x is None: continue
        gross=x/e-1
        cost=BUY_FEE if not periods else 0
        net=(1-cost)*(1+gross)-1; nav*=1+net
        periods.append({'signal_date':SIGNALS[i],'entry_date':ENTRIES[i],'exit_date':EXITS[i],
                        'eligible_count':1,'gross_return':gross,'cost':cost,'net_return':net,
                        'turnover':1.0 if len(periods)==1 else 0,'nav':nav})
    return periods

def write_csv(path,rows):
    if not rows: return
    keys=[]
    for r in rows:
        for k in r:
            if k not in keys: keys.append(k)
    with open(path,'w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=keys); w.writeheader(); w.writerows(rows)

def main():
    out=Path('output'); out.mkdir(exist_ok=True)
    uni,excluded=load_universe()
    allrows=[eligible_rows(uni,i) for i in range(len(SIGNALS))]
    results={}; summaries=[]
    for n in range(1,6):
        p=simulate_topn(allrows,n); results[f'Top{n}']=p; summaries.append({'strategy':f'Top{n}',**metrics(p)})
    eq=simulate_equal(allrows); results['全體等權']=eq; summaries.append({'strategy':'全體等權',**metrics(eq)})
    b=simulate_0050(uni); results['0050買進持有']=b; summaries.append({'strategy':'0050買進持有',**metrics(b)})
    summaries.sort(key=lambda x:x['total_return'],reverse=True)
    write_csv(out/'summary.csv',summaries)
    write_csv(out/'universe.csv',[{'code':v['code'],'name':v['name'],'categories':'/'.join(v['categories']),
                                  'first_date':min(v['series']),'last_date':max(v['series'])} for v in uni.values()])
    write_csv(out/'excluded.csv',excluded)
    for key,p in results.items():
        flat=[]
        for row in p:
            base={k:v for k,v in row.items() if k!='picks'}
            picks=row.get('picks',[])
            for j in range(5):
                if j<len(picks):
                    q=picks[j]
                    base[f'rank{j+1}_code']=q['code']; base[f'rank{j+1}_name']=q['name']
                    base[f'rank{j+1}_momentum']=q['momentum']; base[f'rank{j+1}_forward']=q['forward']
            flat.append(base)
        write_csv(out/(key.replace('/','_')+'.csv'),flat)
    ranks=[]
    for i,rows in enumerate(allrows):
        for rank,r in enumerate(rows[:20],1):
            ranks.append({'signal_date':SIGNALS[i],'rank':rank,**r})
    write_csv(out/'top20_each_signal.csv',ranks)
    payload={'data_start':ENTRIES[0],'data_end':EXITS[-1],'signal_start':SIGNALS[0],
             'signal_end':SIGNALS[-1],'universe_count':len(uni),'excluded_count':len(excluded),
             'eligible_counts':[len(x) for x in allrows],'summary':summaries}
    (out/'result.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(payload,ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
