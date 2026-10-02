"""Sample data so the dashboard can be explored immediately."""
import json
from datetime import date, timedelta
from db import q, x
from services import create_content, now, log

def seed():
    if q("SELECT 1 FROM brands LIMIT 1"): return
    ts = now()
    b = x("INSERT INTO brands(name,description,voice,tone,dos,donts,keywords,audience,created) VALUES(?,?,?,?,?,?,?,?,?)",
          ("Aaraa Millets", "Coimbatore-based millet snack brand sourcing directly from Tamil Nadu farmers.", "Warm, honest, rooted in tradition but modern.",
           "Friendly, proud, never preachy", "Mention farmer sourcing; use simple words; one clear call to action", "miracle, cure, guaranteed, cheap",
           "millet, ragi, healthy, farmers, traditional", "Urban families and young professionals in South India who want healthier snacks", ts))
    def camp(n, g, br): return x("INSERT INTO campaigns(brand_id,name,goal,brief,analysis,created) VALUES(?,?,?,?,?,?)", (b, n, g, br, "", ts))
    c1 = camp("Pongal Millet Gift Box", "Drive festive gift-box sales before Pongal", "Launch a Pongal gift box with ragi cookies, millet murukku and jaggery bites. Target families gifting during Pongal. Ship across Tamil Nadu within 3 days. Ask people to order online before the festival.")
    c2 = camp("Summer Ragi Cooler Launch", "Introduce ragi cooler mix to young professionals", "New instant ragi cooler mix for summer. Audience: young professionals and college students. Position as a quick, healthy alternative to sugary drinks. Launch in April; drive sign-ups for sampling.")
    c3 = camp("Farmer Stories", "Build trust through sourcing transparency", "A monthly series introducing the farmers behind our millets. Build trust and brand love among families. Publish on LinkedIn and the blog.")
    pieces = [
     (c1, "instagram", "Pongal gifting, made healthier", "🌾 This Pongal, gift something that loves them back.\n\nOur new Pongal Gift Box brings ragi cookies, millet murukku and jaggery bites - sourced from farmers we know by name.\n\nOrder online before the festival. Tap the link in bio.\n\n#Millet #Pongal #HealthySnacks #Farmers", "sample", "ready"),
     (c1, "email", "Subject: Your Pongal gift box is here", "Subject: Your Pongal gift box is here\n\nHi there,\n\nPongal is about sharing. This year, share something wholesome: our Gift Box with ragi cookies, millet murukku and jaggery bites, made with millets from farmers across Tamil Nadu.\n\nOrder before the festival and we will deliver within three days.\n\nWarm regards,\nTeam Aaraa", "sample", "approved"),
     (c1, "ad", "Pongal Gift Box", "A Pongal gift that is healthy and honest. Millet snacks from farmers we know. Order now →", "sample", "in_review"),
     (c2, "instagram", "Meet the ragi cooler", "Why does your afternoon drink need 6 spoons of sugar? 🥤\n\nMeet our instant ragi cooler: cold, filling and made from millet. Just add water and chill.\n\nSign up for a free sample today!\n\n#Ragi #SummerDrinks #Healthy", "sample", "draft"),
     (c2, "video", "15s ragi cooler reel", "[0-3s] Hook: hand shakes a bottle, text \"3 minutes. Zero sugar rush.\"\n[3-10s] Pour ragi cooler mix, add cold water, stir; voiceover: \"Millet energy, ready when you are.\"\n[10-15s] CTA: \"Get your free sample\" + logo", "sample", "changes_requested"),
     (c3, "linkedin", "Meet Selvi from Dharmapuri", "What does it take to bring millet from a farm to your kitchen?\n\nThis month we visited Selvi, a ragi farmer in Dharmapuri who has grown millets for 20 years. She told us fair pricing changed how her family plans the year.\n\nWe believe transparent sourcing builds trust. Read her story and tell us whose story we should feature next.\n\n#Millets #Farmers #Sustainability", "sample", "approved"),
     (c3, "blog", "Why we name our farmers", "# Why we name our farmers\n\nMost snack labels tell you what is inside. Few tell you who grew it.\n\n## Trust starts at the source\nWhen we buy ragi, we buy from farmers we have met. Learn more about our sourcing on our site.\n\n## What is next\nEvery month we will publish a story from the fields. Subscribe to follow along.", "sample", "draft")]
    ids = []
    for cp, ch, t, body, src, st in pieces:
        i = create_content(cp, ch, t, body, "English", src, status=st); ids.append(i)
        if st in ("approved", "ready", "in_review", "changes_requested"):
            x("INSERT INTO approvals(content_id,action,from_status,to_status,reviewer,note,created) VALUES(?,?,?,?,?,?,?)", (i, "submit", "draft", "in_review", "author", "", ts))
        if st in ("approved", "ready"):
            x("INSERT INTO approvals(content_id,action,from_status,to_status,reviewer,note,created) VALUES(?,?,?,?,?,?,?)", (i, "approve", "in_review", "approved", "Priya (Brand Lead)", "Looks good.", ts))
        if st == "ready":
            x("INSERT INTO approvals(content_id,action,from_status,to_status,reviewer,note,created) VALUES(?,?,?,?,?,?,?)", (i, "mark_ready", "approved", "ready", "Priya (Brand Lead)", "", ts))
        if st == "changes_requested":
            x("INSERT INTO approvals(content_id,action,from_status,to_status,reviewer,note,created) VALUES(?,?,?,?,?,?,?)", (i, "request_changes", "in_review", "changes_requested", "Priya (Brand Lead)", "Hook is weak; add stronger CTA.", ts))
    for cid, r, tags, cm in [(ids[0], 5, "great hook,on brand", "Love it"), (ids[1], 4, "clear cta", ""), (ids[2], 3, "too long", ""), (ids[3], 2, "weak cta,generic", "Feels generic"),
                             (ids[4], 2, "weak hook,generic", ""), (ids[5], 5, "on brand", "Authentic"), (ids[6], 3, "too long,generic", "")]:
        x("INSERT INTO feedback(content_id,rating,tags,comment,created) VALUES(?,?,?,?,?)", (cid, r, tags, cm, ts))
    t = date.today()
    for k, (cp, cid, ch, title) in enumerate([(c1, ids[0], "instagram", "Pongal gift box reveal"), (c1, ids[1], "email", "Gift box email"), (c2, ids[3], "instagram", "Ragi cooler teaser"),
                                              (c2, ids[4], "video", "Cooler reel"), (c3, ids[5], "linkedin", "Farmer story: Selvi")]):
        x("INSERT INTO calendar(campaign_id,content_id,date,channel,title,notes,status,created) VALUES(?,?,?,?,?,?,?,?)", (cp, cid, (t + timedelta(days=2 + 3 * k)).isoformat(), ch, title, "", "planned", ts))
    x("INSERT INTO personas(campaign_id,data,source,created) VALUES(?,?,?,?)", (c1, json.dumps({"personas": [{"name": "Meena, the Festive Planner", "age_range": "32-45", "role": "Homemaker / working parent", "goals": ["Thoughtful gifts", "Healthier festival treats"], "pain_points": ["Too much sugar in gift boxes"], "channels": ["instagram", "email"], "tone_that_works": "Warm and reassuring", "sample_hook": "Gift wholesome this Pongal."}]}), "sample", ts))
    x("INSERT INTO visuals(campaign_id,content_id,title,prompt,style,aspect,image,source,created) VALUES(?,?,?,?,?,?,?,?,?)", (c1, None, "Gift box hero", "Editorial photograph of a handwoven basket gift box with ragi cookies and millet murukku on a banana leaf, warm morning light, marigold and terracotta palette, shallow depth of field, festive Pongal mood", "editorial photography", "4:5", "", "sample", ts))
    log("system", "Sample data loaded")
