"""Resolve correct Naver reutersCode for each ETF — store in `naver_code` field."""
import json, urllib.request, time

IN = '/sessions/vibrant-nice-franklin/mnt/outputs/etfs.json'
OUT = IN

with open(IN) as f:
    data = json.load(f)

def probe(tk):
    """Return correct Naver code or None."""
    candidates = [tk, f"{tk}.O", f"{tk}.K", f"{tk}.N"]
    for c in candidates:
        url = f"https://api.stock.naver.com/etf/{c}/basic"
        try:
            req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as r:
                body = json.loads(r.read())
            if body.get('stockName'):
                return body.get('reutersCode') or c
        except Exception:
            pass
    return None

ok = 0; fail = []
for i, e in enumerate(data['etfs']):
    tk = e['ticker']
    if tk.endswith('.KS') or tk.endswith('.KQ'):
        # Korean ETFs: domestic stock code (6 digits)
        code = tk.split('.')[0]
        e['naver_code'] = code
        e['naver_path'] = 'domestic/stock'
        ok += 1
        continue
    # US/overseas ETF: probe API
    print(f"[{i+1}/{len(data['etfs'])}] probing {tk}...", flush=True)
    code = probe(tk)
    if code:
        e['naver_code'] = code
        e['naver_path'] = 'worldstock/etf'
        ok += 1
    else:
        fail.append(tk)
        e['naver_code'] = tk  # fallback
        e['naver_path'] = 'worldstock/etf'
    time.sleep(0.05)

with open(OUT, 'w') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"\nResolved {ok}/{len(data['etfs'])}.")
if fail:
    print(f"Failed: {fail}")
