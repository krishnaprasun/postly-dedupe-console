#!/usr/bin/env python3
"""Assemble the review dataset: clusters.json + the frames the console needs.

Source of truth is the analysis output in the scratchpad; this copies only the
frames belonging to rows that actually appear in a cluster (a few hundred MB of
the 516MB capture), so the console is self-contained and survives scratchpad
cleanup.
"""
import csv, json, shutil, sys
from collections import defaultdict
from pathlib import Path

SRC  = Path(sys.argv[1] if len(sys.argv) > 1 else
            "/private/tmp/claude-501/-Users-krishnaprasun/7a7860c6-4228-44a0-93d1-a30ebfcb7759/scratchpad")
HERE = Path(__file__).resolve().parent
DATA = HERE / "data"; DATA.mkdir(exist_ok=True)
FR   = DATA / "frames"; FR.mkdir(exist_ok=True)
csv.field_size_limit(10**9)

def rd(p):
    rows = list(csv.reader(open(p, newline='', encoding='utf-8')))
    return rows[0], rows[1:]

# ---- duplicate clusters -----------------------------------------------------
_, dup = rd(SRC / "postly_duplicate_content.csv")
cl = defaultdict(list)
for r in dup: cl[r[0]].append(r)

def i(x):
    try: return int(x)
    except Exception: return 0

clusters = []
for k, v in cl.items():
    members = [{
        "row": i(m[3]), "serial": m[4], "date": m[5], "sub": m[6], "vendor": m[7] or "-",
        "shares": i(m[8]), "downloads": i(m[9]), "path": m[10], "link": m[11],
        "suggested": m[2],
    } for m in v]
    members.sort(key=lambda m: (m["suggested"] != "KEEP", -(m["shares"] + m["downloads"])))
    clusters.append({
        "id": k, "size": len(v),
        "cross_vendor": v[0][12] == "YES",
        "cross_sub":    v[0][13] == "YES",
        "detection":    v[0][14],
        "date_variant": v[0][15] == "DATE-VARIANT-REVIEW",
        "members": members,
    })
# hardest/highest-value first: different-files and cross-vendor before the obvious ones
clusters.sort(key=lambda c: (c["date_variant"], c["detection"] != "DIFFERENT-FILES",
                             not c["cross_vendor"], -c["size"]))

# ---- background reuse (view-only) ------------------------------------------
_, bg = rd(SRC / "postly_background_reuse.csv")
backgrounds = [{"id": r[0], "count": i(r[1]), "subs": r[2],
                "rows": [int(x) for x in r[3].split("; ") if x.strip().isdigit()]}
               for r in bg]
backgrounds.sort(key=lambda b: -b["count"])

json.dump({"clusters": clusters, "backgrounds": backgrounds},
          open(DATA / "clusters.json", "w"))
print(f"clusters={len(clusters)}  backgrounds={len(backgrounds)}")

# ---- copy only the frames the console will show -----------------------------
need = {m["row"] for c in clusters for m in c["members"]}
for b in backgrounds[:400]:
    need.update(b["rows"][:12])
copied = miss = 0
for r in need:
    s, d = SRC / "frames" / str(r), FR / str(r)
    if d.exists(): continue
    if s.exists():
        shutil.copytree(s, d); copied += 1
    else:
        miss += 1
print(f"frames copied={copied} missing={miss} total_rows={len(need)}")
