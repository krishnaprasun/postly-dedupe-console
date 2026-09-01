#!/usr/bin/env python3
"""Postly duplicate review & removal console.

Reviewers see every candidate duplicate cluster side by side (real frames, not
hashes), pick which copy survives, and confirm or reject. Nothing is removed from
the app by browsing: removal is a separate, explicitly gated step that operates
ONLY on clusters a human confirmed.

Why review at all: the detector is perceptual, and one class of false positive is
known and real -- daily darshan art that differs only in a small date stamp
(7-7-2026 vs 8-7-2026). Those clusters are flagged DATE-VARIANT and sorted last.
"""
import csv, io, json, os, functools, hmac, secrets
from pathlib import Path
from flask import (Flask, render_template, request, redirect, url_for, jsonify,
                   send_from_directory, Response, abort)
import db

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
app = Flask(__name__)

# Per-reviewer logins so every removal decision is attributable to a person.
# DEDUPE_USERS="alice:pw1,bob:pw2" ; falls back to a single dev login locally.
def _load_users():
    raw = os.environ.get("DEDUPE_USERS", "").strip()
    users = {}
    for pair in raw.split(","):
        if ":" in pair:
            u, _, pw = pair.partition(":")
            u, pw = u.strip(), pw.strip()
            if u and pw: users[u] = pw
    if not users:
        # No published default: this repo is public, so a hardcoded password would
        # be a published password. Generate one per boot for local dev, and refuse
        # to run wide open anywhere that looks like a real deploy.
        if os.environ.get("RENDER") or os.environ.get("DEDUPE_REQUIRE_USERS"):
            raise SystemExit("DEDUPE_USERS is not set - refusing to start without logins")
        pw = secrets.token_urlsafe(12)
        print(f"\n  [dev login]  user: dev   password: {pw}\n", flush=True)
        users = {"dev": pw}
    return users

USERS = _load_users()
# Removal adapter: 'export' writes a manifest only (safe default).
# 'sheet' writes back to the master sheet and must be turned on deliberately.
EXEC_MODE = os.environ.get("DEDUPE_EXEC_MODE", "export")

_D = json.load(open(DATA / "clusters.json"))
CLUSTERS = _D["clusters"]
BACKGROUNDS = _D["backgrounds"]
BY_ID = {c["id"]: c for c in CLUSTERS}
db.init()

def auth(f):
    @functools.wraps(f)
    def w(*a, **k):
        au = request.authorization
        if not au or not hmac.compare_digest(USERS.get(au.username, ""), au.password or ""):
            return Response("login required", 401,
                            {"WWW-Authenticate": 'Basic realm="postly-dedupe"'})
        return f(*a, **k)
    return w

def enrich():
    """Clusters annotated with their current decision."""
    d = db.all_decisions()
    out = []
    for c in CLUSTERS:
        c = dict(c)
        dec = d.get(c["id"])
        c["verdict"] = dec["verdict"] if dec else None
        c["keeper_row"] = dec["keeper_row"] if dec else c["members"][0]["row"]
        out.append(c)
    return out

def apply_filters(cs, f, cls):
    if f == "pending":  cs = [c for c in cs if not c["verdict"]]
    elif f == "confirm": cs = [c for c in cs if c["verdict"] == "confirm"]
    elif f == "reject":  cs = [c for c in cs if c["verdict"] == "reject"]
    elif f == "skip":    cs = [c for c in cs if c["verdict"] == "skip"]
    if cls == "newfind":   cs = [c for c in cs if c["detection"] == "DIFFERENT-FILES"]
    elif cls == "vendor":  cs = [c for c in cs if c["cross_vendor"]]
    elif cls == "datevar": cs = [c for c in cs if c["date_variant"]]
    elif cls == "safe":    cs = [c for c in cs if not c["date_variant"]]
    return cs

@app.route("/")
@auth
def queue():
    f   = request.args.get("f", "pending")
    cls = request.args.get("cls", "all")
    cs  = enrich()
    stats = {
        "total": len(cs),
        "pending": sum(1 for c in cs if not c["verdict"]),
        "confirm": sum(1 for c in cs if c["verdict"] == "confirm"),
        "reject":  sum(1 for c in cs if c["verdict"] == "reject"),
        "skip":    sum(1 for c in cs if c["verdict"] == "skip"),
        "rows_to_remove": sum(len(c["members"]) - 1 for c in cs if c["verdict"] == "confirm"),
        "newfind": sum(1 for c in cs if c["detection"] == "DIFFERENT-FILES"),
        "datevar": sum(1 for c in cs if c["date_variant"]),
        "vendor":  sum(1 for c in cs if c["cross_vendor"]),
    }
    sel = apply_filters(cs, f, cls)
    return render_template("queue.html", clusters=sel[:300], stats=stats, f=f, cls=cls,
                           shown=len(sel[:300]), matched=len(sel))

