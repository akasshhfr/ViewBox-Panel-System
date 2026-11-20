# Database diagram

SQLite for the prototype; the schema is plain SQL (`schema.sql`) and maps directly to PostgreSQL.

```mermaid
erDiagram
    SOURCES ||--o{ MEMBERS : "credited source (last touch)"
    SOURCES ||--o{ MEMBERS : "first touch"
    SOURCES ||--o{ LINK_TOUCHES : "clicked"
    MEMBERS ||--o{ MEMBERS : "referred_by"
    MEMBERS ||--o{ SURVEY_COMPLETIONS : completes
    SURVEYS ||--o{ SURVEY_COMPLETIONS : "has"
    MEMBERS ||--o{ META_LEADS : "created from"
    MEMBERS ||--o{ LINK_TOUCHES : "referral link owner"

    SOURCES {
        int id PK
        text name UK
        text kind
        text slug UK "tracked link /s/slug"
        int active
    }
    MEMBERS {
        int id PK
        text member_code UK "VB10005"
        text phone UK "normalised 10 digits"
        text name
        text email
        text gender
        text dob
        text city
        text income_range
        text interests "semicolon list"
        int source_id FK "credited source"
        int first_touch_source_id FK
        int referred_by_id FK "self reference"
        text referral_code UK "personal link /r/code"
        text stage "lead | fit | completed | failed"
        text stage_reason
        text last_survey_completed_on "drives 3-month cool-off"
        text flag "review note"
        text meta_lead_id UK
        text meta_campaign_id
    }
    SURVEYS {
        int id PK
        text title
        text topics
        text start_date
        text deadline "max 15 days after start"
        int quota
        int age_min
        int age_max
        int age_strict
        text city
        int city_strict
        text gender
        int gender_strict
        text income_ranges
        int income_strict
    }
    SURVEY_COMPLETIONS {
        int survey_id PK, FK
        int member_id PK, FK
        text completed_on
    }
    LINK_TOUCHES {
        int id PK
        int source_id FK
        text visitor_id
        int referrer_member_id FK
        text touched_at
    }
    META_LEADS {
        int id PK
        text leadgen_id UK
        text payload
        text status "created | duplicate | rejected"
        text errors
        int member_id FK
    }
    OTPS {
        text phone PK
        text code
        text expires_at
    }
```

## Key modelling decisions

- **Sources are rows, not code.** Adding LinkedIn is one INSERT from the admin screen; the tracked link is `/s/<slug>`.
- **Two attributions on one member:** `source_id` (credited, last touch) and `first_touch_source_id` (kept for analysis). `referred_by_id` is separate, so a channel and a referrer can both be recorded.
- **One funnel stage per member** (`stage`). The source dashboard counts Fit and Completed straight from members; "My Referrals" reads the referred member's stage.
- **Referral = `members.referred_by_id`** (self-reference), so a referral can never exist without both people.
- **Survey rules live on the survey** with a `*_strict` flag each. Eligibility is *computed* on read (never stored), so editing a rule or a member's profile is reflected immediately.
- **Cool-off** needs only `last_survey_completed_on` + 3 months. `survey_completions` provides quota counts.
- **`meta_leads`** keeps every inbound lead, including rejected ones, as a review queue; nothing is silently dropped.
