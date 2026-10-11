#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ETF Monitor 주간 업데이트
# 사용법: cd <repo> && python3 scripts/weekly_update.py [--start N] [--end M] [--insights-only]
#   --start/--end : yfinance 청크 실행용 (타임아웃 시 분할). 생략하면 전체 + 인사이트 계산.
#   --insights-only : 가격 수집 없이 인사이트(+국내 ETF 유니버스 자금흐름·신규상장·자동편입)만.
#
# 2026-10-11 확장
#  - 국내 상장 ETF 전체(네이버 etfItemList, ~1,170개)를 매주 스냅샷(snapshots/kr_universe/<날짜>.json)으로 남기고
#    직전 스냅샷과 비교해 '추정 순유입(=AUM 변화 − 가격효과)'·신규 상장을 계산
#  - 조건을 넘는 신규/자금 유입 테마 ETF 를 자동 편입(주 3개 상한, auto_added 표시)
#  - 크로스에셋(금리·신용·금·달러·비트코인)·위험선호·환율·섹터 로테이션·52주 신고/신저·개인 심리(레버리지/인버스)
#    를 규칙 기반 해설(narrative) 문장으로 생성 → 대시보드 💡 인사이트 상단에 표시
import sys, json, glob, os, re, urllib.request
try:
    p = glob.glob('/sessions/*/mnt/Claude/.pylibs')
    if p: sys.path.insert(0, p[0])
except Exception: pass
import yfinance as yf
from datetime import datetime, timezone, timedelta
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

KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).strftime('%Y-%m-%d')

def fetch_prices(e):
    t = e['ticker']
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

# 1) 가격/차트 갱신
for i, e in enumerate(data['etfs'][start:end], start=start):
    print(f"[{i+1}/{len(data['etfs'])}] {e['ticker']}", flush=True)
    try: fetch_prices(e)
    except Exception as ex: print(f"  ! {e['ticker']}: {ex}", flush=True)

if skip_insights:
    with open('etfs.json','w') as f: json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"청크 저장 완료 ({start}..{end})"); sys.exit(0)

# ─────────────────────────────────────────────────────────────
# 2) 국내 상장 ETF 유니버스 — 자금흐름·신규상장·놓친 ETF·자동 편입
# ─────────────────────────────────────────────────────────────
TAB = {1:'국내 시장지수',2:'국내 업종/테마',3:'국내 파생',4:'해외 주식',5:'원자재',6:'채권',7:'기타(혼합·TDF 등)'}
EXCL_KW = ['레버리지','인버스','커버드콜','채권','혼합','TDF','머니마켓','CD금리','KOFR','국채','회사채','금융채','통안','단기','만기','TRF','타겟데일리','타겟위클리','합성','선물','2X','(H)']

def fetch_universe():
    url = 'https://finance.naver.com/api/sise/etfItemList.nhn?etfType=0&targetColumn=market_sum&sortOrder=desc'
    req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
    raw = urllib.request.urlopen(req, timeout=20).read()
    try: txt = raw.decode('utf-8')
    except UnicodeDecodeError: txt = raw.decode('euc-kr', 'replace')
    items = json.loads(txt)['result']['etfItemList']
    out = {}
    for i in items:
        out[i['itemcode']] = [i['itemname'], i.get('etfTabCode'), i.get('marketSum') or 0, i.get('amonut') or 0,
                              i.get('nowVal') or 0, round(i.get('threeMonthEarnRate') or 0, 2)]
    return out   # code -> [name, tab, AUM(억), 거래대금(백만원), 현재가, 3개월%]

def code_order(c):   # KRX 신규 코드(0xxxY0)는 숫자가 클수록 최근 상장
    m = re.match(r'^0(\d{3})([A-Z])0$', c)
    return (int(m.group(1)), m.group(2)) if m else None

