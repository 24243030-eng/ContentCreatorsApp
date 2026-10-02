"""Vago - AI Content Studio. Flask app (JSON API + single-page frontend)."""
import os, json
from datetime import date
from dotenv import load_dotenv
load_dotenv()
from flask import Flask, jsonify, request, render_template, Response
from werkzeug.exceptions import HTTPException
import db, ai, services as S
from seed import seed

app = Flask(__name__)
app.json.ensure_ascii = False
app.config["MAX_CONTENT_LENGTH"] = 1_000_000
GEN_DIR = os.path.join(os.path.dirname(__file__), "static", "generated")
LANGS = ["English", "Tamil", "Hindi", "Telugu", "Malayalam", "Kannada", "Bengali", "Marathi", "Spanish", "French", "German"]

def body(): return request.get_json(silent=True) or {}
def text(d, k, mx=5000, req=False):
    v = str(d.get(k) or "").strip()
    if req and not v: raise ValueError(f"'{k}' is required")
    if len(v) > mx: raise ValueError(f"'{k}' is too long (max {mx} characters)")
    return v
def num(d, k, default=None):
    try: return int(d.get(k, default))
    except (TypeError, ValueError): raise ValueError(f"'{k}' must be a number")
def get(table, i, label):
    r = db.q(f"SELECT * FROM {table} WHERE id=?", (i,), True)
    if not r: raise LookupError(f"{label} not found")
    return r
def brand_ctx(b): return {k: b.get(k, "") for k in ("name", "description", "voice", "tone", "dos", "donts", "keywords", "audience")}
def mode_label(m): return {"gemini": "gemini", "demo": "demo"}[m]

@app.errorhandler(Exception)
def fail(e):
    if isinstance(e, ai.AIError): return jsonify(error=str(e)), e.status
    if isinstance(e, LookupError): return jsonify(error=str(e)), 404
    if isinstance(e, ValueError): return jsonify(error=str(e)), 400
    if isinstance(e, HTTPException): return jsonify(error=e.description), e.code
    app.logger.exception(e); return jsonify(error="Unexpected server error. Check the terminal for details."), 500

@app.after_request
def hdr(r): r.headers["X-Content-Type-Options"] = "nosniff"; return r

@app.get("/")
def index(): return render_template("index.html")

@app.get("/api/status")
def status():
    live = ai.is_live()
    return jsonify(mode="live" if live else "demo", model=ai.model() if live else None, image_enabled=ai.image_enabled(), languages=LANGS, channels=S.CHANNELS, statuses=S.STATUSES, feedback_tags=S.FEEDBACK_TAGS,
                   notice=None if live else "Demo mode: outputs are simple templates/heuristics, NOT AI. Add GEMINI_API_KEY to .env for live Gemini.")

# ---------- dashboard ----------
@app.get("/api/dashboard")
def dashboard():
    c = lambda s: db.q(s, one=True)
    return jsonify(totals={"campaigns": c("SELECT COUNT(*) n FROM campaigns")["n"], "pieces": c("SELECT COUNT(*) n FROM contents")["n"],
                           "publishable": c("SELECT COUNT(*) n FROM contents WHERE status IN ('approved','ready')")["n"], "avg_quality": round(c("SELECT AVG(quality) a FROM contents")["a"] or 0),
                           "avg_rating": round(c("SELECT AVG(rating) a FROM feedback")["a"] or 0, 1)},
                   by_channel=db.q("SELECT channel k,COUNT(*) n FROM contents GROUP BY channel"), by_status=db.q("SELECT status k,COUNT(*) n FROM contents GROUP BY status"),
                   camp_quality=db.q("SELECT c.name k,ROUND(AVG(t.quality)) n FROM campaigns c JOIN contents t ON t.campaign_id=c.id GROUP BY c.id"),
                   activity=db.q("SELECT * FROM activity ORDER BY id DESC LIMIT 8"))

# ---------- brands (3) ----------
@app.get("/api/brands")
def brands(): return jsonify(db.q("SELECT * FROM brands ORDER BY id"))

def brand_fields(d):
    return [text(d, "name", 80, True), text(d, "description", 500), text(d, "voice", 800), text(d, "tone", 200), text(d, "dos", 800), text(d, "donts", 400), text(d, "keywords", 300), text(d, "audience", 400)]

