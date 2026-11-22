
import calendar
from datetime import date

COOL_OFF_MONTHS = 3


def parse_date(s):
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


def add_months(d, n):
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def fmt(d):
    return d.strftime("%d %b %Y")


def age_on(dob, today):
    if not dob:
        return None
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def split(s):
    return [x.strip() for x in (s or "").split(";") if x.strip()]


def evaluate(member, survey, today, completed_count=0):
    hard, strict, flex = [], [], []
    eligible_again = None

    last = parse_date(member["last_survey_completed_on"])
    if last:
        again = add_months(last, COOL_OFF_MONTHS)
        if today < again:
            eligible_again = again
            hard.append(f"you completed a survey on {fmt(last)}; you can join another from {fmt(again)}")

    deadline = parse_date(survey["deadline"])
    if deadline and today > deadline:
        hard.append(f"this survey closed on {fmt(deadline)}")
    if survey["quota"] and completed_count >= survey["quota"]:
        hard.append(f"the quota of {survey['quota']} is full")

    def bucket(is_strict, msg):
        (strict if is_strict else flex).append(msg)

    lo, hi = survey["age_min"], survey["age_max"]
    if lo is not None or hi is not None:
        age = age_on(parse_date(member["dob"]), today)
        need = f"{lo} to {hi}" if lo is not None and hi is not None else (f"{lo} or older" if lo is not None else f"up to {hi}")
        if age is None:
            bucket(survey["age_strict"], f"your date of birth is missing, this survey needs age {need}")
        elif (lo is not None and age < lo) or (hi is not None and age > hi):
            bucket(survey["age_strict"], f"age {age}, this survey needs {need}")

    if survey["city"]:
        city = member["city"]
        if (city or "").lower() != survey["city"].lower():
            bucket(survey["city_strict"], f"city is {city or 'missing'}, this survey is for {survey['city']}")

    if survey["gender"]:
        if (member["gender"] or "").lower() != survey["gender"].lower():
            bucket(survey["gender_strict"], f"gender is {member['gender'] or 'missing'}, this survey is for {survey['gender']}")

    incomes = split(survey["income_ranges"])
    if incomes and member["income_range"] not in incomes:
        bucket(survey["income_strict"], f"income range is {member['income_range'] or 'missing'}, this survey needs {' / '.join(incomes)}")

    if hard or strict:
        return {"status": "Rejected", "eligible_again": eligible_again,
                "reason": "Not eligible: " + "; ".join(hard + strict)}
    if flex:
        return {"status": "Waitlisted", "eligible_again": None,
                "reason": "Waitlisted: " + "; ".join(flex) + " (preferred, not required)"}
    return {"status": "Approved", "eligible_again": None, "reason": "Approved: all rules met"}