uni = {}; uni_prev = {}; prev_date = None; flows = {}
try:
    uni = fetch_universe()
    os.makedirs('snapshots/kr_universe', exist_ok=True)
    olds = sorted(p for p in glob.glob('snapshots/kr_universe/*.json') if os.path.basename(p)[:10] < TODAY)
    if olds:
        prev_date = os.path.basename(olds[-1])[:10]
        uni_prev = json.load(open(olds[-1]))
    with open(f'snapshots/kr_universe/{TODAY}.json','w') as f: json.dump(uni, f, ensure_ascii=False, separators=(',',':'))
    for c, v in uni.items():
        pv = uni_prev.get(c)
        if pv and pv[4] and v[4]:
            flows[c] = round(v[2] - pv[2] * (v[4] / pv[4]), 1)   # 추정 순유입(억) = AUM 변화 − 가격효과
    print(f"KR 유니버스 {len(uni)}개 (직전 {prev_date or '없음'})")
except Exception as ex:
    print('  ! KR 유니버스 수집 실패:', ex)

tracked_codes = {e['ticker'].split('.')[0] for e in data['etfs']}
def excluded_name(n): return any(k in n for k in EXCL_KW)
BRAND = r'^(KODEX|TIGER|ACE|SOL|RISE|PLUS|HANARO|KIWOOM|TIME|KoAct|1Q|IBK|BNK|WON|파워|마이다스|MIDAS|마이티|UNICORN|에셋플러스|TRUSTON|DAISHIN343|히어로즈|VITA|ITF|KCGI)\s*'
def core(n): return re.sub(BRAND, '', n or '').replace(' ', '')
tracked_cores = {core(e['name']) for e in data['etfs'] if re.search('[가-힣]', e['name'] or '')}

SECTOR_KW = [('HBM','반도체'),('반도체','반도체'),('원자력','원자력'),('SMR','원자력'),('방산','방산/우주'),('우주','방산/우주'),
             ('조선','조선'),('휴머노이드','AI/로봇'),('로봇','AI/로봇'),('전력','전력/인프라'),('바이오','바이오/제약'),('헬스','헬스케어'),
             ('2차전지','2차전지'),('배터리','2차전지'),('금현물','금'),('골드','금'),('양자','양자컴퓨팅'),('광통신','광통신'),
             ('차이나','중국 테크'),('중국','중국 테크'),('S&P500','해외투자(국내상장)'),('나스닥','해외투자(국내상장)'),
             ('배당','금융/배당'),('은행','금융'),('증권','금융'),('금융','금융'),('게임','게임/엔터'),('엔터','엔터/콘텐츠'),
             ('콘텐츠','엔터/콘텐츠'),('자동차','자동차'),('현대차','자동차'),('AI','AI/로봇')]
def guess_sector(n):
    for k, s in SECTOR_KW:
        if k in n: return s
    return '신규 테마'

new_listings = []
if uni_prev:
    for c, v in uni.items():
        if c not in uni_prev:
            new_listings.append({'code':c,'name':v[0],'tab':TAB.get(v[1],''),'aum':v[2],'amt':v[3],'r3m':v[5]})
    new_listings.sort(key=lambda x: -x['aum'])
recent = sorted([c for c in uni if code_order(c) and not excluded_name(uni[c][0]) and uni[c][1] != 7], key=lambda c: code_order(c), reverse=True)[:15]
recent_listed = [{'code':c,'name':uni[c][0],'tab':TAB.get(uni[c][1],''),'aum':uni[c][2],'amt':uni[c][3],'r3m':uni[c][5],
                  'flow':flows.get(c),'tracked':c in tracked_codes} for c in recent]

def urow(c):
    v = uni[c]
    return {'code':c,'name':v[0],'tab':TAB.get(v[1],''),'aum':v[2],'amt':v[3],'r3m':v[5],'flow':flows.get(c),'tracked':c in tracked_codes}