@app.post("/api/brands")
def brand_new():
    v = brand_fields(body()); i = db.x("INSERT INTO brands(name,description,voice,tone,dos,donts,keywords,audience,created) VALUES(?,?,?,?,?,?,?,?,?)", (*v, S.now()))
    S.log("brand", f"Brand '{v[0]}' created"); return jsonify(get("brands", i, "Brand")), 201

@app.put("/api/brands/<int:i>")
def brand_edit(i):
    get("brands", i, "Brand"); v = brand_fields(body())
    db.x("UPDATE brands SET name=?,description=?,voice=?,tone=?,dos=?,donts=?,keywords=?,audience=? WHERE id=?", (*v, i)); S.log("brand", f"Brand '{v[0]}' voice updated")
    return jsonify(get("brands", i, "Brand"))

@app.get("/api/insights")
def insights(): return jsonify(S.insights(num(request.args, "brand_id", 0)))

# ---------- campaigns ----------
@app.get("/api/campaigns")
def campaigns():
    return jsonify(db.q("SELECT c.*,b.name brand_name,(SELECT COUNT(*) FROM contents t WHERE t.campaign_id=c.id) pieces,(SELECT COUNT(*) FROM contents t WHERE t.campaign_id=c.id AND t.status IN ('approved','ready')) approved FROM campaigns c LEFT JOIN brands b ON b.id=c.brand_id ORDER BY c.id DESC"))

@app.post("/api/campaigns")
def campaign_new():
    d = body(); get("brands", num(d, "brand_id"), "Brand")
    i = db.x("INSERT INTO campaigns(brand_id,name,goal,brief,analysis,created) VALUES(?,?,?,?,?,?)", (num(d, "brand_id"), text(d, "name", 120, True), text(d, "goal", 300), text(d, "brief", 5000), "", S.now()))
    S.log("campaign", f"Campaign '{d['name'][:40]}' created"); return jsonify(get("campaigns", i, "Campaign")), 201

@app.put("/api/campaigns/<int:i>")
def campaign_edit(i):
    get("campaigns", i, "Campaign"); d = body()
    db.x("UPDATE campaigns SET name=?,goal=?,brief=? WHERE id=?", (text(d, "name", 120, True), text(d, "goal", 300), text(d, "brief", 5000), i)); return jsonify(get("campaigns", i, "Campaign"))

@app.delete("/api/campaigns/<int:i>")
def campaign_del(i):
    c = get("campaigns", i, "Campaign"); db.x("DELETE FROM campaigns WHERE id=?", (i,)); S.log("campaign", f"Campaign '{c['name'][:40]}' deleted"); return jsonify(ok=True)

# ---------- 1 brief intelligence ----------
@app.post("/api/brief/analyze")
def brief():
    d = body(); c = get("campaigns", num(d, "campaign_id"), "Campaign"); b = get("brands", c["brand_id"], "Brand"); t = text(d, "brief", 5000) or c["brief"]
    if len(t) < 20: raise ValueError("Write at least a couple of sentences in the brief first.")
    r, m = ai.run("brief", {"brief": t, "goal": c["goal"], "brand": brand_ctx(b), "audience": b["audience"], "tone": b["tone"]})
    db.x("UPDATE campaigns SET brief=?,analysis=? WHERE id=?", (t, json.dumps({"mode": m, **r}), c["id"])); S.log("ai", f"Brief analysed for '{c['name'][:40]}' ({m})")
    return jsonify(result=r, mode=m)

# ---------- 2 generator ----------
def _txt(v): return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False) if v else ""

