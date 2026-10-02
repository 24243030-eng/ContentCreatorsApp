"""Domain logic: content storage/versioning, explainable quality scoring, duplicates, SEO, comparison, feedback learning, workflow."""
import re, math
from collections import Counter
from datetime import datetime, timezone
from db import q, x

CHANNELS = ["instagram", "linkedin", "blog", "ad", "email", "video"]
STATUSES = ["draft", "in_review", "changes_requested", "approved", "ready", "rejected"]
SPEC = {"instagram": (30, 110, 3, 10), "linkedin": (90, 260, 0, 5), "blog": (600, 1500, 0, 0), "ad": (12, 45, 0, 3), "email": (80, 230, 0, 0), "video": (40, 120, 0, 3)}
CTA = re.compile(r"\b(shop|buy|order|sign up|subscribe|join|learn more|discover|book|register|download|try|get|visit|tap|click|reply|read|start|contact|call|explore|reserve)\b", re.I)
EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")
STOP = set("the a an and or of to in for on with is are was be this that it as at by from your you our we they their can will not have has more all one about into than".split())
TRANSITIONS = {"submit": ({"draft", "changes_requested"}, "in_review"), "approve": ({"in_review"}, "approved"), "request_changes": ({"in_review", "approved"}, "changes_requested"),
               "reject": ({"in_review"}, "rejected"), "mark_ready": ({"approved"}, "ready"), "reopen": ({"rejected", "ready", "approved"}, "draft")}
MIN_READY_QUALITY = 45

def now(): return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
def log(kind, text): x("INSERT INTO activity(kind,text,created) VALUES(?,?,?)", (kind, text, now()))
def words(t): return re.findall(r"[\w']+", t or "")
def clamp(v, lo=0, hi=100): return max(lo, min(hi, v))

# ---------- content storage & versions ----------
def brand_of_campaign(cid): return q("SELECT b.* FROM brands b JOIN campaigns c ON c.brand_id=b.id WHERE c.id=?", (cid,), True) or {}
def brand_of_content(cid): return q("SELECT b.* FROM brands b JOIN campaigns c ON c.brand_id=b.id JOIN contents t ON t.campaign_id=c.id WHERE t.id=?", (cid,), True) or {}

