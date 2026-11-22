
import csv
import io
import re
import secrets
from datetime import date, datetime

DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d-%m-%y", "%d/%m/%y"]
INCOMES = ["Below 3L", "3L-6L", "6L-10L", "10L-20L", "Above 20L"]
CITY_MAP = {"bombay": "Mumbai", "mumbai": "Mumbai", "navimumbai": "Navi Mumbai",
            "bangalore": "Bengaluru", "bengaluru": "Bengaluru"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def norm_phone(raw):
    """Return a 10-digit Indian mobile or None."""
    d = re.sub(r"\D", "", raw or "")
    if len(d) == 12 and d.startswith("91"):
        d = d[2:]
    elif len(d) == 11 and d.startswith("0"):
        d = d[1:]
    return d if len(d) == 10 and d[0] in "6789" else None


def norm_city(raw):
    s = (raw or "").strip()
    if not s:
        return None
    key = re.sub(r"\s+", "", s).lower()
    return CITY_MAP.get(key, s.title())


def norm_gender(raw):
    s = (raw or "").strip().lower()
    return {"m": "Male", "male": "Male", "f": "Female", "female": "Female"}.get(s)


def norm_date(raw):
    s = (raw or "").strip()
    for f in DATE_FORMATS:
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            continue
    return None


def norm_interests(raw):
    out = []
    for p in re.split(r"[;,]", raw or ""):
        p = p.strip().title()
        if p and p not in out:
            out.append(p)
    return out


def source_key(raw):
    """Map the many spellings in the file onto our canonical source names."""
    s = re.sub(r"\s+", " ", (raw or "").strip().lower())
    if not s:
        return None
    if s in ("insta", "ig", "instagram"):
        return "Instagram"
    if s in ("fb", "facebook"):
        return "Facebook"
    if s == "website":
        return "Website"
    if s == "referral":
        return "Member Referral"
    if "mumbai" in s and ("wa" in s or "whatsapp" in s):
        return "WhatsApp Group - Mumbai"
    if "pune" in s and ("wa" in s or "whatsapp" in s):
        return "WhatsApp Group - Pune"
    if s.startswith("staff dm"):
        return re.sub(r"\bagent (\d+)", lambda m: f"Agent {int(m.group(1)):02d}", raw.strip().title().replace("Dm", "DM"), flags=re.I)
    return raw.strip()


def new_referral_code(taken):
    while True:
        c = secrets.token_hex(3).upper()
        if c not in taken:
            taken.add(c)
            return c


def parse_csv(text, existing_phones=(), existing_codes=(), today=None):
    """Return (clean_rows, report, counts). Pure function: touches no database."""
    today = today or date.today()
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    report, rows = [], []
    seen_phone, seen_code = set(existing_phones), set(existing_codes)
    max_num = max([int(c[2:]) for c in existing_codes if re.fullmatch(r"VB\d+", c)] + [10000])
    total = 0
    for raw in reader:  # first pass: find the highest existing ID so new IDs never clash
        code = (raw.get("member_id") or "").strip().upper()
        total += 1
        if re.fullmatch(r"VB\d+", code):
            max_num = max(max_num, int(code[2:]))

    next_num = max_num + 1
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    for line, raw in enumerate(reader, start=2):
        raw = {k: (v or "").strip() for k, v in raw.items() if k}
        label = raw.get("member_id") or f"row {line}"
        fixes = []

        def skip(reason):
            report.append({"line": line, "member": label, "action": "Skipped", "detail": reason})

        if not any(raw.values()):
            skip("empty row")
            continue
        phone = norm_phone(raw.get("phone"))
        if not raw.get("phone"):
            skip("phone number is missing")
            continue
        if not phone:
            skip(f"phone '{raw['phone']}' is not a valid 10-digit mobile number")
            continue
        if phone in seen_phone:
            skip(f"phone {phone} already exists (duplicate of an earlier row or an existing member)")
            continue

        code = raw.get("member_id", "").upper()
        if not re.fullmatch(r"VB\d+", code):
            code = f"VB{next_num}"; next_num += 1
            fixes.append("member ID was missing, new ID assigned")
        elif code in seen_code:
            old, code = code, f"VB{next_num}"; next_num += 1
            fixes.append(f"member ID {old} was already used by another person, new ID {code} assigned")
        seen_code.add(code)
        seen_phone.add(phone)

        if phone != re.sub(r"\D", "", raw["phone"]):
            fixes.append(f"phone cleaned to {phone}")

        name = raw.get("name", "")
        if not name:
            name = "Unnamed member"; fixes.append("name was missing")
        elif name.isupper() or name.islower():
            name = name.title(); fixes.append("name capitalisation fixed")

        email = raw.get("email", "")
        if email and not EMAIL_RE.match(email):
            fixes.append(f"invalid email '{email}' removed"); email = ""

        g_raw = raw.get("gender", "")
        gender = norm_gender(g_raw)
        if g_raw and gender != g_raw:
            fixes.append(f"gender '{g_raw}' standardised to {gender}") if gender else fixes.append(f"gender '{g_raw}' not recognised, left blank")

        city = norm_city(raw.get("city"))
        if raw.get("city") and city != raw["city"]:
            fixes.append(f"city '{raw['city']}' standardised to {city}")

        inc = raw.get("income_range", "")
        if inc and inc not in INCOMES:
            m = re.match(r"(\d+)\s*lakh", inc.lower())
            mapped = None
            if m:
                v = int(m.group(1))
                mapped = "Below 3L" if v < 3 else "3L-6L" if v < 6 else "6L-10L" if v < 10 else "10L-20L" if v <= 20 else "Above 20L"
            fixes.append(f"income '{inc}' mapped to {mapped}" if mapped else f"income '{inc}' not recognised, left blank")
            inc = mapped or ""

        dob = norm_date(raw.get("date_of_birth"))
        if raw.get("date_of_birth") and not dob:
            fixes.append(f"date of birth '{raw['date_of_birth']}' is not a real date, left blank")
        elif dob and not (10 <= today.year - dob.year <= 100):
            fixes.append(f"date of birth {dob} looks wrong, left blank"); dob = None

        joined = norm_date(raw.get("joined_on"))
        if raw.get("joined_on") and not joined:
            fixes.append(f"joined date '{raw['joined_on']}' invalid, left blank")
        if joined and joined > today:
            fixes.append(f"joined date {joined} is in the future, left blank"); joined = None
        last = norm_date(raw.get("last_survey_completed_on"))
        if raw.get("last_survey_completed_on") and not last:
            fixes.append(f"last survey date '{raw['last_survey_completed_on']}' invalid, left blank")
        if last and last > today:
            fixes.append(f"last survey date {last} is in the future, left blank"); last = None

        src = source_key(raw.get("source"))
        if raw.get("source") and src != raw["source"]:
            fixes.append(f"source '{raw['source']}' standardised to {src}")
        if not src:
            fixes.append("source was blank, set to Unknown")

        interests = norm_interests(raw.get("interests"))
        if "," in raw.get("interests", "") or ";;" in raw.get("interests", ""):
            fixes.append("interests list tidied")

        if fixes:
            report.append({"line": line, "member": code, "action": "Fixed", "detail": "; ".join(fixes)})
        rows.append({"member_code": code, "name": name, "phone": phone, "email": email or None,
                     "gender": gender, "dob": dob.isoformat() if dob else None, "city": city,
                     "income_range": inc or None, "interests": ";".join(interests),
                     "source": src or "Unknown", "referred_by_code": raw.get("referred_by", "").upper() or None,
                     "joined_on": joined.isoformat() if joined else None,
                     "last_survey_completed_on": last.isoformat() if last else None, "line": line})

    
    known = {r["member_code"] for r in rows} | set(existing_codes)
    for r in rows:
        ref = r["referred_by_code"]
        if ref and (ref not in known or ref == r["member_code"]):
            why = "refers to themselves" if ref == r["member_code"] else "does not exist"
            report.append({"line": r["line"], "member": r["member_code"], "action": "Fixed",
                           "detail": f"referrer {ref} {why}, referrer removed"})
            r["referred_by_code"] = None
    counts = {"rows_read": total, "imported": len(rows),
              "skipped": sum(1 for x in report if x["action"] == "Skipped"),
              "fixed": sum(1 for x in report if x["action"] == "Fixed")}
    return rows, report, counts


def commit_rows(conn, rows):
    """Insert cleaned rows (one transaction). Unknown sources are created on the fly."""
    taken = {r[0] for r in conn.execute("SELECT referral_code FROM members")}
    src = {r["name"].lower(): r["id"] for r in conn.execute("SELECT id, name FROM sources")}

    def source_id(name):
        if name.lower() not in src:
            slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            cur = conn.execute("INSERT INTO sources (name, kind, slug) VALUES (?,?,?)", (name, "other", slug))
            src[name.lower()] = cur.lastrowid
        return src[name.lower()]

    with conn:
        for r in rows:
            sid = source_id(r["source"])
            stage = "completed" if r["last_survey_completed_on"] else "lead"
            complete = int(all(r[k] for k in ("name", "dob", "gender", "city", "income_range", "interests")))
            conn.execute(
                """INSERT INTO members (member_code,name,phone,email,gender,dob,city,income_range,interests,
                   source_id,first_touch_source_id,referral_code,joined_on,last_survey_completed_on,stage,profile_complete)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (r["member_code"], r["name"], r["phone"], r["email"], r["gender"], r["dob"], r["city"],
                 r["income_range"], r["interests"], sid, sid, new_referral_code(taken), r["joined_on"],
                 r["last_survey_completed_on"], stage, complete))
        for r in rows:
            if r["referred_by_code"]:
                conn.execute("UPDATE members SET referred_by_id=(SELECT id FROM members WHERE member_code=?) WHERE member_code=?",
                             (r["referred_by_code"], r["member_code"]))
    return len(rows)