flow_top = flow_bot = []; flow_groups = []
if flows:
    srt = sorted(flows.items(), key=lambda kv: kv[1], reverse=True)
    flow_top = [urow(c) for c, f in srt[:12] if f > 0]
    flow_bot = [urow(c) for c, f in reversed(srt[-12:]) if f < 0]
    groups = [('대기자금(CD·KOFR·머니마켓·초단기)', lambda n,t: any(k in n for k in ['CD금리','KOFR','머니마켓','초단기','단기채','단기통안'])),
              ('레버리지(국내)', lambda n,t: '레버리지' in n and t in (1,2,3)),
              ('인버스(국내)', lambda n,t: '인버스' in n),
              ('미국 지수(S&P500·나스닥100)', lambda n,t: t==4 and any(k in n for k in ['S&P500','나스닥100']) and '커버드콜' not in n and '혼합' not in n),
              ('반도체(국내·해외)', lambda n,t: '반도체' in n or 'HBM' in n),
              ('금·원자재', lambda n,t: t==5),
              ('커버드콜', lambda n,t: '커버드콜' in n),
              ('채권(대기자금 제외)', lambda n,t: t==6 and not any(k in n for k in ['CD금리','KOFR','머니마켓','초단기'])),
              ('국내 시장지수', lambda n,t: t==1 and '레버리지' not in n),
              ('국내 업종/테마', lambda n,t: t==2 and not any(k in n for k in ['레버리지','인버스','커버드콜'])),
              ('해외 주식(전체)', lambda n,t: t==4)]
    for g, fn in groups:
        cs = [c for c in flows if fn(uni[c][0], uni[c][1])]
        if not cs: continue
        tot = sum(flows[c] for c in cs)
        aum = sum(uni[c][2] for c in cs)
        best = max(cs, key=lambda c: flows[c]); worst = min(cs, key=lambda c: flows[c])
        flow_groups.append({'group':g,'n':len(cs),'flow':round(tot,1),'aum':aum,'pct':round(tot/aum*100,2) if aum else None,
                            'best':[uni[best][0], flows[best]], 'worst':[uni[worst][0], flows[worst]]})
    flow_groups.sort(key=lambda x: -x['flow'])

# 놓친 ETF 후보: 미편입 · 테마/해외/원자재 · 상품성 키워드 제외 · (자금유입 우선, 없으면 거래대금)
cands = [c for c in uni if c not in tracked_codes and uni[c][1] in (2,4,5) and not excluded_name(uni[c][0]) and uni[c][2] >= 300
         and core(uni[c][0]) not in tracked_cores]
if flows: cands.sort(key=lambda c: -(flows.get(c) or -1e9))
else:     cands.sort(key=lambda c: -uni[c][3])
missed = [urow(c) for c in cands[:12]]

# 자동 편입 (직전 스냅샷이 있을 때만 — 근거가 '자금 유입'이어야 함)
auto_added = []
if flows:
    for c in cands:
        if len(auto_added) >= 3: break
        v = uni[c]; f = flows.get(c) or 0
        is_new = c in {x['code'] for x in new_listings}
        if f >= 300 or (is_new and v[2] >= 300):
            # 이미 편입된 같은 테마(이름 앞 브랜드 제외 핵심어 중복)면 건너뜀
            if core(v[0]) in tracked_cores: continue
            e = {'name':v[0],'ticker':c+'.KS','category':'한국 ETF','description':f"자동 편입 {TODAY} — " + ('신규 상장' if is_new else f'주간 추정 순유입 {f:,.0f}억'),
                 'sector':guess_sector(v[0]),'currency':'KRW','price_native':v[4],'price_change_pct':None,'price_history':[],'price_history_3y':[],
                 'price_history_3m':[],'naver_code':c,'naver_path':'domestic/stock','favorite':False,'memo':'','auto_added':TODAY,'added_at':TODAY}
            try: fetch_prices(e)
            except Exception as ex: print('  ! 자동편입 가격 실패', c, ex)
            data['etfs'].append(e); tracked_codes.add(c); tracked_cores.add(core(v[0]))
            auto_added.append({'code':c,'name':v[0],'sector':e['sector'],'reason':e['description'],'aum':v[2],'flow':f})
            print('  + 자동 편입:', c, v[0], e['sector'])

# 가격이 비어 있는 종목(새로 추가된 것 등)은 여기서 채운다
for e in data['etfs']:
    if not e.get('price_history'):
        try: fetch_prices(e); print('  · 가격 보충', e['ticker'])
        except Exception as ex: print('  ! 가격 보충 실패', e['ticker'], ex)

# ─────────────────────────────────────────────────────────────
# 3) 인사이트 사전 계산
# ─────────────────────────────────────────────────────────────
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
        'year':    (lambda: ((p1y[-1]/p1y[0]-1)*100 if len(p1y)>=40 and p1y[0] else None))(),
    }