@app.post("/api/generate")
def generate():
    d = body(); c = get("campaigns", num(d, "campaign_id"), "Campaign"); b = get("brands", c["brand_id"], "Brand")
    fm = [f for f in d.get("formats", []) if f in S.CHANNELS]; lang = d.get("language", "English")
    if not fm: raise ValueError("Select at least one format.")
    if lang not in LANGS: raise ValueError("Unsupported language.")
    if lang != "English" and not ai.is_live(): raise ai.AIError("Non-English generation needs a Gemini API key (demo templates are English only).", 501)
    if not c["brief"].strip(): raise ValueError("Add a brief to the campaign first.")
    pers = db.q("SELECT data FROM personas WHERE campaign_id=? ORDER BY id DESC LIMIT 1", (c["id"],), True)
    ctx = {"brand": brand_ctx(b), "campaign": {"name": c["name"], "goal": c["goal"], "brief": c["brief"]}, "formats": fm, "language": lang, "learned_rules": S.insights(b["id"])["rules"],
           "persona": json.loads(pers["data"]) if pers else None}
    r, m = ai.run("generate", ctx); items = (r.get("items") if isinstance(r, dict) else r) or []; ids = []
    for it in items:
        ch = it.get("format") if it.get("format") in S.CHANNELS else None
        if ch and _txt(it.get("body")).strip(): ids.append(S.create_content(c["id"], ch, _txt(it.get("title"))[:200] or ai.CH[ch], _txt(it["body"]), lang, m, note=f"Generated ({m})"))
    if not ids: raise ai.AIError("The model returned no usable content. Please retry.")
    S.log("ai", f"{len(ids)} pieces generated for '{c['name'][:40]}' ({m})"); return jsonify(ids=ids, mode=m), 201

# ---------- 17 library ----------
@app.get("/api/contents")
def contents():
    a = request.args; w, p = [], []
    if a.get("search"): w.append("(t.title LIKE ? OR t.body LIKE ?)"); p += [f"%{a['search'][:100]}%"] * 2
    for k, col in [("channel", "t.channel"), ("status", "t.status"), ("language", "t.language"), ("campaign_id", "t.campaign_id")]:
        if a.get(k): w.append(f"{col}=?"); p.append(a[k])
    rows = db.q(f"SELECT t.id,t.title,t.channel,t.status,t.quality,t.version,t.language,t.source,t.updated,t.campaign_id,c.name campaign,substr(t.body,1,220) preview FROM contents t JOIN campaigns c ON c.id=t.campaign_id {'WHERE ' + ' AND '.join(w) if w else ''} ORDER BY t.updated DESC,t.id DESC", p)
    return jsonify(rows)

@app.get("/api/contents/<int:i>")
def content(i):
    c = get("contents", i, "Content"); c["campaign"] = get("campaigns", c["campaign_id"], "Campaign")["name"]
    c["versions"] = db.q("SELECT * FROM versions WHERE content_id=? ORDER BY version DESC", (i,)); c["approvals"] = db.q("SELECT * FROM approvals WHERE content_id=? ORDER BY id DESC", (i,))
    c["feedback"] = db.q("SELECT * FROM feedback WHERE content_id=? ORDER BY id DESC", (i,)); return jsonify(c)

@app.put("/api/contents/<int:i>")
def content_edit(i):
    d = body(); get("contents", i, "Content"); v = S.add_version(i, text(d, "title", 200, True), text(d, "body", 20000, True), text(d, "note", 200) or "Manual edit", "manual"); return jsonify(version=v)

@app.delete("/api/contents/<int:i>")
def content_del(i): get("contents", i, "Content"); db.x("DELETE FROM contents WHERE id=?", (i,)); return jsonify(ok=True)

@app.post("/api/contents/<int:i>/restore")
def restore(i):
    v = db.q("SELECT * FROM versions WHERE content_id=? AND version=?", (i, num(body(), "version")), True)
    if not v: raise LookupError("Version not found")
    return jsonify(version=S.add_version(i, v["title"], v["body"], f"Restored v{v['version']}", "manual"))

def _ctx(c): return {"title": c["title"], "body": c["body"], "channel": c["channel"], "language": c["language"], "brand": brand_ctx(S.brand_of_content(c["id"])), "learned_rules": S.insights(S.brand_of_content(c["id"]).get("id", 0))["rules"]}

# ---------- 5 refine / 16 chat / 4 adapt / 8 translate ----------
@app.post("/api/contents/<int:i>/refine")
def refine(i):
    c = get("contents", i, "Content"); ins = text(body(), "instruction", 400, True)
    r, m = ai.run("refine", {**_ctx(c), "instruction": ins}); v = S.add_version(i, _txt(r.get("title")) or c["title"], _txt(r.get("body")) or c["body"], f"Refine: {ins[:80]}", m)
    return jsonify(version=v, summary=r.get("summary_of_changes", ""), mode=m)

