"""Gemini integration + clearly-labelled demo fallbacks.
run() returns (result, mode) where mode is 'gemini' or 'demo'. Live failures raise AIError -
we NEVER silently substitute template output for a failed live call."""
import os, re, json, base64, uuid, requests
from datetime import date, timedelta
from urllib.parse import quote
API = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
CH = {"instagram": "Instagram post", "linkedin": "LinkedIn post", "blog": "Blog article", "ad": "Ad copy", "email": "Email", "video": "Short video script"}

class AIError(Exception):
    def __init__(self, msg, status=502):
        super().__init__(msg); self.status = status

def api_key(): return os.getenv("GEMINI_API_KEY", "").strip()
def is_live(): return bool(api_key())
def model(): return os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
def image_enabled():
    if os.getenv("ENABLE_IMAGE_GEN", "false").lower() != "true": return False
    return os.getenv("IMAGE_PROVIDER", "gemini") == "pollinations" or is_live()

def _post(mdl, payload):
    try:
        r = requests.post(API.format(mdl), headers={"x-goog-api-key": api_key(), "Content-Type": "application/json"}, json=payload, timeout=120)
    except requests.RequestException as e:
        raise AIError(f"Could not reach Gemini: {e}")
    if r.status_code != 200:
        try: msg = r.json()["error"]["message"]
        except Exception: msg = r.text[:200]
        raise AIError(f"Gemini API error {r.status_code}: {msg}")
    return r.json()

def parse_json(t):
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t.strip())
    try: return json.loads(t)
    except ValueError: raise AIError("Gemini returned malformed JSON. Please retry.")

SYSTEM = ("You are Vago, a senior brand strategist and copywriter. Follow the brand voice strictly. Never invent statistics, prices, "
          "awards or testimonials. Write in the requested language. Output must be valid JSON only.")