NON_EQ = {'크로스에셋','심리 지표'}   # 주식 시장 통계(평균·섹터·TOP)에서 제외 — 별도 섹션
enriched_all = []
for e in data['etfs']:
    r = returns(e)
    p1y = [x for x in (e.get('price_history') or []) if x]
    pos52 = None
    if len(p1y) >= 20:
        hi, lo = max(p1y), min(p1y)
        pos52 = round((p1y[-1]-lo)/(hi-lo)*100, 1) if hi > lo else None
    nm = e['name'] or ''
    short = nm if (re.search('[가-힣]', nm) and len(nm) <= 22) else (e.get('description') or nm)[:18] if e['ticker'].endswith('.KS') else e['ticker']
    enriched_all.append({'name':e['name'],'short':short,'ticker':e['ticker'],'sector':e.get('sector') or '미분류','category':e.get('category',''),
                         'naver_code':e.get('naver_code'),'naver_path':e.get('naver_path'),'r': r,'pos52':pos52,
                         'dd': round((p1y[-1]/max(p1y)-1)*100,1) if p1y else None})
enriched = [d for d in enriched_all if d['category'] not in NON_EQ]
by_t = {d['ticker']: d for d in enriched_all}

def avg(xs):
    xs = [x for x in xs if x is not None]
    return (sum(xs)/len(xs)) if xs else None
def f2(x, s=True): return '—' if x is None else (f"{x:+.1f}%" if s else f"{x:.1f}%")

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
        'week':    round(avg([d['r']['week']    for d in arr]),3),
        'month':   round(avg([d['r']['month']   for d in arr]),3) if avg([d['r']['month'] for d in arr]) is not None else None,
        'quarter': round(avg([d['r']['quarter'] for d in arr]),3) if avg([d['r']['quarter'] for d in arr]) is not None else None,
        'year':    round(avg([d['r']['year']    for d in arr]),3) if avg([d['r']['year'] for d in arr]) is not None else None,
    })
sector_rank.sort(key=lambda x: x['week'] if x['week'] is not None else -999, reverse=True)

def filter_set(predicate, sort_key=None, reverse=True, limit=8):
    matches = [d for d in enriched if predicate(d['r'])]
    if sort_key: matches.sort(key=sort_key, reverse=reverse)
    return matches[:limit]
structural = filter_set(lambda r: all(r[k] is not None and r[k]>0 for k in ['week','month','quarter','year']),
                        lambda d: (d['r']['year'] or 0)+(d['r']['quarter'] or 0))
weakness = filter_set(lambda r: all(r[k] is not None and r[k]<0 for k in ['week','month','quarter','year']),
                      lambda d: (d['r']['year'] or 0)+(d['r']['quarter'] or 0), reverse=False, limit=6)
accel = filter_set(lambda r: r['week'] is not None and r['year'] is not None and r['week']>1 and r['week']*52 - r['year'] > 30,
                   lambda d: d['r']['week']*52 - d['r']['year'], limit=6)
reversal = filter_set(lambda r: r['year'] is not None and r['month'] is not None and r['week'] is not None and r['year']>10 and r['month']<-2 and r['week']<-1,
                      lambda d: d['r']['month'], reverse=False, limit=6)
rebound = filter_set(lambda r: r['year'] is not None and r['week'] is not None and r['month'] is not None and r['year']<-5 and r['week']>2,
                     lambda d: d['r']['week'], limit=6)

# 52주 위치
highs = sorted([d for d in enriched if d['pos52'] is not None and d['pos52'] >= 95], key=lambda d: -(d['r']['quarter'] or 0))[:10]
lows  = sorted([d for d in enriched if d['pos52'] is not None and d['pos52'] <= 5],  key=lambda d: (d['r']['quarter'] or 0))[:10]

# 섹터 로테이션: 1개월 순위 vs 3개월 순위
rot = [s for s in sector_rank if s['month'] is not None and s['quarter'] is not None]
rm = {s['sector']: i+1 for i, s in enumerate(sorted(rot, key=lambda s: -s['month']))}
rq = {s['sector']: i+1 for i, s in enumerate(sorted(rot, key=lambda s: -s['quarter']))}
rotation = sorted([{'sector':s['sector'],'rank_m':rm[s['sector']],'rank_q':rq[s['sector']],'chg':rq[s['sector']]-rm[s['sector']],
                    'month':s['month'],'quarter':s['quarter']} for s in rot], key=lambda x: -x['chg'])
