# ViewBox Panel System

A panel management web application built as part of the Concave Insights assessment. It helps manage survey respondents, track referrals and registration sources, and check survey eligibility.

## Features

- Phone login with mock OTP verification and member profiles.
- Source tracking and personal referral links.
- Survey eligibility checks with reasons and a 3-month cool-off period.
- Admin dashboard with member search, filters and survey management.
- CSV import with validation, and CSV/Excel export.
- Mock Meta Lead Ads integration.

## Tech Stack

Python, Flask, SQLite, HTML, CSS and JavaScript.

## Setup

Run the following commands from the project folder:

```bash
pip install -r requirements.txt
python seed.py
python app.py
```

Open http://127.0.0.1:5000 in your browser.

Note: Running `seed.py` resets the database and loads sample data.

## Demo Login

- **Member:** `9000000001` (OTP is displayed on screen)
- **Admin:** `/admin/login` — username: `admin`, password: `admin123`

## Testing

```bash
python -m unittest discover -s tests
```

## Notes

OTP and Meta lead integration are mocked. Advanced fraud detection and payout integration are not implemented.

Database design and user flow are available in the `design/` folder.

### @akasshhfr
