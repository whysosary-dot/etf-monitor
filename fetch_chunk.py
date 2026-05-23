"""Fetch one chunk of ETFs and append to checkpoint.

Usage: python3 fetch_chunk.py <start> <end>
"""
import sys, os, json, time
from datetime import datetime, timezone
sys.path.insert(0, '/sessions/vibrant-nice-franklin/mnt/Claude/.pylibs')
import yfinance as yf

from etfs_seed import ETFS

CKPT = '/sessions/vibrant-nice-franklin/mnt/outputs/etfs_ckpt.json'
START = int(sys.argv[1]) if len(sys.argv) > 1 else 0
END = int(sys.argv[2]) if len(sys.argv) > 2 else len(ETFS)

# Load checkpoint
if os.path.exists(CKPT):
    data = json.load(open(CKPT))
else:
    data = {"updated_at": "", "etfs": []}
have = {r["ticker"] for r in data["etfs"]}

batch = ETFS[START:END]
for i, t in enumerate(batch):
    yf_tk = t["ticker"]
    if yf_tk in have:
        print(f"  skip {yf_tk} (already cached)", flush=True)
        continue
    print(f"[{START+i+1}/{len(ETFS)}] {yf_tk} {t['name'][:40]}", flush=True)
    rec = {
        "name": t["name"], "ticker": yf_tk, "category": t["category"],
        "description": t["description"], "sector": t["sector"],
        "currency": "KRW" if yf_tk.endswith(".KS") or yf_tk.endswith(".KQ") else "USD",
        "price_native": None, "price_change_pct": None,
        "price_history": [], "price_history_3y": [], "favorite": False,
    }
    try:
        tk = yf.Ticker(yf_tk)
        h3 = tk.history(period="3y", interval="1wk", auto_adjust=True, actions=False)
        h1 = tk.history(period="1y", interval="1wk", auto_adjust=True, actions=False)
        hd = tk.history(period="5d", interval="1d", auto_adjust=True, actions=False)
        if not h3.empty:
            rec["price_history_3y"] = [round(float(x), 4) for x in h3["Close"].dropna().tolist()]
        if not h1.empty:
            rec["price_history"] = [round(float(x), 4) for x in h1["Close"].dropna().tolist()]
        if not hd.empty:
            cd = hd["Close"].dropna().tolist()
            if cd:
                last = float(cd[-1])
                if len(cd) >= 2:
                    rec["price_change_pct"] = round((cd[-1]/cd[-2]-1)*100, 2)
                rec["price_native"] = round(last, 0) if rec["currency"] == "KRW" else round(last, 2)
        if rec["price_native"] is None and rec["price_history"]:
            last = rec["price_history"][-1]
            rec["price_native"] = round(last, 0) if rec["currency"] == "KRW" else round(last, 2)
    except Exception as e:
        print(f"  ! {yf_tk}: {e}", flush=True)
    data["etfs"].append(rec)
    have.add(yf_tk)
    # save every record
    data["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    with open(CKPT, "w") as f:
        json.dump(data, f, ensure_ascii=False)

n_ok = sum(1 for r in data["etfs"] if r["price_native"] is not None)
print(f"\nCkpt {len(data['etfs'])}/{len(ETFS)}, price OK {n_ok}", flush=True)