rot_up = [x for x in rotation if x['chg'] >= 5][:6]
rot_dn = [x for x in reversed(rotation) if x['chg'] <= -5][:6]

# 크로스에셋 · 위험선호
def rr(t, k): d = by_t.get(t); return d['r'][k] if d else None
CROSS = [('TLT','미국 장기국채','오르면 장기금리 하락'),('HYG','하이일드 회사채','오르면 신용위험 선호'),('GLD','금(달러)','안전자산·실질금리'),
         ('411060.KS','금현물(원화)','국내 개인 금 수요'),('UUP','달러 인덱스','오르면 달러 강세'),('IBIT','비트코인','투기적 위험선호'),
         ('EWY','한국(달러)','외국인 시각의 한국'),('069500.KS','코스피200(원화)','국내 시각의 한국')]
cross = [{'ticker':t,'label':l,'hint':h,'name':(by_t.get(t) or {}).get('name',''),'r':(by_t.get(t) or {}).get('r'),'pos52':(by_t.get(t) or {}).get('pos52')}
         for t,l,h in CROSS if by_t.get(t)]
RISK_ON  = ['SMH','XLK','ARKK','IWM','XLY','KWEB','IBIT','HYG']
RISK_OFF = ['XLP','XLU','TLT','GLD','UUP','XLV']
def spread(k):
    a = avg([rr(t,k) for t in RISK_ON]); b = avg([rr(t,k) for t in RISK_OFF])
    return None if a is None or b is None else round(a-b, 2)
risk = {'week':spread('week'),'month':spread('month'),'quarter':spread('quarter'),
        'on':[[t, rr(t,'week'), rr(t,'month')] for t in RISK_ON if t in by_t],
        'off':[[t, rr(t,'week'), rr(t,'month')] for t in RISK_OFF if t in by_t]}

# 국내 vs 해외
kr_eq = [d for d in enriched if d['category']=='한국 ETF' and d['sector']!='해외투자(국내상장)']
us_eq = [d for d in enriched if d['category']!='한국 ETF']

# 개인 심리 (레버리지/인버스)
SENT = [('122630','코스피 레버리지'),('233740','코스닥 레버리지'),('0193T0','SK하이닉스 2배'),('252670','코스피 곱버스(-2배)'),('114800','코스피 인버스')]
sentiment = [{'code':c,'label':l,'flow':flows.get(c),'aum':uni.get(c,[None,None,None])[2] if uni.get(c) else None,
              'amt':uni.get(c,[0,0,0,0])[3] if uni.get(c) else None,'r':(by_t.get(c+'.KS') or {}).get('r')} for c,l in SENT]

# ── 해설 문장 (규칙 기반) ──
narr = []
ow, om, oq, oy = overview
mood = '강세 우위' if ow['breadth'] and ow['breadth']>=65 and ow['avg']>1 else '약세 우위' if ow['breadth'] is not None and ow['breadth']<=35 and ow['avg']<-1 else '중립/혼조'
t = f"주식형 {ow['n']}개 ETF 주간 평균 {f2(ow['avg'])}, 상승 비중 {ow['breadth']:.0f}% → {mood}. "
t += f"1개월 {f2(om['avg'])}(상승 {om['breadth']:.0f}%), 3개월 {f2(oq['avg'])}(상승 {oq['breadth']:.0f}%), 1년 {f2(oy['avg'])}. "
if om['avg'] is not None and oq['avg'] is not None:
    if om['avg'] < 0 and oq['avg'] < 0 and (oy['avg'] or 0) > 10: t += "장기 상승 추세 안의 중기 조정 국면 — 1년 수익은 남아 있지만 최근 3개월은 대부분이 쉬고 있다. "
    elif om['avg'] > 0 and oq['avg'] < 0: t += "3개월 조정 뒤 최근 1개월 반등 — 반등의 폭(breadth)이 넓어지는지가 다음 확인 포인트. "
    elif om['avg'] > 0 and oq['avg'] > 0: t += "중기 추세도 우상향 — 주도 섹터 집중 여부만 체크. "
