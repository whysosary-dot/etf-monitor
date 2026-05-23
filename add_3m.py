"""Augment existing etfs.json with price_history_3m (daily, ~63 trading days)."""
import sys, os, json, time
sys.path.insert(0, '/sessions/vibrant-nice-franklin/mnt/Claude/.pylibs')
import yfinance as yf

IN = '/sessions/vibrant-nice-franklin/mnt/outputs/etfs.json'
OUT = IN

START = int(sys.argv[1]) if len(sys.argv) > 1 else 0
END = int(sys.argv[2]) if len(sys.argv) > 2 else 10**9

with open(IN) as f:
    data = json.load(f)

etfs = data['etfs']
end = min(END, len(etfs))
print(f"Fetching 3m for [{START}:{end}] of {len(etfs)}", flush=True)

for i in range(START, end):
    e = etfs[i]
    if e.get('price_history_3m'):  # skip already done
        print(f"  skip {e['ticker']}", flush=True)
        continue
    yf_tk = e['ticker']
    print(f"[{i+1}/{len(etfs)}] {yf_tk}", flush=True)
    try:
        tk = yf.Ticker(yf_tk)
        h = tk.history(period="3mo", interval="1d", auto_adjust=True, actions=False)
        if not h.empty:
            e['price_history_3m'] = [round(float(x), 4) for x in h['Close'].dropna().tolist()]
        else:
            e['price_history_3m'] = []
    except Exception as ex:
        print(f"  ! {ex}", flush=True)
        e['price_history_3m'] = []
    # incremental save
    with open(OUT, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

n_ok = sum(1 for e in etfs if e.get('price_history_3m'))
print(f"Done. 3m hist OK: {n_ok}/{len(etfs)}", flush=True)