@app.post("/api/contents/<int:i>/chat")
def chat(i):
    c = get("contents", i, "Content"); d = body(); msg = text(d, "message", 600, True); hist = [{"role": str(h.get("role"))[:10], "text": str(h.get("text"))[:600]} for h in (d.get("history") or [])[-6:] if isinstance(h, dict)]
    r, m = ai.run("chat", {**_ctx(c), "message": msg, "history": hist}); nb = _txt(r.get("body")); changed = bool(nb) and nb.strip() != c["body"].strip()
    if changed: S.add_version(i, _txt(r.get("title")) or c["title"], nb, f"Chat edit: {msg[:70]}", m)
    return jsonify(reply=r.get("reply", ""), changed=changed, mode=m)

@app.post("/api/contents/<int:i>/adapt")
def adapt(i):
    c = get("contents", i, "Content"); t = body().get("target")
    if t not in S.CHANNELS or t == c["channel"]: raise ValueError("Pick a different target platform.")
    r, m = ai.run("adapt", {**_ctx(c), "target": t}); n = S.create_content(c["campaign_id"], t, _txt(r.get("title")) or c["title"], _txt(r.get("body")), c["language"], m, i, f"Adapted from #{i} ({c['channel']}→{t})")
    S.log("ai", f"Adapted '{c['title'][:30]}' to {t} ({m})"); return jsonify(id=n, mode=m), 201

@app.post("/api/contents/<int:i>/translate")
def translate(i):
    c = get("contents", i, "Content"); lang = body().get("language")
    if lang not in LANGS or lang == c["language"]: raise ValueError("Pick a different target language.")
    r, m = ai.run("translate", {**_ctx(c), "target_language": lang}); n = S.create_content(c["campaign_id"], c["channel"], _txt(r.get("title")) or c["title"], _txt(r.get("body")), lang, m, i, f"Translated from #{i} to {lang}")
    S.log("ai", f"Translated '{c['title'][:30]}' to {lang} ({m})"); return jsonify(id=n, mode=m), 201

# ---------- 6 quality / 12 SEO / 13 duplicates ----------
@app.post("/api/contents/<int:i>/analyze")
def analyze(i):
    c = get("contents", i, "Content"); qr = S.quality(c["body"], c["channel"], S.brand_of_content(i), c["language"]); db.x("UPDATE contents SET quality=? WHERE id=?", (qr["overall"], i))
    crit, m = ai.run("critique", _ctx(c)); return jsonify(quality=qr, critique=crit if m == "gemini" else None, mode=m)

@app.post("/api/contents/<int:i>/seo")
def seo(i):
    c = get("contents", i, "Content"); kw = text(body(), "keyword", 60); loc = S.seo_check(c["title"], c["body"], kw); r, m = ai.run("seo", {**_ctx(c), "target_keyword": kw})
    return jsonify(local=loc, suggestions=r, mode=m)

@app.post("/api/duplicates")
def dupes():
    d = body()
    if d.get("content_id"): c = get("contents", num(d, "content_id"), "Content"); return jsonify(S.find_duplicates(c["body"], c["id"]))
    return jsonify(S.find_duplicates(text(d, "text", 20000, True)))

# ---------- 7 ideas ----------
@app.post("/api/ideas")
def ideas():
    d = body(); b = get("brands", num(d, "brand_id"), "Brand"); k = min(max(num(d, "count", 5), 1), 8)
    r, m = ai.run("ideas", {"brand": brand_ctx(b), "goal": text(d, "goal", 300), "theme": text(d, "theme", 200), "count": k, "learned_rules": S.insights(b["id"])["rules"]}); return jsonify(ideas=(r.get("ideas") or [])[:k], mode=m)

# ---------- 9 calendar ----------
def _date(v):
    try: return date.fromisoformat(str(v)).isoformat()
    except ValueError: raise ValueError("Date must be YYYY-MM-DD")

@app.get("/api/calendar")
def cal_list():
    cid = request.args.get("campaign_id"); return jsonify(db.q("SELECT e.*,c.name campaign FROM calendar e JOIN campaigns c ON c.id=e.campaign_id " + ("WHERE e.campaign_id=? " if cid else "") + "ORDER BY e.date,e.id", (cid,) if cid else ()))

