# User flow: ViewBox Panel System

Three journeys: a **new member** joining through a tracked link, a **returning member** checking status, and **ops/admin** running the panel.

## 1. Member sign-up and portal

```mermaid
flowchart TD
    A[Link opened<br/>/s/slug or /r/code] -->|tracked: source saved in session, first and last touch| L
    B[Direct visit, no tag] --> L[Login: phone number]
    L -->|new member and no tag| H[Ask: How did you hear about us?<br/>+ optional referrer ID]
    L -->|tagged or existing| O
    H --> O[Mock OTP shown on screen]
    O -->|wrong or expired| O
    O -->|correct, new member| C[Create member<br/>source, first touch, referrer, referral link]
    O -->|correct, existing| P
    C --> P{Profile complete?}
    P -->|no| F[Profile form: name, DOB, gender, city, income, interests]
    F --> HM
    P -->|yes| HM[Home: live surveys]
    HM --> E[Each survey shows Approved / Waitlisted / Rejected + plain reason<br/>interest matches highlighted<br/>cool-off date if applicable]
    HM --> R[My referrals: friend, masked phone, stage, failure reason<br/>copy personal link]
```

## 2. Referral lifecycle (ops-driven)

```mermaid
stateDiagram-v2
    [*] --> Lead: friend signs up via referral link
    Lead --> Fit: ops confirms profile matches survey
    Fit --> Completed: ops marks survey done + quality check passed
    Lead --> Failed: ops records reason
    Fit --> Failed: ops records reason
    Completed --> [*]: bonus earned, 3-month cool-off starts
```

## 3. Admin / ops

```mermaid
flowchart TD
    AL[Admin login] --> D[Source dashboard<br/>sign-ups / Fit / Completed per source]
    AL --> S[Sources: add source, copy tracked link]
    AL --> M[Respondent grid: live search, filter by source / city / status]
    M --> X[Export current view: CSV or Excel]
    M --> MD[Member detail: stage change, eligibility per survey]
    AL --> SV[Surveys: create with Strict / Flexible rules, quota, deadline max 15 days]
    SV --> SD[Survey results: Approved / Waitlisted / Rejected counts]
    AL --> I[Import CSV: preview -> report of fixed / skipped rows -> confirm]
    AL --> ML[Meta leads log]
    ML -.-> API[POST /api/meta/leads<br/>creates member with source Meta Ads]
```

## Screens (mobile-first member side)

| Screen | Purpose | Empty / error states |
|---|---|---|
| Login | phone + how-heard + referrer | invalid number, missing how-heard |
| OTP | enter mock code | wrong or expired code |
| Profile | one-time details | per-field validation messages |
| Home | surveys + status + reasons | "No surveys live right now" |
| My referrals | link, friends, stages | "No referrals yet" |
