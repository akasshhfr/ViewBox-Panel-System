import csv
import hmac
import hashlib
import io
import json
import os
import re
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from functools import wraps

from flask import (Flask, Response, abort, flash, g, jsonify, redirect, render_template,
                   request, session, url_for)
from openpyxl import Workbook

import importer
from db import close_db, connect, get_db, init_schema, ROOT
from eligibility import age_on, evaluate, parse_date, split, fmt

INCOMES = importer.INCOMES
INTERESTS = ["Auto", "Beauty", "Fashion", "Finance", "Food", "Health", "Home", "Kids", "Tech", "Travel"]
GENDERS = ["Male", "Female"]
TOUCH_DAYS = 30
OTP_MINUTES = 10


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
        DATABASE=os.environ.get("VIEWBOX_DB", os.path.join(ROOT, "instance", "viewbox.db")),
        ADMIN_USER=os.environ.get("ADMIN_USER", "admin"),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD", "admin123"),
        META_APP_SECRET=os.environ.get("META_APP_SECRET", ""),  # if set, X-Hub-Signature-256 is checked
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    )
    if config:
        app.config.update(config)
    app.teardown_appcontext(close_db)
    conn = connect(app.config["DATABASE"])
    init_schema(conn)
    conn.close()

    # ---------- helpers ----------
    def today():
        return date.today()

    def utcnow():
        return datetime.now(timezone.utc).replace(tzinfo=None)

    def next_code(db):
        row = db.execute("SELECT MAX(CAST(SUBSTR(member_code,3) AS INTEGER)) FROM members").fetchone()
        return f"VB{(row[0] or 10000) + 1}"

    def new_referral_code(db):
        while True:
            c = secrets.token_hex(3).upper()
            if not db.execute("SELECT 1 FROM members WHERE referral_code=?", (c,)).fetchone():
                return c

    def mask(phone):
        return f"{phone[:2]}XXXXXX{phone[-2:]}" if phone and len(phone) == 10 else "hidden"

    def source_by_name(db, name):
        return db.execute("SELECT * FROM sources WHERE lower(name)=lower(?)", (name,)).fetchone()

    def slugify(s):
        return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")

    def current_member():
        mid = session.get("member_id")
        return get_db().execute("SELECT * FROM members WHERE id=?", (mid,)).fetchone() if mid else None

    def member_required(f):
        @wraps(f)
        def wrap(*a, **k):
            m = current_member()
            if not m:
                return redirect(url_for("login"))
            g.member = m
            return f(*a, **k)
        return wrap

    def admin_required(f):
        @wraps(f)
        def wrap(*a, **k):
            if not session.get("is_admin"):
                return redirect(url_for("admin_login", next=request.path))
            return f(*a, **k)
        return wrap

    def record_touch(source_id, referrer_id=None):
        db = get_db()
        t = session.get("touch") or {}
        t.setdefault("first", source_id)           # first touch is never overwritten
        t.update(last=source_id, referrer_id=referrer_id, at=utcnow().isoformat())
        session["touch"] = t
        session.setdefault("visitor", uuid.uuid4().hex)
        with db:
            db.execute("INSERT INTO link_touches (source_id, visitor_id, referrer_member_id) VALUES (?,?,?)",
                       (source_id, session["visitor"], referrer_id))

    def valid_touch():
        t = session.get("touch")
        if not t:
            return None
        if utcnow() - datetime.fromisoformat(t["at"]) > timedelta(days=TOUCH_DAYS):
            return None
        return t

    def resolve_referrer(db, text):
        text = (text or "").strip().upper()
        if not text:
            return None
        ph = importer.norm_phone(text)
        return db.execute("SELECT * FROM members WHERE member_code=? OR referral_code=? OR phone=?",
                          (text, text, ph or "x")).fetchone()

    def stage_label(m):
        return {"lead": "Lead", "fit": "Fit", "completed": "Completed", "failed": "Did not qualify"}[m["stage"]]

    def completions_map(db):
        return {r["survey_id"]: r["n"] for r in db.execute(
            "SELECT survey_id, COUNT(*) n FROM survey_completions GROUP BY survey_id")}

    app.jinja_env.globals.update(mask=mask, stage_label=stage_label, fmt=fmt, parse_date=parse_date,
                                 split=split, INTERESTS=INTERESTS, INCOMES=INCOMES, GENDERS=GENDERS)

    @app.context_processor
    def inject():
        return {"me": current_member() if session.get("member_id") else None,
                "is_admin": session.get("is_admin"), "today_iso": today().isoformat()}

    # ---------- member portal ----------
    @app.route("/")
    def index():
        return redirect(url_for("home" if session.get("member_id") else "login"))

    @app.route("/s/<slug>")
    def source_link(slug):
        src = get_db().execute("SELECT * FROM sources WHERE slug=? AND active=1", (slug,)).fetchone()
        if not src:
            abort(404)
        record_touch(src["id"])
        return redirect(url_for("login"))

    @app.route("/r/<code>")
    def referral_link(code):
        db = get_db()
        ref = db.execute("SELECT * FROM members WHERE referral_code=?", (code.upper(),)).fetchone()
        src = source_by_name(db, "Member Referral")
        if not ref or not src:
            abort(404)
        record_touch(src["id"], ref["id"])
        return redirect(url_for("login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        db = get_db()
        touch = valid_touch()
        sources = db.execute("SELECT * FROM sources WHERE active=1 AND kind!='referral' ORDER BY name").fetchall()
        referrer = db.execute("SELECT name FROM members WHERE id=?", (touch["referrer_id"],)).fetchone() if touch and touch.get("referrer_id") else None
        if request.method == "POST":
            phone = importer.norm_phone(request.form.get("phone"))
            if not phone:
                flash("Please enter a valid 10-digit mobile number.", "error")
                return render_template("login.html", touch=touch, sources=sources, referrer=referrer), 400
            exists = db.execute("SELECT 1 FROM members WHERE phone=?", (phone,)).fetchone()
            how = request.form.get("how_heard")
            if not exists and not touch and not how:
                flash("Please tell us how you heard about us.", "error")
                return render_template("login.html", touch=touch, sources=sources, referrer=referrer, phone=phone), 400
            code = f"{secrets.randbelow(900000) + 100000}"
            with db:
                db.execute("REPLACE INTO otps (phone, code, expires_at) VALUES (?,?,?)",
                           (phone, code, (utcnow() + timedelta(minutes=OTP_MINUTES)).isoformat()))
            session["pending"] = {"phone": phone, "how": how, "ref": request.form.get("referrer", "").strip()}
            return redirect(url_for("verify"))
        return render_template("login.html", touch=touch, sources=sources, referrer=referrer)

    @app.route("/verify", methods=["GET", "POST"])
    def verify():
        db = get_db()
        pend = session.get("pending")
        if not pend:
            return redirect(url_for("login"))
        row = db.execute("SELECT * FROM otps WHERE phone=?", (pend["phone"],)).fetchone()
        if request.method == "POST":
            ok = row and request.form.get("code", "").strip() == row["code"] \
                and datetime.fromisoformat(row["expires_at"]) > utcnow()
            if not ok:
                flash("That code is wrong or has expired. Check the code and try again.", "error")
                return render_template("verify.html", otp=row["code"] if row else None, phone=mask(pend["phone"])), 400
            with db:
                db.execute("DELETE FROM otps WHERE phone=?", (pend["phone"],))
            m = db.execute("SELECT * FROM members WHERE phone=?", (pend["phone"],)).fetchone()
            if not m:
                m = create_member(db, pend)
            session.pop("pending", None)
            session["member_id"] = m["id"]
            return redirect(url_for("home" if m["profile_complete"] else "profile"))
        return render_template("verify.html", otp=row["code"] if row else None, phone=mask(pend["phone"]))

    def create_member(db, pend):
        """Source = last tagged link (or the 'how did you hear' answer). Referrer = link owner, else typed code."""
        touch = valid_touch()
        flag = None
        src_id = first_id = ref_id = None
        if touch:
            # The browser can remember ids from an older database, so check they still exist.
            if db.execute("SELECT 1 FROM sources WHERE id=?", (touch["last"],)).fetchone():
                src_id = touch["last"]
                still_there = db.execute("SELECT 1 FROM sources WHERE id=?", (touch["first"],)).fetchone()
                first_id = touch["first"] if still_there else src_id
                ref_id = touch.get("referrer_id")
        if src_id is None:
            row = db.execute("SELECT id FROM sources WHERE id=?", (pend.get("how") or 0,)).fetchone()
            unknown = source_by_name(db, "Unknown")
            src_id = row["id"] if row else (unknown["id"] if unknown else None)
            first_id, ref_id = src_id, None
        typed = resolve_referrer(db, pend.get("ref"))
        if pend.get("ref") and not typed:
            flag = f"typed referrer '{pend['ref']}' not found"
        if not ref_id and typed:
            ref_id = typed["id"]
        if ref_id:
            r = db.execute("SELECT phone FROM members WHERE id=?", (ref_id,)).fetchone()
            if not r:
                ref_id = None
            elif r["phone"] == pend["phone"]:
                ref_id, flag = None, "self-referral attempt"
        with db:
            cur = db.execute(
                """INSERT INTO members (member_code, phone, source_id, first_touch_source_id, referred_by_id,
                   referral_code, joined_on, flag) VALUES (?,?,?,?,?,?,?,?)""",
                (next_code(db), pend["phone"], src_id, first_id, ref_id, new_referral_code(db),
                 today().isoformat(), flag))
        return db.execute("SELECT * FROM members WHERE id=?", (cur.lastrowid,)).fetchone()

    @app.route("/profile", methods=["GET", "POST"])
    @member_required
    def profile():
        db, m = get_db(), g.member
        if request.method == "POST":
            f = request.form
            name = f.get("name", "").strip()
            dob = parse_date(f.get("dob"))
            gender, income = f.get("gender"), f.get("income_range")
            city = importer.norm_city(f.get("city"))
            interests = [i for i in f.getlist("interests") if i in INTERESTS]
            errs = []
            if len(name) < 2: errs.append("Enter your name.")
            if not dob or not (10 <= age_on(dob, today()) <= 100): errs.append("Enter a valid date of birth.")
            if gender not in GENDERS: errs.append("Select your gender.")
            if not city: errs.append("Enter your city.")
            if income not in INCOMES: errs.append("Select your income range.")
            if not interests: errs.append("Pick at least one interest.")
            if errs:
                for e in errs: flash(e, "error")
                return render_template("profile.html", m=f, selected=interests), 400
            with db:
                db.execute("""UPDATE members SET name=?, dob=?, gender=?, city=?, income_range=?, interests=?,
                              email=COALESCE(NULLIF(?,''), email), profile_complete=1 WHERE id=?""",
                           (name, dob.isoformat(), gender, city, income, ";".join(interests), f.get("email", "").strip(), m["id"]))
            return redirect(url_for("home"))
        return render_template("profile.html", m=m, selected=split(m["interests"]))

    @app.route("/home")
    @member_required
    def home():
        db, m = get_db(), g.member
        if not m["profile_complete"]:
            return redirect(url_for("profile"))
        comp = completions_map(db)
        mine = set(split(m["interests"]))
        cards = []
        for s in db.execute("SELECT * FROM surveys WHERE deadline >= ? AND start_date <= ? ORDER BY deadline",
                            (today().isoformat(), today().isoformat())):
            res = evaluate(m, s, today(), comp.get(s["id"], 0))
            cards.append({"s": s, "res": res, "match": sorted(mine & set(split(s["topics"])))})
        order = {"Approved": 0, "Waitlisted": 1, "Rejected": 2}
        cards.sort(key=lambda c: (order[c["res"]["status"]], not c["match"]))
        last = parse_date(m["last_survey_completed_on"])
        from eligibility import add_months
        again = add_months(last, 3) if last and add_months(last, 3) > today() else None
        return render_template("home.html", cards=cards, again=again)

    @app.route("/referrals")
    @member_required
    def referrals():
        db, m = get_db(), g.member
        rows = db.execute("SELECT * FROM members WHERE referred_by_id=? ORDER BY id DESC", (m["id"],)).fetchall()
        link = request.url_root.rstrip("/") + url_for("referral_link", code=m["referral_code"])
        return render_template("referrals.html", rows=rows, link=link)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # ---------- admin ----------
    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        if request.method == "POST":
            if (request.form.get("username") == app.config["ADMIN_USER"] and
                    hmac.compare_digest(request.form.get("password", ""), app.config["ADMIN_PASSWORD"])):
                session["is_admin"] = True
                nxt = request.args.get("next", "")
                return redirect(nxt if nxt.startswith("/admin") else url_for("admin_dashboard"))
            flash("Wrong username or password.", "error")
            return render_template("admin_login.html"), 401
        return render_template("admin_login.html")

    @app.route("/admin/logout")
    def admin_logout():
        session.pop("is_admin", None)
        return redirect(url_for("admin_login"))

    @app.route("/admin")
    @admin_required
    def admin_dashboard():
        db = get_db()
        rows = db.execute("""
            SELECT s.id, s.name, s.kind, s.slug,
                   COUNT(m.id) AS signups,
                   COALESCE(SUM(m.stage IN ('fit','completed')),0) AS fit,
                   COALESCE(SUM(m.stage='completed'),0) AS completed,
                   COALESCE(SUM(m.stage='failed'),0) AS failed
            FROM sources s LEFT JOIN members m ON m.source_id=s.id
            GROUP BY s.id ORDER BY signups DESC, s.name""").fetchall()
        totals = db.execute("SELECT COUNT(*) n, SUM(stage='completed') c FROM members").fetchone()
        return render_template("admin_dashboard.html", rows=rows, totals=totals)

    @app.route("/admin/sources", methods=["GET", "POST"])
    @admin_required
    def admin_sources():
        db = get_db()
        if request.method == "POST":
            name, kind = request.form.get("name", "").strip(), request.form.get("kind", "other")
            slug = slugify(name)
            if not name or not slug:
                flash("Give the source a name.", "error")
            elif db.execute("SELECT 1 FROM sources WHERE slug=? OR lower(name)=lower(?)", (slug, name)).fetchone():
                flash(f"A source called '{name}' already exists.", "error")
            else:
                with db:
                    db.execute("INSERT INTO sources (name, kind, slug) VALUES (?,?,?)", (name, kind, slug))
                flash(f"Source '{name}' added. Its tracked link is ready below.", "ok")
            return redirect(url_for("admin_sources"))
        rows = db.execute("SELECT * FROM sources ORDER BY kind, name").fetchall()
        return render_template("admin_sources.html", rows=rows, root=request.url_root.rstrip("/"))

    def member_filters(args):
        sql, p = " FROM members m LEFT JOIN sources s ON s.id=m.source_id WHERE 1=1", []
        q = args.get("q", "").strip()
        if q:
            sql += " AND (m.name LIKE ? OR m.member_code LIKE ? OR m.city LIKE ?)"
            p += [f"%{q}%"] * 3
        if args.get("source"):
            sql += " AND m.source_id=?"; p.append(args["source"])
        if args.get("city"):
            sql += " AND m.city=?"; p.append(args["city"])
        st = args.get("status")
        if st == "cooling_off":
            sql += " AND m.last_survey_completed_on > ?"
            from eligibility import add_months
            p.append(add_months(today(), -3).isoformat())
        elif st in ("lead", "fit", "completed", "failed"):
            sql += " AND m.stage=?"; p.append(st)
        elif st == "flagged":
            sql += " AND m.flag IS NOT NULL"
        return sql, p

    @app.route("/admin/members")
    @admin_required
    def admin_members():
        db = get_db()
        where, p = member_filters(request.args)
        page = max(int(request.args.get("page", 1) or 1), 1)
        total = db.execute("SELECT COUNT(*)" + where, p).fetchone()[0]
        rows = db.execute("SELECT m.*, s.name AS source_name" + where + " ORDER BY m.member_code LIMIT 50 OFFSET ?",
                          p + [(page - 1) * 50]).fetchall()
        ctx = dict(rows=rows, total=total, page=page, pages=max((total + 49) // 50, 1))
        if request.args.get("partial"):
            return render_template("_members_rows.html", **ctx)
        cities = [r[0] for r in db.execute("SELECT DISTINCT city FROM members WHERE city IS NOT NULL ORDER BY city")]
        sources = db.execute("SELECT id, name FROM sources ORDER BY name").fetchall()
        return render_template("admin_members.html", cities=cities, sources=sources, **ctx)

    @app.route("/admin/members/export.<fmt_>")
    @admin_required
    def admin_export(fmt_):
        if fmt_ not in ("csv", "xlsx"):
            abort(404)
        where, p = member_filters(request.args)
        rows = get_db().execute(
            """SELECT m.member_code, m.name, m.phone, m.email, m.gender, m.dob, m.city, m.income_range, m.interests,
               s.name AS source, ft.name AS first_touch, r.member_code AS referred_by, m.stage, m.stage_reason,
               m.joined_on, m.last_survey_completed_on, m.flag
               FROM members m LEFT JOIN sources s ON s.id=m.source_id LEFT JOIN sources ft ON ft.id=m.first_touch_source_id
               LEFT JOIN members r ON r.id=m.referred_by_id WHERE m.id IN (SELECT m.id""" + where + ") ORDER BY m.member_code", p).fetchall()
        head = rows[0].keys() if rows else ["member_code", "name", "phone"]
        if fmt_ == "csv":
            buf = io.StringIO(); w = csv.writer(buf); w.writerow(head)
            w.writerows([list(r) for r in rows])
            return Response(buf.getvalue(), mimetype="text/csv",
                            headers={"Content-Disposition": "attachment; filename=viewbox_members.csv"})
        wb = Workbook(); ws = wb.active; ws.title = "Members"; ws.append(list(head))
        for r in rows: ws.append(list(r))
        out = io.BytesIO(); wb.save(out)
        return Response(out.getvalue(), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": "attachment; filename=viewbox_members.xlsx"})

    @app.route("/admin/members/<int:mid>")
    @admin_required
    def admin_member(mid):
        db = get_db()
        m = db.execute("""SELECT m.*, s.name source_name, ft.name first_touch_name, r.name referrer_name, r.member_code referrer_code
                          FROM members m LEFT JOIN sources s ON s.id=m.source_id LEFT JOIN sources ft ON ft.id=m.first_touch_source_id
                          LEFT JOIN members r ON r.id=m.referred_by_id WHERE m.id=?""", (mid,)).fetchone()
        if not m: abort(404)
        comp = completions_map(db)
        surveys = db.execute("SELECT * FROM surveys ORDER BY deadline DESC").fetchall()
        results = [(s, evaluate(m, s, today(), comp.get(s["id"], 0))) for s in surveys]
        referred = db.execute("SELECT * FROM members WHERE referred_by_id=?", (mid,)).fetchall()
        return render_template("admin_member.html", m=m, results=results, surveys=surveys, referred=referred)

    @app.route("/admin/members/<int:mid>/stage", methods=["POST"])
    @admin_required
    def admin_stage(mid):
        db = get_db()
        stage, reason = request.form.get("stage"), request.form.get("reason", "").strip()
        if stage not in ("lead", "fit", "completed", "failed"): abort(400)
        if stage == "failed" and not reason:
            flash("Please record why this person did not qualify.", "error")
            return redirect(url_for("admin_member", mid=mid))
        with db:
            if stage == "completed":
                sid = request.form.get("survey_id")
                if not sid:
                    flash("Pick the survey that was completed.", "error")
                    return redirect(url_for("admin_member", mid=mid))
                db.execute("INSERT OR IGNORE INTO survey_completions (survey_id, member_id, completed_on) VALUES (?,?,?)",
                           (sid, mid, today().isoformat()))
                db.execute("UPDATE members SET last_survey_completed_on=? WHERE id=?", (today().isoformat(), mid))
            db.execute("UPDATE members SET stage=?, stage_reason=? WHERE id=?",
                       (stage, reason if stage == "failed" else None, mid))
        flash("Stage updated.", "ok")
        return redirect(url_for("admin_member", mid=mid))

    @app.route("/admin/surveys", methods=["GET", "POST"])
    @admin_required
    def admin_surveys():
        db = get_db()
        if request.method == "POST":
            f = request.form
            def num(k):
                try: return int(f[k]) if f.get(k) else None
                except ValueError: return "bad"
            start, end = parse_date(f.get("start_date")), parse_date(f.get("deadline"))
            amin, amax, quota = num("age_min"), num("age_max"), num("quota")
            errs = []
            if not f.get("title", "").strip(): errs.append("Title is required.")
            if not start or not end: errs.append("Start date and deadline are required.")
            elif end < start: errs.append("Deadline must be after the start date.")
            elif (end - start).days > 15: errs.append("A project must finish within 15 days of its start.")
            if "bad" in (amin, amax, quota): errs.append("Age and quota must be whole numbers.")
            elif amin is not None and amax is not None and amin > amax: errs.append("Minimum age is higher than maximum age.")
            if errs:
                for e in errs: flash(e, "error")
                return render_template("admin_surveys.html", rows=surveys_list(db), form=f), 400
            with db:
                db.execute("""INSERT INTO surveys (title, description, topics, start_date, deadline, quota, age_min, age_max, age_strict,
                              city, city_strict, gender, gender_strict, income_ranges, income_strict) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                           (f["title"].strip(), f.get("description", "").strip(), ";".join(f.getlist("topics")), start.isoformat(),
                            end.isoformat(), quota, amin, amax, int(f.get("age_strict") == "1"),
                            importer.norm_city(f.get("city")), int(f.get("city_strict") == "1"),
                            f.get("gender") or None, int(f.get("gender_strict") == "1"),
                            ";".join(f.getlist("income_ranges")) or None, int(f.get("income_strict") == "1")))
            flash("Survey created.", "ok")
            return redirect(url_for("admin_surveys"))
        return render_template("admin_surveys.html", rows=surveys_list(db), form={"start_date": today().isoformat()})

    def surveys_list(db):
        return db.execute("""SELECT s.*, (SELECT COUNT(*) FROM survey_completions c WHERE c.survey_id=s.id) done
                             FROM surveys s ORDER BY deadline DESC""").fetchall()

    @app.route("/admin/surveys/<int:sid>")
    @admin_required
    def admin_survey(sid):
        db = get_db()
        s = db.execute("SELECT * FROM surveys WHERE id=?", (sid,)).fetchone()
        if not s: abort(404)
        done = db.execute("SELECT COUNT(*) FROM survey_completions WHERE survey_id=?", (sid,)).fetchone()[0]
        out, tally = [], {"Approved": 0, "Waitlisted": 0, "Rejected": 0}
        for m in db.execute("SELECT * FROM members WHERE profile_complete=1 ORDER BY member_code"):
            r = evaluate(m, s, today(), done)
            tally[r["status"]] += 1
            if len(out) < 100: out.append((m, r))
        return render_template("admin_survey.html", s=s, rows=out, tally=tally, done=done)

    # ---------- CSV import (preview -> confirm) ----------
    UPLOADS = os.path.join(os.path.dirname(app.config["DATABASE"]), "uploads")

    @app.route("/admin/import", methods=["GET", "POST"])
    @admin_required
    def admin_import():
        db = get_db()
        if request.method == "GET":
            return render_template("admin_import.html")
        os.makedirs(UPLOADS, exist_ok=True)
        token = request.form.get("token")
        if token:  # step 2: confirm
            path = os.path.join(UPLOADS, os.path.basename(token) + ".csv")
            if not os.path.exists(path):
                flash("That preview expired. Please upload the file again.", "error")
                return redirect(url_for("admin_import"))
            rows, report, counts = parse_for(db, open(path, encoding="utf-8").read())
            n = importer.commit_rows(db, rows)
            os.remove(path)
            flash(f"Imported {n} members. {counts['skipped']} rows were skipped, {counts['fixed']} were fixed.", "ok")
            return redirect(url_for("admin_members"))
        f = request.files.get("file")
        if not f or not f.filename.lower().endswith(".csv"):
            flash("Choose a .csv file.", "error")
            return render_template("admin_import.html"), 400
        try:
            text = f.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                f.seek(0); text = f.read().decode("latin-1")
            except Exception:
                flash("Could not read that file.", "error")
                return render_template("admin_import.html"), 400
        if "phone" not in (text.splitlines()[0].lower() if text.strip() else ""):
            flash("This does not look like the members file: the header row needs a 'phone' column.", "error")
            return render_template("admin_import.html"), 400
        token = uuid.uuid4().hex
        with open(os.path.join(UPLOADS, token + ".csv"), "w", encoding="utf-8") as out:
            out.write(text)
        rows, report, counts = parse_for(db, text)
        return render_template("admin_import.html", rows=rows[:15], report=report, counts=counts, token=token)

    def parse_for(db, text):
        phones = [r[0] for r in db.execute("SELECT phone FROM members")]
        codes = [r[0] for r in db.execute("SELECT member_code FROM members")]
        return importer.parse_csv(text, phones, codes, today())

    # ---------- Meta (Facebook / Instagram) lead ads mock endpoint ----------
    def lead_fields(payload):
        out = {}
        for item in payload.get("field_data") or []:
            vals = item.get("values") or []
            if item.get("name") and vals:
                out[item["name"].lower()] = str(vals[0]).strip()
        return out

    @app.route("/api/meta/leads", methods=["POST"])
    def meta_leads():
        raw = request.get_data()
        secret = app.config["META_APP_SECRET"]
        if secret:
            sig = request.headers.get("X-Hub-Signature-256", "")
            good = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig, good):
                return jsonify(status="error", errors=["invalid signature"]), 401
        payload = request.get_json(silent=True)
        db = get_db()
        if not isinstance(payload, dict):
            return jsonify(status="rejected", errors=["body must be a JSON object"]), 400
        lead_id = str(payload.get("id") or payload.get("leadgen_id") or "").strip()
        fields = lead_fields(payload)
        phone = importer.norm_phone(fields.get("phone_number") or fields.get("phone"))
        name = fields.get("full_name") or fields.get("name") or ""
        email = fields.get("email", "")
        errors = []
        if not lead_id: errors.append("lead id is missing")
        if not payload.get("campaign_id"): errors.append("campaign_id is missing")
        if not name: errors.append("full_name is missing")
        if not phone: errors.append("phone_number is missing or not a valid Indian mobile number")
        if email and not importer.EMAIL_RE.match(email): errors.append("email is not valid")

        def log(status, member_id=None, errs=None):
            with db:
                db.execute("INSERT OR IGNORE INTO meta_leads (leadgen_id, payload, status, errors, member_id) VALUES (?,?,?,?,?)",
                           (lead_id or None, json.dumps(payload), status, "; ".join(errs or []) or None, member_id))

        if errors:
            log("rejected", errs=errors)
            return jsonify(status="rejected", errors=errors), 422
        dup = db.execute("SELECT * FROM members WHERE meta_lead_id=?", (lead_id,)).fetchone()
        if dup:  # same lead sent twice -> idempotent, no new member
            return jsonify(status="duplicate", reason="lead already received", member_id=dup["member_code"]), 200
        same_phone = db.execute("SELECT * FROM members WHERE phone=?", (phone,)).fetchone()
        if same_phone:
            log("duplicate", same_phone["id"], ["phone already belongs to an existing member"])
            return jsonify(status="duplicate", reason="phone already belongs to an existing member",
                           member_id=same_phone["member_code"]), 200
        src = source_by_name(db, "Meta Ads")
        with db:
            cur = db.execute(
                """INSERT INTO members (member_code, name, phone, email, city, source_id, first_touch_source_id, referral_code,
                   joined_on, meta_lead_id, meta_campaign_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (next_code(db), name.title() if name.islower() or name.isupper() else name, phone, email or None,
                 importer.norm_city(fields.get("city")), src["id"], src["id"], new_referral_code(db),
                 today().isoformat(), lead_id, str(payload["campaign_id"])))
        member = db.execute("SELECT member_code FROM members WHERE id=?", (cur.lastrowid,)).fetchone()
        log("created", cur.lastrowid)
        return jsonify(status="created", member_id=member["member_code"], source="Meta Ads",
                       campaign_id=str(payload["campaign_id"])), 201

    @app.route("/admin/meta-leads")
    @admin_required
    def admin_meta_leads():
        rows = get_db().execute("SELECT l.*, m.member_code FROM meta_leads l LEFT JOIN members m ON m.id=l.member_id ORDER BY l.id DESC LIMIT 100").fetchall()
        return render_template("admin_meta_leads.html", rows=rows)

    @app.errorhandler(404)
    def nf(_e):
        return render_template("error.html", code=404, msg="We could not find that page."), 404

    @app.errorhandler(413)
    def too_big(_e):
        return render_template("error.html", code=413, msg="That file is too large (limit 2 MB)."), 413

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
