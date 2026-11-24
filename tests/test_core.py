import os, re, sys, tempfile, unittest
from datetime import date
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import importer
from eligibility import evaluate
from app import create_app
import seed


class Core(unittest.TestCase):
    def test_phone(self):
        self.assertEqual(importer.norm_phone("+91 86799 51794"), "8679951794")
        self.assertEqual(importer.norm_phone("06133252695"), "6133252695")
        self.assertIsNone(importer.norm_phone("992141534"))
        self.assertIsNone(importer.norm_phone("98765abc21"))

    def test_dates_and_city(self):
        self.assertIsNone(importer.norm_date("31/02/1995"))
        self.assertEqual(importer.norm_date("01-03-84").year, 1984)
        self.assertEqual(importer.norm_city(" Bombay"), "Mumbai")
        self.assertEqual(importer.norm_city("NaviMumbai"), "Navi Mumbai")

    def test_import_does_not_crash_on_garbage(self):
        rows, rep, c = importer.parse_csv("phone,name\n,\nxyz,Bob\n9876543210,\n")
        self.assertEqual(c["imported"], 1)
        self.assertEqual(c["skipped"], 2)

    def survey(self, **kw):
        s = dict(deadline="2026-12-01", quota=None, age_min=18, age_max=35, age_strict=1, city="Mumbai",
                 city_strict=0, gender=None, gender_strict=1, income_ranges=None, income_strict=0)
        s.update(kw); return s

    def member(self, **kw):
        m = dict(dob="1995-01-01", city="Mumbai", gender="Female", income_range="3L-6L", last_survey_completed_on=None)
        m.update(kw); return m

    def test_eligibility(self):
        t = date(2026, 11, 20)
        self.assertEqual(evaluate(self.member(), self.survey(), t)["status"], "Approved")
        r = evaluate(self.member(dob="2009-06-01"), self.survey(), t)
        self.assertEqual(r["status"], "Rejected"); self.assertIn("age 17, this survey needs 18 to 35", r["reason"])
        self.assertEqual(evaluate(self.member(city="Pune"), self.survey(), t)["status"], "Waitlisted")
        self.assertEqual(evaluate(self.member(), self.survey(quota=5), t, 5)["status"], "Rejected")
        self.assertEqual(evaluate(self.member(), self.survey(deadline="2026-11-01"), t)["status"], "Rejected")
        r = evaluate(self.member(last_survey_completed_on="2026-10-01"), self.survey(), t)
        self.assertEqual(r["status"], "Rejected"); self.assertEqual(str(r["eligible_again"]), "2027-01-01")


class Web(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["VIEWBOX_DB"] = os.path.join(cls.tmp, "t.db")
        seed.create_app = lambda: create_app({"DATABASE": os.environ["VIEWBOX_DB"]})
        seed.main()
        cls.app = create_app({"DATABASE": os.environ["VIEWBOX_DB"], "TESTING": True})

    def login(self, c, phone, **extra):
        c.post("/login", data={"phone": phone, **extra})
        otp = re.search(r'class="otp">(\d+)<', c.get("/verify").get_data(as_text=True)).group(1)
        return c.post("/verify", data={"code": otp})

    def test_tracked_link_and_signup(self):
        c = self.app.test_client()
        c.get("/s/instagram")
        r = self.login(c, "9111111111", referrer="VB10000")
        self.assertEqual(r.status_code, 302)
        import sqlite3
        row = sqlite3.connect(os.environ["VIEWBOX_DB"]).execute(
            """SELECT s.name, f.name, r.member_code FROM members m JOIN sources s ON s.id=m.source_id
               JOIN sources f ON f.id=m.first_touch_source_id LEFT JOIN members r ON r.id=m.referred_by_id
               WHERE m.phone='9111111111'""").fetchone()
        self.assertEqual(row, ("Instagram", "Instagram", "VB10000"))  # channel credit AND typed referrer both kept

    def test_untagged_asks_how_heard(self):
        c = self.app.test_client()
        r = c.post("/login", data={"phone": "9222222222"})
        self.assertEqual(r.status_code, 400)

    def test_meta_lead(self):
        c = self.app.test_client()
        lead = {"id": "L1", "campaign_id": "C9", "form_id": "F1", "field_data": [
            {"name": "full_name", "values": ["Test Lead"]}, {"name": "phone_number", "values": ["+919333333333"]}]}
        self.assertEqual(c.post("/api/meta/leads", json=lead).status_code, 201)
        self.assertEqual(c.post("/api/meta/leads", json=lead).json["status"], "duplicate")
        bad = c.post("/api/meta/leads", json={"id": "L2", "field_data": []})
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(c.post("/api/meta/leads", data="not json").status_code, 400)

    def test_admin_requires_login_and_exports(self):
        c = self.app.test_client()
        self.assertEqual(c.get("/admin/members").status_code, 302)
        c.post("/admin/login", data={"username": "admin", "password": "admin123"})
        self.assertIn("member_code", c.get("/admin/members/export.csv?q=Priya").get_data(as_text=True))
        self.assertEqual(c.get("/admin/members/export.xlsx").status_code, 200)
        for p in ["/admin", "/admin/sources", "/admin/surveys", "/admin/surveys/1", "/admin/import", "/admin/meta-leads", "/admin/members/5"]:
            self.assertEqual(c.get(p).status_code, 200, p)

    def test_member_pages_and_masking(self):
        c = self.app.test_client()
        self.login(c, "9000000001")
        html = c.get("/home").get_data(as_text=True)
        self.assertIn("Mumbai Shopping Habits", html)
        self.assertIn("/r/DEMO01", c.get("/referrals").get_data(as_text=True))
        self.assertEqual(importer.norm_phone("9876543221"), "9876543221")


if __name__ == "__main__":
    unittest.main()
