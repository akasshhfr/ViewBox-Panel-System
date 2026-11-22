
import os
import sys
from datetime import date, timedelta

import importer
from app import create_app
from db import connect, init_schema, ROOT

SOURCES = [
    ("Website", "website"), ("WhatsApp Group - Mumbai", "whatsapp_group"), ("WhatsApp Group - Pune", "whatsapp_group"),
    ("Staff DM - Agent 01", "staff"), ("Staff DM - Agent 02", "staff"), ("Instagram", "social_post"),
    ("Facebook", "social_post"), ("Member Referral", "referral"), ("Meta Ads", "ads"), ("Unknown", "other"),
]


def main():
    db_path = create_app().config["DATABASE"]
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = connect(db_path)
    init_schema(conn)
    t = date.today()
    with conn:
        for name, kind in SOURCES:
            conn.execute("INSERT INTO sources (name, kind, slug) VALUES (?,?,?)",
                         (name, kind, importer.re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")))
        conn.executemany(
            """INSERT INTO surveys (title, description, topics, start_date, deadline, quota, age_min, age_max, age_strict,
               city, city_strict, gender, gender_strict, income_ranges, income_strict) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [("Mumbai Shopping Habits", "20-minute study on how people shop for fashion and food.", "Fashion;Food",
              t.isoformat(), (t + timedelta(days=10)).isoformat(), 60, 18, 35, 1, "Mumbai", 0, None, 1, None, 0),
             ("Tech & Auto Owners Pulse", "Opinions on gadgets and cars.", "Tech;Auto",
              t.isoformat(), (t + timedelta(days=12)).isoformat(), 40, 25, 45, 0, None, 0, None, 1,
              "6L-10L;10L-20L;Above 20L", 1),
             ("Women's Health & Beauty", "Everyday health and beauty products.", "Health;Beauty",
              t.isoformat(), (t + timedelta(days=7)).isoformat(), 30, 21, 50, 1, "Pune", 0, "Female", 1, None, 0)])
    text = open(os.path.join(ROOT, "data", "viewbox_respondents_sample.csv"), encoding="utf-8-sig").read()
    rows, report, counts = importer.parse_csv(text, today=t)
    importer.commit_rows(conn, rows)
    
    with conn:
        sid = conn.execute("SELECT id FROM sources WHERE name='Website'").fetchone()[0]
        conn.execute("""INSERT INTO members (member_code,name,phone,gender,dob,city,income_range,interests,source_id,
                        first_touch_source_id,referral_code,joined_on,profile_complete)
                        VALUES ('VB10000','Demo Member','9000000001','Female','1996-05-14','Mumbai','6L-10L',
                        'Fashion;Food;Tech',?,?,'DEMO01',?,1)""", (sid, sid, t.isoformat()))
    print(f"Imported {counts['imported']} of {counts['rows_read']} CSV rows "
          f"({counts['skipped']} skipped, {counts['fixed']} fixed). Demo member phone: 9000000001")
    conn.close()


if __name__ == "__main__":
    sys.exit(main())