def _gen(prompt):
    data = _post(model(), {"systemInstruction": {"parts": [{"text": SYSTEM}]}, "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                           "generationConfig": {"responseMimeType": "application/json", "temperature": 0.8, "maxOutputTokens": 8192}})
    try: return parse_json("".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"]))
    except (KeyError, IndexError): raise AIError("Gemini returned an empty response (possibly blocked by safety filters).")

TASKS = {
 "brief": ("Analyze this campaign brief like a senior strategist. Ground everything in the brief; flag gaps and risks.",
  '{"summary":"","objective":"","audience":"","tone":"","key_messages":[""],"deliverables":[""],"risks":[""],"missing_info":[""],"questions":[""],"recommended_formats":["instagram|linkedin|blog|ad|email|video"],"clarity_score":0}'),
 "generate": ("Write ready-to-publish content for EACH requested format using brand voice, dos/donts, keywords, learned_rules, persona and language in the context. "
  "Conventions: instagram=hook+short caption+hashtags; linkedin=insight-led professional post; blog=markdown with H1/H2 and 600+ words; ad=headline+primary text under 45 words; "
  "email=subject line then body; video=scene-by-scene script with timings (30-45s). Put hashtags inside body.",
  '{"items":[{"format":"instagram","title":"","body":""}]}'),
 "adapt": ("Adapt the source content to the target channel's conventions and length while keeping the core message and brand voice.", '{"title":"","body":""}'),
 "refine": ("Rewrite the content following the instruction exactly. Keep facts unchanged.", '{"title":"","body":"","summary_of_changes":""}'),
 "translate": ("Translate and culturally localise (not literal) into the target language. Keep brand names, hashtags and formatting.", '{"title":"","body":""}'),
 "ideas": ("Generate distinct, original campaign ideas for this brand and goal. Avoid clichés.", '{"ideas":[{"title":"","concept":"","hook":"","formats":["instagram"],"effort":"low|medium|high"}]}'),
 "calendar": ("Build a content calendar. Use ISO dates (YYYY-MM-DD) from start_date across `days`, vary channels, sequence a story arc (tease, launch, proof, urgency). "
  "If existing contents are given, schedule them (include content_id).", '{"entries":[{"date":"YYYY-MM-DD","channel":"instagram","title":"","notes":"","content_id":null}]}'),
 "visual": ("Write detailed, production-ready image-generation prompts for campaign visuals: subject, composition, lighting, palette, style, mood, camera. No text-in-image unless essential.",
  '{"prompts":[{"title":"","prompt":"","style":"","aspect":"1:1|4:5|16:9|9:16"}]}'),
 "persona": ("Create realistic, distinct audience personas grounded in the brand and brief. Do not invent statistics.",
  '{"personas":[{"name":"","age_range":"","role":"","goals":[""],"pain_points":[""],"channels":[""],"tone_that_works":"","sample_hook":""}]}'),
 "seo": ("Give SEO recommendations for this content.", '{"title_options":[""],"meta_description":"","keywords":[""],"headings":[""],"improvements":[""]}'),
 "critique": ("Critique this content honestly against the brand voice and channel.", '{"strengths":[""],"weaknesses":[""],"suggestions":[""]}'),
 "chat": ("You are an editing assistant. Apply the user's request to the content and reply briefly. If the request is a question, answer it and return the content unchanged.", '{"reply":"","title":"","body":""}'),
}

def run(task, ctx):
    if not is_live():
        return DEMO[task](ctx), "demo"
    do, shape = TASKS[task]
    return _gen(f"{do}\n\nCONTEXT (JSON):\n{json.dumps(ctx, ensure_ascii=False)}\n\nReturn ONLY JSON shaped like:\n{shape}"), "gemini"

def image_enabled():
    if os.getenv("ENABLE_IMAGE_GEN", "false").lower() != "true":
        return False
    # Free provider needs no Gemini key; Gemini image model needs one
    return os.getenv("IMAGE_PROVIDER", "gemini").lower() == "pollinations" or is_live()

def _save_image(data, out_dir, ext="png"):
    name = f"{uuid.uuid4().hex}.{ext}"
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, name), "wb") as f:
        f.write(data)
    return name

def generate_image(prompt, out_dir):
    if not image_enabled():
        raise AIError("Image generation is not configured. Set ENABLE_IMAGE_GEN=true in .env, or paste the prompt into any image tool.", 501)

    provider = os.getenv("IMAGE_PROVIDER", "gemini").lower()

    # Option A: free provider (no billing, no Gemini quota)
    if provider == "pollinations":
        try:
            r = requests.get("https://image.pollinations.ai/prompt/" + quote(prompt[:900]),
                             params={"width": 1024, "height": 1024, "nologo": "true"}, timeout=120)
        except requests.RequestException as e:
            raise AIError(f"Image service unreachable: {e}")
        if r.status_code != 200 or not r.content:
            raise AIError(f"Image service error {r.status_code}. Try again in a minute.")
        return _save_image(r.content, out_dir, "jpg")

    # Option B: Gemini image model (may need billing on free keys)
    data = _post(os.getenv("IMAGE_MODEL", "gemini-3.1-flash-image"),
                 {"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}})
    try:
        for p in data["candidates"][0]["content"]["parts"]:
            b = p.get("inlineData") or p.get("inline_data")
            if b:
                return _save_image(base64.b64decode(b["data"]), out_dir)
    except (KeyError, IndexError):
        pass
    raise AIError("The image model returned no image (prompt may have been blocked).")

# ---------------- DEMO (template / heuristic - NOT AI) ----------------
def _sents(t): return [s.strip() for s in re.split(r"(?<=[.!?])\s+", t.strip()) if s.strip()]
def _first(t, n=160): s = (_sents(t) or [t or ""])[0]; return s[:n]
def _needs_key(what): raise AIError(f"{what} needs a Gemini API key. Demo mode cannot do this honestly - add GEMINI_API_KEY to .env.", 501)

def d_brief(c):
    t = c.get("brief", ""); low = t.lower(); s = _sents(t)
    checks = [("budget|₹|rs\\.|\\$", "Budget not mentioned"), ("deadline|date|week|month|launch|festival|season", "Timeline not mentioned"),
              ("audience|customers|people|women|men|students|families|farmers", "Target audience unclear"), ("buy|order|sign|visit|download|subscribe|register|shop", "Desired action unclear")]
    miss = [m for k, m in checks if not re.search(k, low)]
    return {"summary": " ".join(s[:2]) or "No brief text.", "objective": c.get("goal") or "Not stated", "audience": c.get("audience") or "Not stated",
            "tone": c.get("tone") or "Not stated", "key_messages": s[:4], "deliverables": ["Instagram post", "LinkedIn post", "Email"], "risks": ["Keyword heuristics only - enable Gemini for real risk analysis."],
            "missing_info": miss, "questions": [f"Please clarify: {m.lower()}" for m in miss], "recommended_formats": ["instagram", "linkedin", "email"],
            "clarity_score": max(25, 92 - 15 * len(miss) - (20 if len(t) < 80 else 0))}

def d_generate(c):
    b = c.get("brand") or {}; camp = c.get("campaign") or {}
    n = b.get("name") or "Our brand"; goal = camp.get("goal") or camp.get("name") or "our latest launch"; br = _first(camp.get("brief", ""), 200) or goal
    kw = [k.strip() for k in (b.get("keywords") or "").split(",") if k.strip()][:4]
    tags = " ".join("#" + re.sub(r"\W", "", k.title()) for k in kw) or "#" + re.sub(r"\W", "", n)
    T = {"instagram": (f"{n}: {goal}", f"✨ {goal}\n\n{br}\n\nTap the link in bio to explore.\n\n{tags}"),
         "linkedin": (f"{goal} - what we learned", f"Why does {goal.lower()} matter?\n\n{br}\n\nHere is our approach:\n• Start with the customer\n• Be transparent\n• Measure what matters\n\nJoin the conversation - what would you add?\n\n{tags}"),
         "blog": (f"{goal}: a practical guide", f"# {goal}\n\n{br}\n\n## Why it matters\nExplain the problem your audience faces and why {n} cares.\n\n## How {n} approaches it\nDescribe the approach in plain language.\n\n## What to do next\nVisit our site to learn more and get started."),
         "ad": (f"{goal}", f"{goal}. {br[:90]} Shop now →"),
         "email": (f"Subject: {goal}", f"Subject: {goal}\n\nHi there,\n\n{br}\n\nReady to try it? Reply or visit our store to order today.\n\nWarm regards,\n{n}"),
         "video": (f"15s video: {goal}", f"[0-3s] Hook: on-screen text \"{goal}\"\n[3-10s] Show the product in use; voiceover: {br[:100]}\n[10-15s] CTA: \"Order now\" + logo\n\n{tags}")}
    return {"items": [{"format": f, "title": T[f][0], "body": T[f][1]} for f in c.get("formats", []) if f in T]}

def d_adapt(c):
    body, t = c.get("body", ""), c.get("target"); first = _first(body, 140); n = (c.get("brand") or {}).get("name", "")
    m = {"instagram": body[:280] + ("…" if len(body) > 280 else ""), "linkedin": f"Here's what we've been building:\n\n{body}\n\nWhat do you think?",
         "blog": f"# {c.get('title','')}\n\n{body}", "ad": first[:90] + " Learn more →", "email": f"Subject: {c.get('title','')}\n\nHi there,\n\n{body}\n\nWarm regards,\n{n}",
         "video": f"[0-5s] {first}\n[5-12s] {' '.join(_sents(body)[1:3])[:140]}\n[12-15s] CTA + logo"}
    return {"title": c.get("title", ""), "body": m.get(t, body)}

def d_refine(c):
    ins = c.get("instruction", "").lower(); body = c.get("body", ""); s = _sents(body); title = c.get("title", "")
    if "short" in ins: body = " ".join(s[:max(1, len(s) // 2)]); note = "Kept the first half of the sentences."
    elif "punch" in ins: body = "\n".join(s); note = "Split into one sentence per line."
    elif "cta" in ins or "call to action" in ins: body += "\n\nTake the next step today - visit our site."; note = "Appended a call to action."
    elif "emoji" in ins: body = "✨ " + body; note = "Added an emoji."
    elif "hashtag" in ins and "remove" in ins: body = re.sub(r"\s*#\w+", "", body).strip(); note = "Removed hashtags."
    else: _needs_key("Free-form rewriting")
    return {"title": title, "body": body, "summary_of_changes": note + " (demo rule, not AI)"}

def d_translate(c): _needs_key("Translation")
def d_chat(c):
    r = d_refine({"instruction": c.get("message", ""), "body": c.get("body", ""), "title": c.get("title", "")}) if True else None
    return {"reply": r["summary_of_changes"], "title": r["title"], "body": r["body"]}

def d_ideas(c):
    n = c.get("brand", {}).get("name", "Your brand"); g = c.get("goal") or "growth"; k = int(c.get("count", 5))
    base = [("Behind the scenes", "Show how the product is made, step by step."), ("Myth vs fact", "Bust three common myths in your category."),
            ("Customer spotlight", "Feature one real customer story (with permission)."), ("30-day challenge", "Invite the audience to try the product daily."),
            ("Festival special", "Tie a limited edition to an upcoming festival."), ("Ask me anything", "Live Q&A with the founder.")]
    return {"ideas": [{"title": f"{t}", "concept": f"{d} Goal: {g}.", "hook": f"What {n} does differently", "formats": ["instagram", "video"], "effort": "medium"} for t, d in base[:k]]}

def d_calendar(c):
    st = date.fromisoformat(c["start_date"]); days = int(c.get("days", 14)); chs = c.get("channels") or ["instagram", "linkedin", "email", "video"]
    ex = c.get("contents") or []; out = []
    step = max(1, days // max(1, len(ex) or 6))
    if ex:
        for i, e in enumerate(ex): out.append({"date": (st + timedelta(days=i * step)).isoformat(), "channel": e["channel"], "title": e["title"], "notes": "Scheduled from existing content", "content_id": e["id"]})
    else:
        for i in range(6): out.append({"date": (st + timedelta(days=i * step)).isoformat(), "channel": chs[i % len(chs)], "title": f"Post {i+1}: {['Tease','Launch','Proof','Story','Offer','Last call'][i]}", "notes": "Placeholder slot (demo)", "content_id": None})
    return {"entries": out}

def d_visual(c):
    n = c.get("brand", {}).get("name", "the brand"); s = c.get("style") or "clean editorial photography"; subj = c.get("subject") or c.get("campaign", {}).get("name", "the product")
    tone = c.get("brand", {}).get("tone") or "warm"
    v = [("Hero shot", f"{s} of {subj} for {n}, centered composition, soft natural window light, shallow depth of field, {tone} mood, uncluttered background, high detail", "1:1"),
         ("Lifestyle", f"{s}, people enjoying {subj} in an everyday setting, candid framing, golden-hour light, {tone} mood, authentic textures", "4:5"),
         ("Minimal flat-lay", f"{s}, top-down flat-lay of {subj} with 2-3 props, generous negative space for copy, muted palette, soft shadows", "16:9")]
    return {"prompts": [{"title": t, "prompt": p, "style": s, "aspect": a} for t, p, a in v][:int(c.get("count", 3))]}

def d_persona(c):
    a = c.get("brand", {}).get("audience") or "your customers"
    return {"personas": [{"name": n, "age_range": r, "role": f"Segment of {a}", "goals": ["Get reliable value", "Save time"], "pain_points": ["Too many choices", "Low trust in claims"],
            "channels": ch, "tone_that_works": t, "sample_hook": h} for n, r, ch, t, h in [
            ("The Practical Planner", "28-40", ["email", "linkedin"], "Clear and factual", "Here is exactly what you get."),
            ("The Curious Explorer", "18-27", ["instagram", "video"], "Playful and visual", "Ever tried this?"),
            ("The Loyal Advocate", "35-55", ["email", "instagram"], "Warm and appreciative", "Thanks for being with us.")]]}

def d_seo(c):
    words = [w for w in re.findall(r"[a-zA-Z]{5,}", c.get("body", "").lower())]
    top = [w for w, _ in __import__("collections").Counter(words).most_common(5)]
    return {"title_options": [c.get("title", "")[:60]], "meta_description": " ".join(c.get("body", "").split())[:155], "keywords": top, "headings": [], "improvements": ["Demo mode: only keyword counts. Enable Gemini for rewrite suggestions."]}

def d_critique(c): return {"strengths": [], "weaknesses": [], "suggestions": []}

DEMO = {"brief": d_brief, "generate": d_generate, "adapt": d_adapt, "refine": d_refine, "translate": d_translate, "ideas": d_ideas, "calendar": d_calendar,
        "visual": d_visual, "persona": d_persona, "seo": d_seo, "critique": d_critique, "chat": d_chat}