@app.route("/c/<cid>")
@auth
def cluster(cid):
    c = BY_ID.get(cid)
    if not c: abort(404)
    dec = db.get(cid)
    order = [x["id"] for x in apply_filters(enrich(), request.args.get("f", "pending"),
                                            request.args.get("cls", "all"))]
    nxt = None
    if cid in order:
        i = order.index(cid)
        nxt = order[i + 1] if i + 1 < len(order) else None
    elif order:
        nxt = order[0]
    frames = {m["row"]: sorted(p.name for p in (DATA / "frames" / str(m["row"])).glob("*.jpg"))
              for m in c["members"]}
    return render_template("cluster.html", c=c, dec=dec, frames=frames, nxt=nxt,
                           f=request.args.get("f", "pending"), cls=request.args.get("cls", "all"))

@app.route("/c/<cid>/decide", methods=["POST"])
@auth
def decide(cid):
    if cid not in BY_ID: abort(404)
    verdict = request.form.get("verdict", "skip")
    keeper  = request.form.get("keeper", type=int)
    if verdict == "confirm" and keeper not in {m["row"] for m in BY_ID[cid]["members"]}:
        abort(400, "keeper must be a member of the cluster")
    db.decide(cid, verdict, keeper, request.form.get("note", ""),
              request.authorization.username if request.authorization else "")
    nxt = request.form.get("next")
    f, cls = request.form.get("f", "pending"), request.form.get("cls", "all")
    if nxt:
        return redirect(url_for("cluster", cid=nxt, f=f, cls=cls))
    return redirect(url_for("queue", f=f, cls=cls))

@app.route("/f/<int:row>/<name>")
@auth
def frame(row, name):
    if not name.endswith(".jpg"): abort(404)
    return send_from_directory(DATA / "frames" / str(row), name)

@app.route("/backgrounds")
@auth
def backgrounds():
    return render_template("backgrounds.html", bgs=BACKGROUNDS[:200],
                           total=len(BACKGROUNDS),
                           videos=sum(b["count"] for b in BACKGROUNDS))

# ---- removal ---------------------------------------------------------------
def removal_plan():
    """Rows to retire = every non-keeper in a CONFIRMED cluster. Nothing else."""
    d = db.all_decisions()
    plan = []
    for c in CLUSTERS:
        dec = d.get(c["id"])
        if not dec or dec["verdict"] != "confirm": continue
        keep = dec["keeper_row"]
        for m in c["members"]:
            if m["row"] != keep:
                plan.append({"cluster": c["id"], "sheet_row": m["row"], "serial": m["serial"],
                             "subcategory": m["sub"], "vendor": m["vendor"],
                             "postly_file_path": m["path"], "media_link": m["link"],
                             "shares": m["shares"], "downloads": m["downloads"],
                             "keeper_row": keep})
    return plan

@app.route("/export/removals.csv")
@auth
def export_removals():
    plan = removal_plan()
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(plan[0].keys()) if plan else
                       ["cluster", "sheet_row", "serial", "subcategory", "vendor",
                        "postly_file_path", "media_link", "shares", "downloads", "keeper_row"])
    w.writeheader(); w.writerows(plan)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=postly_removals.csv"})

@app.route("/execute", methods=["GET", "POST"])
@auth
def execute():
    plan = removal_plan()
    if request.method == "GET":
        return render_template("execute.html", plan=plan[:100], n=len(plan),
                               mode=EXEC_MODE, runs=db.executions())
    if request.form.get("confirm_text") != "REMOVE":
        return render_template("execute.html", plan=plan[:100], n=len(plan), mode=EXEC_MODE,
                               runs=db.executions(),
                               error="Type REMOVE exactly to proceed."), 400
    if EXEC_MODE == "export":
        db.log_execution("export", len(plan), "manifest generated; no external write")
        return redirect(url_for("export_removals"))
    db.log_execution("blocked", len(plan), f"mode={EXEC_MODE} not implemented")
    return render_template("execute.html", plan=plan[:100], n=len(plan), mode=EXEC_MODE,
                           runs=db.executions(),
                           error=f"Write mode '{EXEC_MODE}' is not wired up yet — "
                                 "the app-side removal mechanism has not been confirmed. "
                                 "Use the manifest export."), 501

@app.route("/export/decisions.csv")
@auth
def export_decisions():
    """Full audit trail. The free Postgres expires 2026-10-01 -- take a copy."""
    rows = db.history()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["cluster_id", "verdict", "keeper_row", "note", "reviewer", "ts"])
    for r in rows:
        w.writerow([r["cluster_id"], r["verdict"], r["keeper_row"], r["note"],
                    r["reviewer"], r["ts"]])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=dedupe_decisions.csv"})

@app.route("/healthz")
def healthz():
    return jsonify(ok=True, clusters=len(CLUSTERS), backgrounds=len(BACKGROUNDS),
                   mode=EXEC_MODE, store="postgres" if db.PG else "sqlite",
                   reviewers=len(USERS))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8077)), debug=False)
