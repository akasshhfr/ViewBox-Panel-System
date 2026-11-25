PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sources (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL DEFAULT 'other',   -- whatsapp_group | staff | social_post | website | referral | ads | other
  slug TEXT NOT NULL UNIQUE,            -- used in the tracked link /s/<slug>
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS members (
  id INTEGER PRIMARY KEY,
  member_code TEXT NOT NULL UNIQUE,     -- VB10001 style, shown to humans
  name TEXT,
  phone TEXT NOT NULL UNIQUE,           -- normalised 10-digit Indian mobile
  email TEXT,
  gender TEXT,
  dob TEXT,
  city TEXT,
  income_range TEXT,
  interests TEXT NOT NULL DEFAULT '',   -- ';' separated
  source_id INTEGER REFERENCES sources(id),              -- credited source (last touch)
  first_touch_source_id INTEGER REFERENCES sources(id),  -- kept for analysis
  referred_by_id INTEGER REFERENCES members(id),         -- credited referrer
  referral_code TEXT NOT NULL UNIQUE,   -- personal link /r/<code>
  joined_on TEXT,
  last_survey_completed_on TEXT,
  stage TEXT NOT NULL DEFAULT 'lead' CHECK (stage IN ('lead','fit','completed','failed')),
  stage_reason TEXT,
  flag TEXT,                            -- review note (e.g. self-referral attempt); never auto-deleted
  profile_complete INTEGER NOT NULL DEFAULT 0,
  meta_lead_id TEXT UNIQUE,
  meta_campaign_id TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_members_source ON members(source_id);
CREATE INDEX IF NOT EXISTS idx_members_referrer ON members(referred_by_id);
CREATE INDEX IF NOT EXISTS idx_members_city ON members(city);

CREATE TABLE IF NOT EXISTS surveys (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT,
  topics TEXT NOT NULL DEFAULT '',      -- ';' separated, used to highlight interest matches
  start_date TEXT NOT NULL,
  deadline TEXT NOT NULL,               -- must be <= start_date + 15 days
  quota INTEGER,
  age_min INTEGER, age_max INTEGER, age_strict INTEGER NOT NULL DEFAULT 1,
  city TEXT, city_strict INTEGER NOT NULL DEFAULT 0,
  gender TEXT, gender_strict INTEGER NOT NULL DEFAULT 1,
  income_ranges TEXT, income_strict INTEGER NOT NULL DEFAULT 0,  -- ';' separated
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS survey_completions (
  survey_id INTEGER NOT NULL REFERENCES surveys(id),
  member_id INTEGER NOT NULL REFERENCES members(id),
  completed_on TEXT NOT NULL,
  PRIMARY KEY (survey_id, member_id)
);

CREATE TABLE IF NOT EXISTS otps (
  phone TEXT PRIMARY KEY,
  code TEXT NOT NULL,
  expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS link_touches (   -- every click on a tracked link
  id INTEGER PRIMARY KEY,
  source_id INTEGER NOT NULL REFERENCES sources(id),
  visitor_id TEXT NOT NULL,
  referrer_member_id INTEGER REFERENCES members(id),
  touched_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS meta_leads (     -- every lead received, including rejected ones (review queue)
  id INTEGER PRIMARY KEY,
  leadgen_id TEXT UNIQUE,
  payload TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('created','duplicate','rejected')),
  errors TEXT,
  member_id INTEGER REFERENCES members(id),
  received_at TEXT NOT NULL DEFAULT (datetime('now'))
);