if ow['breadth'] is not None and om['breadth'] is not None and ow['breadth'] - om['breadth'] >= 15:
    t += "이번 주 상승 종목 비중이 1개월 기준보다 뚜렷이 넓어졌다(바닥 확인 시도 신호일 수 있음)."
narr.append({'title':'🌡 시장 체온','body':t})

if risk['week'] is not None:
    w, m = risk['week'], risk['month']
    lab = lambda x: '위험선호(Risk-on)' if x > 1 else '위험회피(Risk-off)' if x < -1 else '중립'
    t = f"성장·경기민감 바스켓({', '.join(RISK_ON)}) − 방어 바스켓({', '.join(RISK_OFF)}) 수익률 차이: 1주 {w:+.2f}%p({lab(w)}), 1개월 {m:+.2f}%p({lab(m) if m is not None else '—'}). "
    if m is not None and w > 1 and m < -1: t += "한 달간 방어 우위였다가 이번 주 위험선호로 돌아섰다 — 전환 초입인지 기술적 반등인지는 다음 주 지속 여부로 판단."
    elif m is not None and w < -1 and m > 1: t += "한 달 내내 위험선호였는데 이번 주 방어로 돌아섰다 — 차익실현/이벤트 리스크 점검 구간."
    elif m is not None and w > 1 and m > 1: t += "위험선호가 1주·1개월 모두 유지 — 추세 지속 구간."
    elif m is not None and w < -1 and m < -1: t += "방어 우위가 1주·1개월 모두 이어짐 — 공격적 비중 확대는 보수적으로."
    narr.append({'title':'⚖️ 위험 선호 vs 회피','body':t})

def cx(tk): return rr(tk,'week'), rr(tk,'month')
tl, hy, gd, ud, bt = cx('TLT'), cx('HYG'), cx('GLD'), cx('UUP'), cx('IBIT')
parts = []
if tl[0] is not None: parts.append(f"장기국채(TLT) 1주 {f2(tl[0])}·1개월 {f2(tl[1])} → " + ('장기금리 하락(채권 강세)' if tl[0] > 0.5 else '장기금리 상승(성장주 할인율 부담)' if tl[0] < -0.5 else '금리 보합'))
if hy[0] is not None and tl[0] is not None:
    gap = (hy[1] or 0) - (tl[1] or 0)
    parts.append(f"하이일드(HYG) 1개월 {f2(hy[1])} vs 국채 {f2(tl[1])} → " + ('신용 스프레드 축소(위험 선호)' if gap > 0.5 else '신용 스프레드 확대(위험 회피)' if gap < -0.5 else '신용 여건 중립'))
if gd[0] is not None: parts.append(f"금(GLD) 1주 {f2(gd[0])}·1개월 {f2(gd[1])}" + (' — 안전자산 수요 강함' if (gd[1] or 0) > 3 else ' — 금 조정' if (gd[1] or 0) < -3 else ''))
if ud[0] is not None: parts.append(f"달러(UUP) 1주 {f2(ud[0])}·1개월 {f2(ud[1])} → " + ('달러 강세 — 신흥국·원화 자산에 역풍' if (ud[1] or 0) > 1 else '달러 약세 — 신흥국·원자재에 우호' if (ud[1] or 0) < -1 else '달러 보합'))
if bt[0] is not None: parts.append(f"비트코인(IBIT) 1주 {f2(bt[0])}·1개월 {f2(bt[1])}" + (' — 투기적 위험선호 회복' if (bt[0] or 0) > 5 else ' — 투기 심리 위축' if (bt[0] or 0) < -5 else ''))
if parts: narr.append({'title':'🌐 크로스에셋 (금리·신용·금·달러·코인)','body':' / '.join(parts)})

ew, k2 = cx('EWY'), cx('069500.KS')
if ew[0] is not None and k2[0] is not None:
    fx = ew[0]-k2[0]; fxm = (ew[1] or 0)-(k2[1] or 0)
    t = (f"EWY(달러) 1주 {f2(ew[0])} vs KODEX200(원화) {f2(k2[0])} → 차이 {fx:+.1f}%p ≈ 원화 " + ('강세(외국인 입장 추가 수익)' if fx > 0.5 else '약세(외국인 입장 환손실)' if fx < -0.5 else '보합'))
    t += f". 1개월 기준 차이 {fxm:+.1f}%p. "
    ka, ua = avg([d['r']['week'] for d in kr_eq]), avg([d['r']['week'] for d in us_eq])
    if ka is not None and ua is not None:
        t += f"국내 상장 국내주식 ETF 평균 {f2(ka)} vs 해외 ETF 평균 {f2(ua)} — " + ('한국 상대 강세' if ka-ua > 1 else '한국 상대 약세' if ka-ua < -1 else '비슷') + '.'
    narr.append({'title':'🇰🇷 한국 vs 해외 · 환율','body':t})

