#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ETF Monitor 주간 업데이트 (SKILL.md 인라인 스크립트의 repo 버전 — 기능 동일)
# 사용법: cd <repo> && python3 scripts/weekly_update.py [--start N] [--end M]
#   --start/--end : yfinance 청크 실행용 (타임아웃 시 분할). 생략하면 전체 + 인사이트 계산.
import sys, json, glob
try:
    p = glob.glob('/sessions/*/mnt/Claude/.pylibs')
    if p: sys.path.insert(0, p[0])
except Exception: pass
import yfinance as yf
from datetime import datetime, timezone
from collections import defaultdict

args = sys.argv[1:]
def argval(flag, default=None):
    return int(args[args.index(flag)+1]) if flag in args else default

with open('etfs.json') as f: data = json.load(f)

start = argval('--start', 0)
end = argval('--end', len(data['etfs']))
skip_insights = '--start' in args or '--end' in args  # 청크 모드면 인사이트는 마지막에 별도 실행
if '--insights-only' in args:
    start = end = 0; skip_insights = False

# 1) 가격/차트 갱신
for i, e in enumerate(data['etfs'][start:end], start=start):
    t = e['ticker']
    print(f"[{i+1}/{len(data['etfs'])}] {t}", flush=True)
    try:
        tk = yf.Ticker(t)
        h3y = tk.history(period='3y', interval='1wk', auto_adjust=True, actions=False)
        h1y = tk.history(period='1y', interval='1wk', auto_adjust=True, actions=False)
        h3m = tk.history(period='3mo', interval='1d', auto_adjust=True, actions=False)
        hd  = tk.history(period='5d', interval='1d', auto_adjust=True, actions=False)
        if not h3y.empty: e['price_history_3y'] = [round(float(x),4) for x in h3y['Close'].dropna().tolist()]
        if not h1y.empty: e['price_history']    = [round(float(x),4) for x in h1y['Close'].dropna().tolist()]
        if not h3m.empty: e['price_history_3m'] = [round(float(x),4) for x in h3m['Close'].dropna().tolist()]
        if not hd.empty:
            cd = hd['Close'].dropna().tolist()
            if cd:
                last = float(cd[-1])
                if len(cd) >= 2: e['price_change_pct'] = round((cd[-1]/cd[-2]-1)*100, 2)
                e['price_native'] = round(last,0) if e['currency']=='KRW' else round(last,2)
    except Exception as ex:
        print(f"  ! {t}: {ex}", flush=True)

if skip_insights:
    with open('etfs.json','w') as f: json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"청크 저장 완료 ({start}..{end})"); sys.exit(0)

# 2) 인사이트 사전 계산 (프론트엔드 buildInsights와 동일 로직)
def ret(p, n):
    if not p or len(p) < n+1: return None
    a, b = p[-n-1], p[-1]
    if not a or not b: return None
    return (b/a - 1) * 100

def returns(e):
    p1y = e.get('price_history') or []
    p3m = e.get('price_history_3m') or []
    return {
        'week':    ret(p1y, 1),
        'month':   (lambda: ((p3m[-1]/p3m[-22]-1)*100 if len(p3m)>=22 and p3m[-22] else None))(),
        'quarter': (lambda: ((p3m[-1]/p3m[0]-1)*100 if len(p3m)>=2 and p3m[0] else None))(),
        'year':    (lambda: ((p1y[-1]/p1y[0]-1)*100 if len(p1y)>=2 and p1y[0] else None))(),
    }

enriched = []
for e in data['etfs']:
    r = returns(e)
    enriched.append({'name':e['name'],'ticker':e['ticker'],'sector':e.get('sector') or '미분류','naver_code':e.get('naver_code'),'naver_path':e.get('naver_path'), 'r': r})

def avg(xs):
    xs = [x for x in xs if x is not None]
    return (sum(xs)/len(xs)) if xs else None

period_keys = [('week','1주'),('month','1개월'),('quarter','3개월'),('year','1년')]
overview = []
for k,lbl in period_keys:
    arr = [d['r'][k] for d in enriched if d['r'][k] is not None]
    upN = sum(1 for v in arr if v>0)
    overview.append({'label':lbl,'avg':round(avg(arr),3) if arr else None,'breadth':round(upN/len(arr)*100,1) if arr else None,'n':len(arr)})

def sorted_by(k):
    return sorted([d for d in enriched if d['r'][k] is not None], key=lambda d: d['r'][k], reverse=True)

tops = {}
for k,lbl in period_keys:
    s = sorted_by(k)
    tops[k] = {'label':lbl,'top':s[:7],'bot':list(reversed(s[-7:]))}