@app.post("/api/calendar")
def cal_add():
    d = body(); get("campaigns", num(d, "campaign_id"), "Campaign"); ch = d.get("channel", "instagram")
    if ch not in S.CHANNELS: raise ValueError("Invalid channel")
    i = db.x("INSERT INTO calendar(campaign_id,content_id,date,channel,title,notes,status,created) VALUES(?,?,?,?,?,?,?,?)", (num(d, "campaign_id"), d.get("content_id"), _date(d.get("date")), ch, text(d, "title", 200, True), text(d, "notes", 500), "planned", S.now()))
    return jsonify(get("calendar", i, "Entry")), 201

@app.put("/api/calendar/<int:i>")
def cal_edit(i):
    get("calendar", i, "Entry"); d = body(); ch = d.get("channel")
    if ch not in S.CHANNELS or d.get("status") not in ("planned", "scheduled", "published", "skipped"): raise ValueError("Invalid channel or status")
    db.x("UPDATE calendar SET date=?,channel=?,title=?,notes=?,status=? WHERE id=?", (_date(d.get("date")), ch, text(d, "title", 200, True), text(d, "notes", 500), d["status"], i)); return jsonify(get("calendar", i, "Entry"))

@app.delete("/api/calendar/<int:i>")
def cal_del(i): get("calendar", i, "Entry"); db.x("DELETE FROM calendar WHERE id=?", (i,)); return jsonify(ok=True)

@app.post("/api/calendar/generate")
def cal_gen():
    d = body(); c = get("campaigns", num(d, "campaign_id"), "Campaign"); b = get("brands", c["brand_id"], "Brand"); days = min(max(num(d, "days", 14), 3), 60); st = _date(d.get("start_date") or date.today())
    ex = db.q("SELECT id,title,channel FROM contents WHERE campaign_id=? AND status IN ('approved','ready','draft','in_review','changes_requested')", (c["id"],))
    r, m = ai.run("calendar", {"campaign": {"name": c["name"], "goal": c["goal"], "brief": c["brief"]}, "brand": brand_ctx(b), "start_date": st, "days": days, "contents": ex}); n = 0
    for e in r.get("entries") or []:
        try: dt = _date(e.get("date"))
        except ValueError: continue
        ch = e.get("channel") if e.get("channel") in S.CHANNELS else "instagram"; cid = e.get("content_id") if any(z["id"] == e.get("content_id") for z in ex) else None
        db.x("INSERT INTO calendar(campaign_id,content_id,date,channel,title,notes,status,created) VALUES(?,?,?,?,?,?,?,?)", (c["id"], cid, dt, ch, _txt(e.get("title"))[:200] or "Untitled", _txt(e.get("notes"))[:500], "planned", S.now())); n += 1
    S.log("ai", f"Calendar: {n} entries for '{c['name'][:40]}' ({m})"); return jsonify(added=n, mode=m), 201

# ---------- 10 visuals ----------
@app.get("/api/visuals")
def vis_list(): cid = request.args.get("campaign_id", 0); return jsonify(db.q("SELECT * FROM visuals WHERE campaign_id=? ORDER BY id DESC", (cid,)))

@app.post("/api/visuals")
def vis_gen():
    d = body(); c = get("campaigns", num(d, "campaign_id"), "Campaign"); b = get("brands", c["brand_id"], "Brand"); subj = ""
    if d.get("content_id"): ct = get("contents", num(d, "content_id"), "Content"); subj = f"{ct['title']}: {ct['body'][:400]}"
    r, m = ai.run("visual", {"brand": brand_ctx(b), "campaign": {"name": c["name"], "goal": c["goal"], "brief": c["brief"][:600]}, "subject": subj, "style": text(d, "style", 120), "count": min(max(num(d, "count", 3), 1), 5)})
    ids = [db.x("INSERT INTO visuals(campaign_id,content_id,title,prompt,style,aspect,image,source,created) VALUES(?,?,?,?,?,?,?,?,?)", (c["id"], d.get("content_id"), _txt(p.get("title"))[:120], _txt(p.get("prompt")), _txt(p.get("style"))[:120], _txt(p.get("aspect"))[:10], "", m, S.now())) for p in (r.get("prompts") or []) if p.get("prompt")]
    return jsonify(ids=ids, mode=m), 201

