import os, sys, tempfile, unittest
from unittest import mock
os.environ["VAGO_DB"] = os.path.join(tempfile.mkdtemp(), "test.db"); os.environ.pop("GEMINI_API_KEY", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import app as vago, ai, services as S

class T(unittest.TestCase):
    def setUp(self): self.c = vago.app.test_client()

    def test_sample_data_and_status(self):
        self.assertEqual(self.c.get("/api/status").json["mode"], "demo")
        self.assertGreaterEqual(self.c.get("/api/dashboard").json["totals"]["campaigns"], 3)
        self.assertEqual(self.c.get("/").status_code, 200)

    def test_generate_demo_is_labelled(self):
        r = self.c.post("/api/generate", json={"campaign_id": 2, "formats": ["instagram", "email"]}); self.assertEqual(r.status_code, 201); self.assertEqual(r.json["mode"], "demo")
        self.assertEqual(self.c.get(f"/api/contents/{r.json['ids'][0]}").json["source"], "demo")

    def test_validation(self):
        self.assertEqual(self.c.post("/api/generate", json={"campaign_id": 1, "formats": []}).status_code, 400)
        self.assertEqual(self.c.post("/api/campaigns", json={"brand_id": 1, "name": ""}).status_code, 400)
        self.assertEqual(self.c.get("/api/contents/99999").status_code, 404)

    def test_translate_requires_key(self): self.assertEqual(self.c.post("/api/contents/1/translate", json={"language": "Tamil"}).status_code, 501)

    def test_quality_is_explainable(self):
        q = S.quality("Why wait? Order our ragi cookies today! #Millet #Healthy #Ragi", "instagram", {"keywords": "ragi,millet"})
        self.assertTrue(all(m["detail"] for m in q["metrics"])); self.assertGreater(q["overall"], 60)
        self.assertLess(S.quality("buy", "blog")["overall"], q["overall"])

    def test_duplicates(self):
        body = self.c.get("/api/contents/1").json["body"]; r = self.c.post("/api/duplicates", json={"text": body}).json
        self.assertEqual(r["matches"][0]["verdict"], "duplicate")

    def test_refine_versions_restore(self):
        v = self.c.post("/api/contents/4/refine", json={"instruction": "make it shorter"}).json["version"]; self.assertEqual(v, 2)
        self.assertEqual(self.c.post("/api/contents/4/restore", json={"version": 1}).json["version"], 3)
        self.assertEqual(self.c.post("/api/contents/4/refine", json={"instruction": "write a haiku"}).status_code, 501)

    def test_workflow_rules(self):
        wf = lambda i, a, r="Asha", n="": self.c.post(f"/api/contents/{i}/workflow", json={"action": a, "reviewer": r, "note": n})
        self.assertEqual(wf(4, "mark_ready").status_code, 400)          # draft cannot skip review
        self.assertEqual(wf(4, "submit").status_code, 200); self.assertEqual(wf(4, "approve", "").status_code, 400)  # reviewer required
        self.assertEqual(wf(4, "request_changes").status_code, 400)     # note required
        self.assertEqual(wf(4, "approve").json["status"], "approved"); self.assertEqual(wf(4, "mark_ready").json["status"], "ready")
        self.c.put("/api/contents/4", json={"title": "x", "body": "Edited body text. Order now."}); self.assertEqual(self.c.get("/api/contents/4").json["status"], "draft")

    def test_calendar_crud(self):
        e = self.c.post("/api/calendar", json={"campaign_id": 1, "title": "Test", "date": "2026-12-01", "channel": "email"}).json
        self.assertEqual(self.c.put(f"/api/calendar/{e['id']}", json={**e, "date": "2026-12-05"}).json["date"], "2026-12-05")
        self.assertEqual(self.c.post("/api/calendar", json={"campaign_id": 1, "title": "x", "date": "bad"}).status_code, 400)
        self.assertEqual(self.c.delete(f"/api/calendar/{e['id']}").status_code, 200)
        self.assertGreater(self.c.post("/api/calendar/generate", json={"campaign_id": 2, "days": 10}).json["added"], 0)

    def test_compare_and_feedback_learning(self):
        self.assertIn("verdict", self.c.get("/api/compare?a=1&b=3").json); self.assertEqual(self.c.get("/api/compare?a=1&b=1").status_code, 400)
        self.assertTrue(any("generic" in r.lower() for r in self.c.get("/api/insights?brand_id=1").json["rules"]))
        self.assertEqual(self.c.post("/api/contents/1/feedback", json={"rating": 9}).status_code, 400)

    def test_visuals_personas_ideas_seo_export(self):
        self.assertEqual(self.c.post("/api/visuals", json={"campaign_id": 1}).status_code, 201)
        self.assertEqual(self.c.post("/api/visuals/1/image", json={}).status_code, 501)   # not configured -> honest error
        self.assertEqual(self.c.post("/api/personas", json={"campaign_id": 1}).status_code, 201)
        self.assertTrue(self.c.post("/api/ideas", json={"brand_id": 1, "goal": "sales"}).json["ideas"])
        self.assertIn("score", self.c.post("/api/contents/7/seo", json={"keyword": "farmers"}).json["local"])
        self.assertIn("attachment", self.c.get("/api/contents/1/export?fmt=md").headers["Content-Disposition"])

    def test_live_mode_uses_gemini_and_surfaces_errors(self):
        fake = {"items": [{"format": "instagram", "title": "Live", "body": "Live body. Order now! #a #b #c"}]}
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}), mock.patch.object(ai, "_gen", return_value=fake):
            r = self.c.post("/api/generate", json={"campaign_id": 1, "formats": ["instagram"], "language": "Tamil"}); self.assertEqual(r.json["mode"], "gemini")
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}), mock.patch.object(ai, "_post", side_effect=ai.AIError("quota")):
            self.assertEqual(self.c.post("/api/brief/analyze", json={"campaign_id": 1}).status_code, 502)

if __name__ == "__main__": unittest.main()