if rot_up or rot_dn:
    t = ''
    if rot_up: t += "새로 치고 올라온 섹터(3개월 순위 → 1개월 순위): " + ', '.join(f"{x['sector']}({x['rank_q']}→{x['rank_m']}위, 1M {f2(x['month'])})" for x in rot_up[:4]) + '. '
    if rot_dn: t += "힘이 빠지는 기존 주도 섹터: " + ', '.join(f"{x['sector']}({x['rank_q']}→{x['rank_m']}위, 1M {f2(x['month'])})" for x in rot_dn[:4]) + '. '
    t += "순위가 크게 바뀐 섹터는 자금이 옮겨가는 중이라는 뜻 — 1~2주 더 유지되면 로테이션으로 본다."
    narr.append({'title':'🔄 섹터 로테이션','body':t})

if flows:
    t = f"국내 상장 ETF {len(flows)}개 기준, {prev_date} 대비 추정 순유입(AUM 변화에서 가격효과 제외). "
    if flow_groups:
        t += '그룹별: ' + ', '.join(f"{g['group']} {g['flow']:+,.0f}억" for g in flow_groups[:4]) + ' … ' + ', '.join(f"{g['group']} {g['flow']:+,.0f}억" for g in flow_groups[-2:]) + '. '
    if flow_top: t += f"최대 유입 {flow_top[0]['name']} {flow_top[0]['flow']:+,.0f}억, "
    if flow_bot: t += f"최대 유출 {flow_bot[0]['name']} {flow_bot[0]['flow']:+,.0f}억. "
    wait = next((g for g in flow_groups if g['group'].startswith('대기자금')), None)
    if wait: t += ("대기자금 ETF로 돈이 쌓이는 중(관망)" if wait['flow'] > 500 else "대기자금 ETF에서 돈이 빠져나가는 중(주식 재투입 가능성)" if wait['flow'] < -500 else "대기자금 흐름은 잠잠") + '.'
    narr.append({'title':'💸 국내 ETF 자금 흐름','body':t})
else:
    narr.append({'title':'💸 국내 ETF 자금 흐름','body':f"국내 상장 ETF 전체({len(uni)}개) 기준 스냅샷을 {TODAY}부터 쌓기 시작했습니다. 다음 주 갱신부터 주간 추정 순유입(AUM 변화 − 가격효과)·신규 상장 비교가 표시됩니다."})

s_txt = []
for s in sentiment:
    bits = []
    if s['flow'] is not None: bits.append(f"순유입 {s['flow']:+,.0f}억")
    if s['amt']: bits.append(f"거래대금 {s['amt']/100:,.0f}억")
    if s['r'] and s['r'].get('week') is not None: bits.append(f"1주 {f2(s['r']['week'])}")
    if bits: s_txt.append(f"{s['label']}: " + ' · '.join(bits))
if s_txt:
    t = ' / '.join(s_txt)
    lev = [s['flow'] for s in sentiment[:3] if s['flow'] is not None]; inv = [s['flow'] for s in sentiment[3:] if s['flow'] is not None]
    if lev and inv:
        if sum(lev) > 0 and sum(inv) < 0: t += " → 개인이 상승 쪽에 베팅(레버리지 유입·인버스 유출) — 과열 여부 점검."
        elif sum(lev) < 0 and sum(inv) > 0: t += " → 개인이 하락 쪽에 베팅(인버스 유입) — 역발상으로 보면 바닥 신호일 수 있음."
    narr.append({'title':'🎲 개인 심리 (레버리지·인버스)','body':t})