@app.post("/api/visuals/<int:i>/image")
def vis_img(i):
    v = get("visuals", i, "Visual"); name = ai.generate_image(v["prompt"] + f" Aspect ratio {v['aspect']}.", GEN_DIR); db.x("UPDATE visuals SET image=? WHERE id=?", (name, i)); return jsonify(image=name)

# ---------- 11 personas ----------
@app.get("/api/personas")
def pers_list(): return jsonify([{**r, "data": json.loads(r["data"])} for r in db.q("SELECT * FROM personas WHERE campaign_id=? ORDER BY id DESC", (request.args.get("campaign_id", 0),))])

@app.post("/api/personas")
def pers_gen():
    d = body(); c = get("campaigns", num(d, "campaign_id"), "Campaign"); b = get("brands", c["brand_id"], "Brand")
    r, m = ai.run("persona", {"brand": brand_ctx(b), "campaign": {"name": c["name"], "goal": c["goal"], "brief": c["brief"][:800]}}); db.x("INSERT INTO personas(campaign_id,data,source,created) VALUES(?,?,?,?)", (c["id"], json.dumps(r, ensure_ascii=False), m, S.now()))
    return jsonify(mode=m), 201

# ---------- 14 compare ----------
@app.get("/api/compare")
def compare():
    a, b = num(request.args, "a"), num(request.args, "b")
    if a == b: raise ValueError("Choose two different campaigns.")
    return jsonify(S.compare(a, b))

# ---------- 15 feedback ----------
@app.post("/api/contents/<int:i>/feedback")
def fb(i):
    get("contents", i, "Content"); d = body(); r = num(d, "rating")
    if not 1 <= r <= 5: raise ValueError("Rating must be 1-5.")
    tags = ",".join(t for t in d.get("tags", []) if t in S.FEEDBACK_TAGS); db.x("INSERT INTO feedback(content_id,rating,tags,comment,created) VALUES(?,?,?,?,?)", (i, r, tags, text(d, "comment", 500), S.now())); return jsonify(ok=True), 201

# ---------- 18 workflow ----------
@app.post("/api/contents/<int:i>/workflow")
def workflow(i): d = body(); return jsonify(status=S.transition(i, d.get("action"), text(d, "reviewer", 80), text(d, "note", 500)))

@app.get("/api/approvals")
def approvals(): return jsonify(db.q("SELECT a.*,t.title FROM approvals a JOIN contents t ON t.id=a.content_id ORDER BY a.id DESC LIMIT 15"))

# ---------- export ----------
def _md(c): return f"# {c['title']}\n\n*{c['channel']} · {c['language']} · v{c['version']} · {c['status']}*\n\n{c['body']}\n"

@app.get("/api/contents/<int:i>/export")
def export(i):
    c = get("contents", i, "Content"); f = request.args.get("fmt", "md"); slug = "".join(ch if ch.isalnum() else "-" for ch in c["title"][:40]).strip("-") or "content"
    data, mt = {"md": (_md(c), "text/markdown"), "txt": (c["body"], "text/plain"), "json": (json.dumps(c, ensure_ascii=False, indent=2), "application/json")}.get(f, (None, None))
    if data is None: raise ValueError("Format must be md, txt or json.")
    return Response(data, mimetype=mt + "; charset=utf-8", headers={"Content-Disposition": f"attachment; filename={slug}.{f}"})

@app.get("/api/campaigns/<int:i>/export")
def export_campaign(i):
    c = get("campaigns", i, "Campaign"); rows = db.q("SELECT * FROM contents WHERE campaign_id=? ORDER BY id", (i,))
    return Response(f"# {c['name']}\n\n{c['goal']}\n\n---\n\n" + "\n---\n\n".join(_md(r) for r in rows), mimetype="text/markdown; charset=utf-8", headers={"Content-Disposition": "attachment; filename=campaign.md"})

db.init(); seed()
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", 5000)), debug=os.getenv("FLASK_DEBUG") == "1")