def create_content(campaign_id, channel, title, body, language="English", source="demo", parent_id=None, note="Initial version", status="draft"):
    ts = now(); ql = quality(body, channel, brand_of_campaign(campaign_id), language)["overall"]
    cid = x("INSERT INTO contents(campaign_id,channel,title,body,language,status,version,source,parent_id,quality,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (campaign_id, channel, title, body, language, status, 1, source, parent_id, ql, ts, ts))
    x("INSERT INTO versions(content_id,version,title,body,note,source,created) VALUES(?,?,?,?,?,?,?)", (cid, 1, title, body, note, source, ts))
    return cid

def add_version(cid, title, body, note, source):
    c = q("SELECT * FROM contents WHERE id=?", (cid,), True)
    if not c: raise LookupError("Content not found")
    v = c["version"] + 1; ts = now(); ql = quality(body, c["channel"], brand_of_content(cid), c["language"])["overall"]
    status = "draft" if c["status"] in ("approved", "ready", "in_review", "rejected") else c["status"]
    x("UPDATE contents SET title=?,body=?,version=?,quality=?,status=?,updated=?,source=? WHERE id=?", (title, body, v, ql, status, ts, source, cid))
    x("INSERT INTO versions(content_id,version,title,body,note,source,created) VALUES(?,?,?,?,?,?,?)", (cid, v, title, body, note, source, ts))
    if status != c["status"]:
        x("INSERT INTO approvals(content_id,action,from_status,to_status,reviewer,note,created) VALUES(?,?,?,?,?,?,?)", (cid, "edited", c["status"], status, "system", "Edited after review - approval reset", ts))
    return v

# ---------- explainable quality ----------
def _syll(w):
    w = w.lower(); n = len(re.findall(r"[aeiouy]+", w)); return max(1, n - (1 if w.endswith("e") and n > 1 else 0))

def quality(text, channel="instagram", brand=None, language="English"):
    brand = brand or {}; ws = words(text); wc = len(ws); sents = [s for s in re.split(r"[.!?\n]+", text or "") if s.strip()]; sc = max(1, len(sents))
    lo, hi, tmin, tmax = SPEC.get(channel, (20, 300, 0, 10)); tags = len(re.findall(r"#\w+", text or "")); emo = len(EMOJI.findall(text or ""))
    m = []
    # length
    ls = 100 if lo <= wc <= hi else clamp(100 * wc / lo if wc < lo else 100 * hi / wc, 20, 95)
    m.append(("length", "Length fit", ls, 15, f"{wc} words; ideal for {channel} is {lo}-{hi}."))
    # readability
    if language.lower().startswith("english") and wc > 5:
        fl = 206.835 - 1.015 * (wc / sc) - 84.6 * (sum(_syll(w) for w in ws) / wc)
        m.append(("readability", "Readability", clamp(fl if fl < 90 else 90 + (100 - fl) / 10, 20, 100), 15, f"Flesch reading ease ≈ {round(fl)} (60-80 reads as plain English)."))
    else:
        m.append(("readability", "Readability", 70, 15, "Not scored for non-English text (neutral 70)."))
    # hook
    first = " ".join(ws[:14]); sig = [("question", "?" in (text or "").split("\n")[0]), ("number", bool(re.search(r"\d", first))), ("addresses reader", bool(re.search(r"\b(you|your)\b", first, re.I))),
                                      ("emoji/power opener", bool(EMOJI.search(first)) or bool(re.search(r"\b(new|free|secret|why|how|stop|finally|introducing)\b", first, re.I)))]
    hit = [n for n, ok in sig if ok]
    m.append(("hook", "Opening hook", min(100, 40 + 30 * len(hit)), 20, "Hook signals: " + (", ".join(hit) if hit else "none found in the first line.")))
    # CTA
    has = bool(CTA.search(text or ""))
    m.append(("cta", "Call to action", 100 if has else 30, 15, "Action phrase found." if has else "No clear call to action detected."))
    # hygiene
    hs, hd = 100, []
    if tmax == 0 and tags: hs -= 30; hd.append(f"{tags} hashtags is unusual for {channel}")
    if tmin and tags < tmin: hs -= 30; hd.append(f"only {tags} hashtags (aim {tmin}-{tmax})")
    if tmax and tags > tmax: hs -= 30; hd.append(f"{tags} hashtags is too many (max ~{tmax})")
    if channel == "linkedin" and emo > 3: hs -= 20; hd.append("too many emojis for LinkedIn")
    m.append(("format", "Format hygiene", clamp(hs), 10, "; ".join(hd) or f"Hashtags ({tags}) and emojis ({emo}) fit {channel}."))
    # brand voice
    kws = [k.strip().lower() for k in (brand.get("keywords") or "").split(",") if k.strip()]; bans = [b.strip().lower() for b in re.split(r"[,;\n]", brand.get("donts") or "") if b.strip()]
    low = (text or "").lower(); found = [k for k in kws if k in low]; bad = [b for b in bans if b in low]
    bs = (40 + 60 * len(found) / len(kws)) if kws else 70; bs = clamp(bs - 25 * len(bad))
    m.append(("brand", "Brand voice fit", bs, 15, (f"Uses {len(found)}/{len(kws)} brand keywords. " if kws else "No brand keywords set (neutral 70). ") + (f"Contains avoided terms: {', '.join(bad)}." if bad else "No avoided terms found.")))
    # clarity
    avg = wc / sc; m.append(("clarity", "Sentence clarity", clamp(100 - max(0, avg - 20) * 4, 20, 100), 10, f"Average {avg:.1f} words per sentence (≤20 is easy to scan)."))
    tw = sum(w for *_, w, _ in m); overall = round(sum(s * w for _, _, s, w, _ in m) / tw)
    grade = "Excellent" if overall >= 80 else "Good" if overall >= 65 else "Needs work" if overall >= 50 else "Weak"
    return {"overall": overall, "grade": grade, "metrics": [{"key": k, "name": n, "score": round(s), "weight": w, "detail": d} for k, n, s, w, d in m],
            "stats": {"words": wc, "sentences": sc, "hashtags": tags, "emojis": emo}}

# ---------- duplicates ----------
def _sh(ws, n=3): return {" ".join(ws[i:i + n]) for i in range(max(1, len(ws) - n + 1))}
def similarity(a, b):
    wa, wb = [w.lower() for w in words(a)], [w.lower() for w in words(b)]
    if not wa or not wb: return 0.0
    sa, sb = _sh(wa), _sh(wb); j = len(sa & sb) / len(sa | sb)
    ca, cb = Counter(wa), Counter(wb); dot = sum(ca[k] * cb[k] for k in ca); cos = dot / (math.sqrt(sum(v * v for v in ca.values())) * math.sqrt(sum(v * v for v in cb.values())))
    return 0.6 * j + 0.4 * cos

def find_duplicates(text, exclude_id=None, limit=8):
    out = []
    for c in q("SELECT t.id,t.title,t.channel,t.body,t.status,c.name campaign FROM contents t JOIN campaigns c ON c.id=t.campaign_id"):
        if c["id"] == exclude_id: continue
        s = similarity(text, c["body"])
        if s >= 0.15: out.append({"id": c["id"], "title": c["title"], "channel": c["channel"], "campaign": c["campaign"], "similarity": round(s * 100), "verdict": "duplicate" if s >= .6 else "similar" if s >= .35 else "some overlap"})
    sents = [s.strip().lower() for s in re.split(r"[.!?\n]+", text or "") if len(words(s)) > 3]; rep = [s for s, n in Counter(sents).items() if n > 1]
    return {"matches": sorted(out, key=lambda m: -m["similarity"])[:limit], "internal_repeats": rep}

# ---------- SEO (local, deterministic) ----------
def seo_check(title, body, keyword=""):
    ws = [w.lower() for w in words(body)]; wc = len(ws); cnt = Counter(w for w in ws if w not in STOP and len(w) > 3)
    top = [{"word": w, "count": n, "density": round(100 * n / max(1, wc), 1)} for w, n in cnt.most_common(8)]
    kw = keyword.strip().lower(); checks = []
    def add(name, ok, d): checks.append({"name": name, "pass": bool(ok), "detail": d})
    add("Title length 30-60 chars", 30 <= len(title) <= 60, f"{len(title)} characters")
    add("Enough content depth (300+ words)", wc >= 300, f"{wc} words")
    add("Has headings (# / ##)", len(re.findall(r"^#{1,3} ", body or "", re.M)) >= 2, f"{len(re.findall(r'^#{1,3} ', body or '', re.M))} headings")
    if kw:
        k = body.lower().count(kw); dens = 100 * k / max(1, wc)
        add("Keyword in title", kw in title.lower(), f'"{kw}"'); add("Keyword in first 100 words", kw in " ".join(ws[:100]), ""); add("Keyword density 0.5-2.5%", 0.5 <= dens <= 2.5, f"{dens:.1f}% ({k} uses)")
    add("Contains a link or CTA", bool(CTA.search(body or "")), "")
    return {"score": round(100 * sum(c["pass"] for c in checks) / len(checks)), "checks": checks, "top_keywords": top}

# ---------- feedback learning ----------
TAG_RULES = {"too long": "Keep copy tighter: shorter sentences, fewer paragraphs.", "too short": "Add more concrete detail and specifics.", "too formal": "Use a warmer, conversational register.",
             "too casual": "Keep the tone professional and polished.", "off brand": "Stay closely aligned with the brand voice and keywords.", "weak hook": "Open with a stronger first line (question, number or bold claim).",
             "weak cta": "End with one clear, specific call to action.", "generic": "Use specific details, examples and product truths instead of generic claims."}
FEEDBACK_TAGS = list(TAG_RULES) + ["great hook", "on brand", "clear cta"]

def insights(brand_id):
    rows = q("SELECT f.*,t.channel,t.title,t.body FROM feedback f JOIN contents t ON t.id=f.content_id JOIN campaigns c ON c.id=t.campaign_id WHERE c.brand_id=?", (brand_id,))
    tags = Counter(t for r in rows for t in r["tags"].split(",") if t); rules = [TAG_RULES[t] + f" (flagged {n}×)" for t, n in tags.most_common() if t in TAG_RULES and n >= 2]
    good = [r for r in rows if r["rating"] >= 4]; by = Counter(r["channel"] for r in good)
    if good:
        aw = round(sum(len(words(r["body"])) for r in good) / len(good)); rules.append(f"Top-rated pieces average ~{aw} words" + (f"; best channel so far: {by.most_common(1)[0][0]}." if by else "."))
    return {"count": len(rows), "avg_rating": round(sum(r["rating"] for r in rows) / len(rows), 2) if rows else None, "tags": [{"tag": t, "count": n} for t, n in tags.most_common()], "rules": rules}

# ---------- comparison ----------
def campaign_stats(cid):
    camp = q("SELECT * FROM campaigns WHERE id=?", (cid,), True)
    if not camp: raise LookupError("Campaign not found")
    brand = brand_of_campaign(cid); cs = q("SELECT * FROM contents WHERE campaign_id=?", (cid,)); n = len(cs)
    ql = [quality(c["body"], c["channel"], brand, c["language"]) for c in cs]
    fb = q("SELECT AVG(rating) a, COUNT(*) n FROM feedback WHERE content_id IN (SELECT id FROM contents WHERE campaign_id=?)", (cid,), True)
    dups = sum(1 for i in range(n) for j in range(i + 1, n) if similarity(cs[i]["body"], cs[j]["body"]) >= .6)
    return {"id": cid, "name": camp["name"], "pieces": n, "channels": dict(Counter(c["channel"] for c in cs)), "languages": sorted({c["language"] for c in cs}),
            "avg_quality": round(sum(r["overall"] for r in ql) / n) if n else 0, "approved_rate": round(100 * sum(c["status"] in ("approved", "ready") for c in cs) / n) if n else 0,
            "avg_rating": round(fb["a"], 2) if fb["a"] else None, "feedback_count": fb["n"], "avg_words": round(sum(r["stats"]["words"] for r in ql) / n) if n else 0,
            "cta_coverage": round(100 * sum(next(m["score"] for m in r["metrics"] if m["key"] == "cta") == 100 for r in ql) / n) if n else 0,
            "scheduled": q("SELECT COUNT(*) n FROM calendar WHERE campaign_id=?", (cid,), True)["n"], "duplicate_pairs": dups}

def compare(a, b):
    A, B = campaign_stats(a), campaign_stats(b); win = {}
    for k, hi in [("avg_quality", 1), ("approved_rate", 1), ("avg_rating", 1), ("cta_coverage", 1), ("pieces", 1), ("scheduled", 1), ("duplicate_pairs", 0)]:
        va, vb = A[k] or 0, B[k] or 0; win[k] = "tie" if va == vb else ("A" if (va > vb) == bool(hi) else "B")
    wa = sum(v == "A" for v in win.values()); wb = sum(v == "B" for v in win.values())
    verdict = f"{A['name']} leads on {wa} metrics; {B['name']} leads on {wb}." if wa != wb else "The campaigns are evenly matched."
    return {"a": A, "b": B, "winners": win, "verdict": verdict}

# ---------- approval workflow ----------
def transition(cid, action, reviewer, note):
    c = q("SELECT * FROM contents WHERE id=?", (cid,), True)
    if not c: raise LookupError("Content not found")
    if action not in TRANSITIONS: raise ValueError("Unknown workflow action")
    frm, to = TRANSITIONS[action]
    if c["status"] not in frm: raise ValueError(f"Cannot {action.replace('_', ' ')} while status is '{c['status']}'.")
    if action in ("approve", "request_changes", "reject", "mark_ready") and not reviewer.strip(): raise ValueError("Reviewer name is required.")
    if action in ("request_changes", "reject") and not note.strip(): raise ValueError("A note explaining the decision is required.")
    if action == "mark_ready":
        qs = quality(c["body"], c["channel"], brand_of_content(cid), c["language"])["overall"]
        if qs < MIN_READY_QUALITY: raise ValueError(f"Quality score {qs} is below the publication threshold of {MIN_READY_QUALITY}. Refine the content first.")
    x("UPDATE contents SET status=?,updated=? WHERE id=?", (to, now(), cid))
    x("INSERT INTO approvals(content_id,action,from_status,to_status,reviewer,note,created) VALUES(?,?,?,?,?,?,?)", (cid, action, c["status"], to, reviewer.strip() or "author", note.strip(), now()))
    log("workflow", f"'{c['title'][:40]}' → {to.replace('_', ' ')}")
    return to