sec = defaultdict(list)
for d in enriched:
    if d['r']['week'] is not None: sec[d['sector']].append(d)
sector_rank = []
for s, arr in sec.items():
    if len(arr) < 2: continue
    sector_rank.append({
        'sector': s, 'n': len(arr),
        'week':    round(avg([d['r']['week']    for d in arr]),3) if arr else None,
        'month':   round(avg([d['r']['month']   for d in arr if d['r']['month']   is not None]),3) if arr else None,
        'quarter': round(avg([d['r']['quarter'] for d in arr if d['r']['quarter'] is not None]),3) if arr else None,
        'year':    round(avg([d['r']['year']    for d in arr if d['r']['year']    is not None]),3) if arr else None,
    })
sector_rank.sort(key=lambda x: x['week'] if x['week'] is not None else -999, reverse=True)

def filter_set(predicate, sort_key=None, reverse=True, limit=8):
    matches = [d for d in enriched if predicate(d['r'])]
    if sort_key: matches.sort(key=sort_key, reverse=reverse)
    return matches[:limit]

structural = filter_set(
    lambda r: all(r[k] is not None and r[k]>0 for k in ['week','month','quarter','year']),
    lambda d: (d['r']['year'] or 0)+(d['r']['quarter'] or 0)
)
weakness = filter_set(
    lambda r: all(r[k] is not None and r[k]<0 for k in ['week','month','quarter','year']),
    lambda d: (d['r']['year'] or 0)+(d['r']['quarter'] or 0), reverse=False, limit=6
)
accel = filter_set(
    lambda r: r['week'] is not None and r['year'] is not None and r['week']>1 and r['week']*52 - r['year'] > 30,
    lambda d: d['r']['week']*52 - d['r']['year'], limit=6
)
reversal = filter_set(
    lambda r: r['year'] is not None and r['month'] is not None and r['week'] is not None and r['year']>10 and r['month']<-2 and r['week']<-1,
    lambda d: d['r']['month'], reverse=False, limit=6
)
rebound = filter_set(
    lambda r: r['year'] is not None and r['week'] is not None and r['month'] is not None and r['year']<-5 and r['week']>2,
    lambda d: d['r']['week'], limit=6
)

ov_week = overview[0]
verdict = []
if ov_week['avg'] is not None:
    sign = '+' if ov_week['avg']>=0 else ''
    if ov_week['breadth']>=65 and ov_week['avg']>1: mood='강세 우위'
    elif ov_week['breadth']<=35 and ov_week['avg']<-1: mood='약세 우위'
    else: mood='중립/혼조'
    verdict.append(f"주간 평균 {sign}{ov_week['avg']:.2f}% · 상승 비중 {ov_week['breadth']:.0f}% — {mood}")
top_sec = sector_rank[:3]
bot_sec = list(reversed(sector_rank[-3:])) if sector_rank else []
if top_sec: verdict.append("자금 유입: " + ", ".join(f"{s['sector']}({s['week']:+.2f}%)" for s in top_sec))
if bot_sec: verdict.append("자금 이탈: " + ", ".join(f"{s['sector']}({s['week']:+.2f}%)" for s in bot_sec))
if len(structural)>=3: verdict.append(f"구조적 강세 {len(structural)}종목 (4기간 모두 +)")
if len(weakness)>=3: verdict.append(f"구조적 약세 {len(weakness)}종목 (4기간 모두 −)")
if accel: verdict.append(f"모멘텀 가속 {len(accel)}종목")
if reversal: verdict.append(f"조정 진입 {len(reversal)}종목")
if rebound: verdict.append(f"저점 반등 시도 {len(rebound)}종목")

data['insights'] = {
    'computed_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S'),
    'overview': overview,
    'sector_rank': sector_rank,
    'top_week': tops['week']['top'],
    'bot_week': tops['week']['bot'],
    'top_year': tops['year']['top'],
    'bot_year': tops['year']['bot'],
    'structural': structural,
    'weakness': weakness,
    'accel': accel,
    'reversal': reversal,
    'rebound': rebound,
    'verdict': verdict,
}
data['updated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')

with open('etfs.json','w') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print('\n=== 이번 주 인사이트 ===')
for v in verdict: print(' •', v)
print(f"\n상위 5: {[(d['ticker'], round(d['r']['week'],2)) for d in tops['week']['top'][:5]]}")
print(f"하위 5: {[(d['ticker'], round(d['r']['week'],2)) for d in tops['week']['bot'][:5]]}")