if highs or lows:
    t = ''
    if highs: t += f"52주 고점 부근(위치 95%+) {len(highs)}개: " + ', '.join(d['short'] for d in highs[:8]) + '. '
    if lows:  t += f"52주 저점 부근(5% 이하) {len(lows)}개: " + ', '.join(d['short'] for d in lows[:8]) + '. '
    t += "고점 부근이 많고 저점 부근이 적으면 추세장, 반대면 약세장 성격."
    narr.append({'title':'🏔 52주 신고가·신저가','body':t})

if auto_added:
    narr.append({'title':'➕ 이번 주 자동 편입','body':', '.join(f"{a['name']}({a['reason']})" for a in auto_added)})

verdict = []
if ow['avg'] is not None:
    verdict.append(f"주간 평균 {'+' if ow['avg']>=0 else ''}{ow['avg']:.2f}% · 상승 비중 {ow['breadth']:.0f}% — {mood}")
top_sec = sector_rank[:3]; bot_sec = list(reversed(sector_rank[-3:])) if sector_rank else []
if top_sec: verdict.append("강세 섹터: " + ", ".join(f"{s['sector']}({s['week']:+.2f}%)" for s in top_sec))
if bot_sec: verdict.append("약세 섹터: " + ", ".join(f"{s['sector']}({s['week']:+.2f}%)" for s in bot_sec))
if risk['week'] is not None: verdict.append(f"위험선호 스프레드 1주 {risk['week']:+.2f}%p · 1개월 {risk['month']:+.2f}%p" if risk['month'] is not None else f"위험선호 스프레드 1주 {risk['week']:+.2f}%p")
if len(structural)>=3: verdict.append(f"구조적 강세 {len(structural)}종목 (4기간 모두 +)")
if len(weakness)>=3: verdict.append(f"구조적 약세 {len(weakness)}종목 (4기간 모두 −)")
if accel: verdict.append(f"모멘텀 가속 {len(accel)}종목")
if reversal: verdict.append(f"조정 진입 {len(reversal)}종목")
if rebound: verdict.append(f"저점 반등 시도 {len(rebound)}종목")

data['insights'] = {
    'computed_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S'),
    'overview': overview, 'sector_rank': sector_rank,
    'top_week': tops['week']['top'], 'bot_week': tops['week']['bot'],
    'top_year': tops['year']['top'], 'bot_year': tops['year']['bot'],
    'structural': structural, 'weakness': weakness, 'accel': accel, 'reversal': reversal, 'rebound': rebound,
    'verdict': verdict, 'mood': mood,
    'narrative': narr, 'cross': cross, 'risk': risk,
    'rotation_up': rot_up, 'rotation_dn': rot_dn, 'highs': highs, 'lows': lows,
    'flows': {'prev_date': prev_date, 'date': TODAY, 'n': len(uni), 'top': flow_top, 'bot': flow_bot, 'groups': flow_groups},
    'new_listings': new_listings[:15], 'recent_listed': recent_listed, 'missed': missed, 'auto_added': auto_added,
    'sentiment': sentiment,
}
data['updated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
with open('etfs.json','w') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

# 날짜별 스냅샷 보관 (대시보드 ◀ 날짜 ▶ 선택용)
os.makedirs('snapshots', exist_ok=True)
with open(f'snapshots/{TODAY}.json', 'w') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
_ip = 'snapshots/index.json'
try: _idx = json.load(open(_ip))
except Exception: _idx = {'dates': []}
_idx['dates'] = sorted(set(_idx.get('dates', [])) | {TODAY}, reverse=True)
with open(_ip, 'w') as f: json.dump(_idx, f, ensure_ascii=False, indent=1)
print(f'snapshot saved: snapshots/{TODAY}.json ({len(_idx["dates"])} dates)')
try:
    import subprocess
    subprocess.run(['git', 'add', 'snapshots', 'etfs.json'], check=False, capture_output=True)
except Exception: pass

print('\n=== 이번 주 인사이트 ===')
for v in verdict: print(' •', v)
for n in narr: print(f"\n[{n['title']}]\n{n['body']}")
if auto_added: print('\n자동 편입:', [(a['code'], a['name']) for a in auto_added])
print(f"\n상위 5: {[(d['ticker'], round(d['r']['week'],2)) for d in tops['week']['top'][:5]]}")
print(f"하위 5: {[(d['ticker'], round(d['r']['week'],2)) for d in tops['week']['bot'][:5]]}")
