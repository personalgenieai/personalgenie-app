# PersonalGenie — PRD v9.1
## Personal OS: Know Me, Learn Me, Work for Me

| | |
|---|---|
| **Version** | 9.5 — Network Signal Intelligence + Consent-on-Demand |
| **Status** | Build-Ready |
| **Date** | March 2026 (updated 2026-03-10) |
| **Platform** | Apple Ecosystem — iPhone · Apple Watch · Mac |
| **Replaces** | PRD v9.0 |

---

## Table of Contents

1. [Product Vision](#1-product-vision)
2. [What It Is](#2-what-it-is)
3. [Core Architecture](#3-core-architecture)
4. [Brain-State Database Schema](#4-brain-state-database-schema)
5. [Skills Platform](#5-skills-platform)
5A. [Skill Sub-Brain Architecture](#5a-skill-sub-brain-architecture)
6. [Onboarding Experience](#6-onboarding-experience)
6A. [Socratic Onboarding — Invited Users](#66-socratic-onboarding--invited-users)
7. [Daily Operating Rhythm](#7-daily-operating-rhythm)
8. [Wearable Memory Engine](#8-wearable-memory-engine)
9. [Overnight Processing Engine](#9-overnight-processing-engine)
10. [Genie Personas](#10-genie-personas)
11. [Genie-to-Genie Protocol](#11-genie-to-genie-protocol)
12. [Social Onboarding & Network Effects](#12-social-onboarding--network-effects)
13. [Privacy Architecture](#13-privacy-architecture)
14. [Session Persona Assembly](#14-session-persona-assembly)
15. [Data Ingestion Sources](#15-data-ingestion-sources)
16. [Functional Requirements](#16-functional-requirements)
17. [Non-Functional Requirements](#17-non-functional-requirements)
18. [Tech Stack](#18-tech-stack)
19. [Build Milestones](#19-build-milestones)
20. [Post-MVP Roadmap](#20-post-mvp-roadmap)

---

## 1. Product Vision

PersonalGenie is a **personal operating layer** — not a chatbot, not an assistant, not an app you open when you need something. It is an ambient AI that builds a complete, structured model of who you are and uses it to create small moments of magic in your life, every day.

It knows your relationships and how you feel about them. It knows your health, your habits, your preferences, your goals, your history. It learns from everything you do — your messages, your calendar, your voice, your daily check-ins. Every night it processes what it has learned and updates its model of you. Every morning it wakes up knowing you a little better.

It is a platform. Your company ships discrete **Skills** — Health Coach, Budget Coach, Sleep Coach, Travel Planner — each of which plugs into the full brain-state and inherits everything the Genie already knows about you. Skills are ambient by default and active when you turn them on.

It is private by architecture. Everything lives on your device. Nobody else sees it. Not even us.

### 1.1 Vision Statement

> *A Genie that knows you the way a great chief of staff would — but lives entirely on your device, gets smarter every day, and grows more capable as new skills are added to its repertoire.*

### 1.2 The Problem

Every AI product today starts from zero with every user. You explain yourself every session. You configure preferences manually. The experience is generic because it has to be — it knows nothing about you that you haven't told it in the last five minutes.

The richest dataset about who you are already exists — in your messages, your emails, your photos, your calendar, your health data, your conversations. Nobody has unified it. Nobody has built a structured, living model of a person from it and used that model to power a growing suite of personal capabilities.

### 1.3 The Opportunity

PersonalGenie is the first product to:

- Ingest existing personal data to construct a rich initial persona on day one
- Maintain a structured, evolving brain-state that persists across all sessions
- Run morning and evening sessions to continuously update its world model
- Process everything overnight to detect drift, update preferences, and refine rules
- Capture ambient life moments via Apple Watch with one press
- Support a Skills Platform where new capabilities plug into the full brain-state
- Connect Genies between trusted people to create shared moments without sharing private data
- Accelerate new user onboarding through existing network relationships

---

## 2. What It Is

### 2.1 The Core Loop

```
Ingest → Model → Learn → Update → Act → Refine → Repeat
```

Data flows in from multiple sources. The brain-state database is built and continuously updated. Daily sessions add fresh signal. The overnight engine processes, detects drift, updates rules. Skills plug in and use the model. The Genie acts — a suggestion, a reminder, a coaching moment, a shared experience. Your feedback refines the model. The loop runs forever.

### 2.2 Three Operating Modes

**Onboarding** — One-time. Ingest all data sources, build initial persona, run overnight, deliver the first morning reveal. Ends when the user feels known.

**Daily Rhythm** — Perpetual. Morning session (forward-looking), evening session (reflective). The heartbeat of the product. Every session adds signal, every signal improves the model.

**Ambient Operation** — Always running in the background. Overnight processing. Skill modules recording passively. Surfaces moments of magic without being asked.

---

## 3. Core Architecture

### 3.1 System Layers

```
┌──────────────────────────────────────────────────────┐
│                   SURFACE LAYER                       │
│        iPhone · Apple Watch · Mac                     │
│   Morning Session · Evening Session · Capture         │
│   Skill Interfaces · Genie Chat                       │
├──────────────────────────────────────────────────────┤
│                 SKILLS PLATFORM                       │
│   Pluggable skill modules (Health · Budget · Sleep)   │
│   Ambient mode ←→ Active coaching mode                │
│   Each skill reads brain-state, writes to vault       │
├──────────────────────────────────────────────────────┤
│                 SESSION PERSONA                       │
│   Compressed runtime object assembled per session     │
│   from vault + active skills + current persona mode   │
├──────────────────────────────────────────────────────┤
│                 INFERENCE LAYER                       │
│   On-device (Core ML / MLX) + Cloud hybrid            │
│   Session Persona → LLM → Response                    │
├──────────────────────────────────────────────────────┤
│                OVERNIGHT ENGINE                       │
│   Drift detection · Preference updates                │
│   Rule refinement · Memory consolidation              │
│   Skill state updates · Phase detection               │
├──────────────────────────────────────────────────────┤
│                 PERSONAL VAULT                        │
│   Local SQLite + JSON · Encrypted · On-device         │
│   8 core domains · Full user visibility               │
│   Skill data namespaced per skill                     │
├──────────────────────────────────────────────────────┤
│                 INGESTION LAYER                       │
│   iMessage · WhatsApp · Gmail · Photos                │
│   Calendar · Apple Health · Wearable Capture          │
│   Skill-specific ingestion pipelines                  │
└──────────────────────────────────────────────────────┘
```

### 3.2 Core Components

| Component | Role |
|---|---|
| `vault/` | Local encrypted SQLite — the Personal Vault |
| `session_persona.py` | Assembles compressed runtime persona from vault at session start |
| `skills/` | Skill module directory — each skill is a self-contained package |
| `skill_registry.py` | Manages installed skills, active/ambient state, permissions |
| `ingestion/` | Source-specific parsers (iMessage, WhatsApp, Gmail, etc.) |
| `overnight_engine.py` | Nightly processing — drift detection, preference updates, rule refinement |
| `capture_engine.py` | Wearable audio capture, 30s chunk transcription, insight extraction |
| `genie_protocol.py` | Genie-to-Genie negotiation for shared moments |
| `morning_session.py` | Structured morning check-in |
| `evening_session.py` | Structured evening reflection |
| `inference_router.py` | Routes inference to on-device or cloud model |
| `memory_writer.py` | Routes structured insights to correct vault domains |
| `consent_manager.py` | Controls cross-Genie data access and skill permissions |
| `reasoning_trace.py` | Logs Genie decisions with full rationale and source references |

---

## 4. Brain-State Database Schema

The Personal Vault is a local SQLite database structured across 8 core domains. Every record is tagged with source, confidence, creation time, and confirmation status. The vault is fully visible to the user — every record can be viewed, corrected, or deleted at any time.

### 4.1 Universal Record Metadata

Every table across all domains includes these fields:

```sql
id              TEXT PRIMARY KEY    -- UUID
source          TEXT                -- iMessage | WhatsApp | Gmail | Photos | manual
                                    -- | capture | inferred | evening_session
                                    -- | morning_session | skill:{skill_id} | genie_protocol
confidence      REAL                -- 0.0–1.0
created_at      DATETIME
updated_at      DATETIME
user_confirmed  BOOLEAN DEFAULT FALSE
user_corrected  BOOLEAN DEFAULT FALSE
visible_to_user BOOLEAN DEFAULT TRUE
deletable       BOOLEAN DEFAULT TRUE
```

### 4.2 Domain 1 — Identity & Self

```sql
CREATE TABLE identity (
  id              TEXT PRIMARY KEY,
  field           TEXT,    -- name | dob | location | nationality
                           -- | occupation | languages | self_description
  value           TEXT,
  -- + universal metadata
);

CREATE TABLE self_goals (
  id              TEXT PRIMARY KEY,
  domain          TEXT,    -- health | finance | relationships | appearance
                           -- | confidence | career | spirituality | other
  goal            TEXT,
  priority        INTEGER, -- 1 (highest) to 5
  status          TEXT,    -- active | paused | achieved | abandoned
  set_at          DATETIME,
  reviewed_at     DATETIME,
  -- + universal metadata
);
```

### 4.3 Domain 2 — Relationships

```sql
CREATE TABLE relationships (
  id                TEXT PRIMARY KEY,
  name              TEXT,
  relationship_type TEXT,  -- partner | parent | sibling | child | first_cousin
                           -- | extended_family | close_friend | friend | colleague
                           -- | doctor | therapist | trainer | contractor
                           -- | neighbour | emergency_contact | other
  tier              INTEGER, -- 1: partner/immediate | 2: close | 3: important | 4: peripheral
  emotional_valence TEXT,    -- love | like | neutral | complicated | dislike
  emotional_notes   TEXT,
  contact_frequency TEXT,    -- daily | weekly | monthly | rarely
  last_contact      DATETIME,
  location          TEXT,
  shared_history    TEXT,
  what_i_want       TEXT,    -- what the user wants from/for this relationship
  genie_paired      BOOLEAN DEFAULT FALSE,
  genie_pair_id     TEXT,
  pairing_type      TEXT,    -- partner | family | friend | co_parent
  -- + universal metadata
);

CREATE TABLE relationship_signals (
  id              TEXT PRIMARY KEY,
  relationship_id TEXT REFERENCES relationships(id),
  signal_type     TEXT,    -- message | call | mention | meeting | shared_event
  signal_at       DATETIME,
  sentiment       TEXT,    -- positive | neutral | negative | mixed
  notes           TEXT,
  source          TEXT
);
```

### 4.3b Person Facts

Structured, queryable facts about a specific person in the user's life. Distinct from:
- **Memories** — episodic moments ("the Valentine's dinner")
- **Relationship signals** — behavioral events ("messaged 3 times this week")
- **Preferences** — the user's own preferences

Person facts are stable, confirmable, and time-bounded where relevant:

```sql
CREATE TABLE person_facts (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_user_id   UUID REFERENCES users(id),
  person_id       UUID REFERENCES people(id),
  -- NULL person_id = fact about the owner themselves

  fact_key        TEXT NOT NULL,
  -- e.g. "monthly_support_amount" | "support_end_date"
  --      "job_search_status" | "base_city" | "sobriety_status"
  --      "relationship_goal" | "communication_style"

  fact_value      TEXT NOT NULL,
  fact_type       TEXT DEFAULT 'text',
  -- text | number | date | boolean | json

  domain          TEXT,
  -- relationships | health | finance | logistics | goals

  confidence      FLOAT DEFAULT 1.0,
  -- 1.0 = user_stated | 0.7 = genie_inferred | 0.5 = from_messages

  source          TEXT DEFAULT 'user_stated',
  -- user_stated | genie_inferred | imessage_analysis | session

  expires_at      TIMESTAMPTZ,
  -- NULL = permanent. Time-bounded facts expire automatically.

  user_confirmed  BOOLEAN DEFAULT FALSE,
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  updated_at      TIMESTAMPTZ DEFAULT NOW(),

  UNIQUE(owner_user_id, person_id, fact_key)
  -- one canonical value per fact per person — update in place
);
```

**Example facts (TJ):**

| fact_key | fact_value | source |
|---|---|---|
| `monthly_support_amount` | `1000` | user_stated |
| `support_end_date` | `2026-08-01` | user_stated |
| `support_pre_august_type` | `gift_no_payback` | user_stated |
| `support_post_august_type` | `loan_when_stable` | user_stated |
| `job_search_status` | `applying_independently` | user_stated |
| `interview_weakness` | `confidence_not_effort` | user_stated |
| `relationship_goal` | `equal_friendship` | user_stated |

---

### 4.4 Domain 3 — Preferences

```sql
CREATE TABLE preferences (
  id              TEXT PRIMARY KEY,
  domain          TEXT,    -- food | drink | music | travel | exercise | clothing
                           -- | sleep | entertainment | social | home | work
                           -- | communication | spending | other
  subdomain       TEXT,    -- e.g. food > cuisine | music > genre | travel > accommodation
  preference_type TEXT,    -- hard | soft
  value           TEXT,
  sentiment       TEXT,    -- love | like | neutral | dislike | hate
  context         TEXT,    -- situational context for this preference
  phase_aware     BOOLEAN, -- does this change by life phase?
  active          BOOLEAN DEFAULT TRUE,
  -- + universal metadata
);

CREATE TABLE preference_phases (
  id              TEXT PRIMARY KEY,
  preference_id   TEXT REFERENCES preferences(id),
  phase_label     TEXT,    -- e.g. "health_month_1" | "stressed_period" | "energetic_period"
  override_value  TEXT,
  override_behaviour TEXT, -- e.g. "remind daily" | "remind every 3 days" | "do not remind"
  active          BOOLEAN,
  started_at      DATETIME,
  ended_at        DATETIME
);
```

### 4.5 Domain 4 — Health & Wellness

```sql
CREATE TABLE health_profile (
  id              TEXT PRIMARY KEY,
  field           TEXT,    -- height | weight | blood_type | conditions | medications
                           -- | allergies | dietary_restrictions | sleep_target | step_target
  value           TEXT,
  unit            TEXT,
  recorded_at     DATETIME,
  -- + universal metadata
);

CREATE TABLE health_daily_log (
  id              TEXT PRIMARY KEY,
  log_date        DATE,
  food_log        TEXT,    -- JSON: [{meal, items, time, notes}]
  water_ml        INTEGER,
  sleep_hours     REAL,
  sleep_quality   TEXT,    -- great | good | ok | poor
  energy_level    TEXT,    -- high | medium | low
  mood            TEXT,
  steps           INTEGER,
  workout         TEXT,    -- JSON: {type, duration, notes, trainer_notes}
  notes           TEXT,
  source          TEXT
);

CREATE TABLE fitness_records (
  id              TEXT PRIMARY KEY,
  exercise_type   TEXT,
  metric          TEXT,    -- PR | weight | reps | time | distance
  value           TEXT,
  unit            TEXT,
  context         TEXT,    -- trainer notes, conditions, fatigue level
  recorded_at     DATETIME,
  source          TEXT
);
```

### 4.6 Domain 5 — Memories & Events

```sql
CREATE TABLE memories (
  id              TEXT PRIMARY KEY,
  title           TEXT,
  description     TEXT,
  memory_type     TEXT,    -- travel | meal | event | achievement | conversation
                           -- | milestone | experience | other
  people_involved TEXT,    -- JSON array of relationship IDs
  location        TEXT,
  emotion         TEXT,
  occurred_at     DATETIME,
  -- + universal metadata
);

CREATE TABLE captured_sessions (
  id              TEXT PRIMARY KEY,
  session_type    TEXT,    -- gym | meeting | conversation | walk | medical | other
  started_at      DATETIME,
  ended_at        DATETIME,
  duration_s      INTEGER,
  transcript      TEXT,    -- full session transcript (chunked and assembled)
  insights        TEXT,    -- JSON: structured insights extracted by LLM
  people_present  TEXT,    -- JSON array of relationship IDs
  location        TEXT,
  skill_id        TEXT,    -- if captured in context of a skill
  audio_deleted   BOOLEAN DEFAULT TRUE
);
```

### 4.7 Domain 6 — Finance

```sql
CREATE TABLE finance_profile (
  id              TEXT PRIMARY KEY,
  field           TEXT,    -- income_range | savings_habit | investment_style
                           -- | debt_status | financial_goals | spending_style
  value           TEXT,
  -- + universal metadata
);

CREATE TABLE spending_log (
  id              TEXT PRIMARY KEY,
  log_date        DATE,
  category        TEXT,    -- food | transport | entertainment | clothing | health | other
  amount          REAL,
  currency        TEXT,
  notes           TEXT,
  source          TEXT
);
```

### 4.8 Domain 7 — Reasoning Traces

This is the traceability layer — every significant decision, suggestion, or rule the Genie creates is logged with full rationale. This enables the Genie to reference its own reasoning history and builds trust through transparency.

```sql
CREATE TABLE reasoning_traces (
  id              TEXT PRIMARY KEY,
  action_type     TEXT,    -- suggestion | reminder | rule_created | preference_updated
                           -- | phase_detected | skill_action | morning_content
                           -- | evening_question | genie_protocol_signal
  action          TEXT,    -- what the Genie did or said
  rationale       TEXT,    -- why — in plain language
  memory_refs     TEXT,    -- JSON array of vault record IDs referenced
  preference_refs TEXT,    -- JSON array of preference IDs referenced
  skill_id        TEXT,    -- if triggered by a skill
  persona_mode    TEXT,    -- Sentinel | Companion | Whisper at time of action
  user_response   TEXT,    -- how the user responded (accepted | corrected | ignored | deleted)
  created_at      DATETIME
);
```

**Example reasoning trace:**

```json
{
  "action_type": "suggestion",
  "action": "Suggested booking dinner at Nobu tonight",
  "rationale": "Partner's Genie signalled openness to a spontaneous evening out. User's preference vault shows they love Japanese cuisine (hard preference, confirmed). User's mood log from this morning shows high energy. Last dinner out together was 18 days ago, exceeding their soft preference of weekly.",
  "memory_refs": ["mem_892", "mem_341"],
  "preference_refs": ["pref_food_japanese_001", "pref_social_dining_frequency_003"],
  "skill_id": null,
  "persona_mode": "Companion"
}
```

### 4.8b Recommendations

Actionable advice the Genie has surfaced, with full reasoning chain stored for explainability. Every recommendation is traceable back to the specific observations, patterns, and goals that produced it.

```sql
CREATE TABLE recommendations (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_user_id     UUID REFERENCES users(id),
  person_id         UUID REFERENCES people(id),
  -- NULL = recommendation about the user themselves

  title             TEXT NOT NULL,
  -- "The TJ Financial Bridge Conversation"

  recommendation_text TEXT NOT NULL,
  -- plain language: what to do

  script            TEXT,
  -- optional: exact words to say, verbatim

  timing            TEXT,
  -- right_now | this_week | plan_ahead | when_ready

  domain            TEXT,
  -- relationships | health | finance | exercise | nutrition | self

  status            TEXT DEFAULT 'pending',
  -- pending | delivered | acted_on | dismissed | snoozed | expired

  reasoning_chain   JSONB NOT NULL DEFAULT '{}',
  -- full reasoning — see shape below

  delivered_at      TIMESTAMPTZ,
  user_response     TEXT,    -- what the user said after receiving it
  outcome           TEXT,    -- acted_on | dismissed | modified | deferred
  outcome_notes     TEXT,    -- what actually happened / user correction

  created_at        TIMESTAMPTZ DEFAULT NOW(),
  updated_at        TIMESTAMPTZ DEFAULT NOW()
);
```

**reasoning_chain shape:**

```json
{
  "observations": [
    "Leo has raised card separation 3+ times without resolution",
    "TJ applying independently — dependency is confidence not motivation",
    "Leo's severance ends August — external constraint already communicated"
  ],
  "pattern_identified": "Leo's generosity outpaces TJ's independence development",
  "goal": "Transition to equal friendship with no financial residue",
  "why_this_approach": "August is external not personal — removes withdrawal sting",
  "why_this_framing": "Pre-August as gift removes shame; post-August loan restores TJ's agency",
  "what_not_to_do": "No formal agreement, no dollar total, do not send over text",
  "fact_refs": ["monthly_support_amount", "support_end_date", "job_search_status"],
  "memory_refs": ["Valentine dinner", "Credit card conversation(s)"]
}
```

**Why this matters:** When the user asks *"why did you suggest that?"* six months later, the Genie reads the reasoning chain and explains itself in plain language — not reconstructed from scratch, but retrieved from what it actually knew at the time.

---

### 4.9 Domain 8 — Skill State

Each installed skill has its own namespaced state table. See Section 5 for full schema.

---

### 4.10 Explainability Architecture

Every significant Genie output is traceable. The three layers work together:

```
person_facts        →  what the Genie knew (inputs)
reasoning_chain     →  why it concluded what it did (logic)
recommendations     →  what it said and what happened (output + outcome)
```

**How explainability works in practice:**

When the user asks *"why did you suggest that?"*:

1. Genie looks up the `recommendation` by title or recency
2. Reads `reasoning_chain.observations` — what it saw in the data
3. Reads `reasoning_chain.pattern_identified` — what pattern it named
4. Reads `reasoning_chain.goal` — what the user wanted
5. Reads `reasoning_chain.why_this_framing` — why those specific words

Response in the Genie's voice:
> *"When we talked in March, you'd raised the credit card separation three times and it hadn't happened. TJ was applying to jobs on his own — the problem wasn't motivation, it was confidence. August was already the agreed end point, so I used it as the anchor rather than introducing a new boundary. The gift/loan framing came from what I know about TJ: shame about dependency is the real friction, not the money itself."*

**What is NOT reconstructed:** The Genie never re-derives its reasoning from raw messages. It reads the stored chain. This means the explanation is stable and auditable — it won't shift based on new data unless the user explicitly asks the Genie to re-evaluate.

**Three storage layers at a glance:**

| Layer | Table | What it stores | Queryable? |
|---|---|---|---|
| Facts | `person_facts` | Stable, confirmable facts about a person | Yes — by key |
| Memories | `moments` | Episodic, contextual moments | By person, emotion, topic |
| Preferences | `preferences` | User's own behavioral patterns | By domain |
| Decisions | `reasoning_traces` | All Genie actions with rationale | By action_type |
| Recommendations | `recommendations` | Actionable advice + script + reasoning chain + outcome | By person, domain, status |

---

## 5. Skills Platform

### 5.1 Overview

Skills are discrete capability modules built by PersonalGenie and shipped as first-party extensions to the core Genie. Each skill:

- Plugs into the full brain-state on activation
- Has two operating modes: **Ambient** (passive recording only) and **Active** (coaching, prompting, tracking)
- Contributes structured data back to the relevant vault domains
- Learns the user's preferences within its domain over time
- Persists its own state in a namespaced skill table
- Can be activated, paused, or removed at any time

Skills do not see raw vault data. They receive a skill-scoped persona — a curated subset of brain-state relevant to that skill's domain — assembled by `session_persona.py` at runtime.

### 5.2 Skill Operating Modes

**Ambient Mode (default)**
- Skill is installed but not actively coaching
- Passively ingests relevant data from wearable captures, evening sessions, and health logs
- Builds its domain model silently
- Does not initiate conversations or send proactive reminders
- User can activate to Active mode at any time — and when they do, the skill already has data

**Active Mode (user-initiated)**
- Skill becomes a participant in morning and evening sessions
- Initiates proactive coaching conversations based on goals and preferences
- Sends reminders, asks follow-up questions, tracks progress
- Surfaces suggestions and interventions based on its domain model
- Behaviour adapts based on persona mode (Sentinel = aggressive coaching, Whisper = gentle nudges)

### 5.3 Skill Schema

```sql
CREATE TABLE skill_registry (
  skill_id        TEXT PRIMARY KEY,  -- e.g. "health_coach" | "budget_coach" | "sleep_coach"
  skill_name      TEXT,
  version         TEXT,
  installed_at    DATETIME,
  mode            TEXT,              -- ambient | active
  mode_changed_at DATETIME,
  persona_scopes  TEXT,              -- JSON: which vault domains this skill can read
  vault_domains   TEXT,              -- JSON: which vault domains this skill can write to
  active          BOOLEAN DEFAULT TRUE
);

CREATE TABLE skill_state_{skill_id} (
  -- Each skill has its own namespaced state table
  -- Schema defined per skill — examples below
);

CREATE TABLE skill_preferences (
  id              TEXT PRIMARY KEY,
  skill_id        TEXT REFERENCES skill_registry(skill_id),
  preference_key  TEXT,   -- skill-specific preference key
  preference_type TEXT,   -- hard | soft
  value           TEXT,
  phase_label     TEXT,   -- optional phase context
  user_confirmed  BOOLEAN,
  created_at      DATETIME,
  updated_at      DATETIME
);

CREATE TABLE skill_reasoning_traces (
  id              TEXT PRIMARY KEY,
  skill_id        TEXT,
  action          TEXT,
  rationale       TEXT,
  vault_refs      TEXT,   -- JSON
  user_response   TEXT,
  created_at      DATETIME
);
```

### 5.4 First-Party Skills — V1

#### Skill: Health Coach (`health_coach`)

**Persona scope:** health_profile, health_daily_log, fitness_records, preferences (exercise, food), self_goals (health), captured_sessions (gym, medical, walk)

**Ambient behaviour:**
- Ingests gym captures silently
- Logs any food or exercise mentioned in evening sessions
- Tracks Apple Health data passively

**Active behaviour:**
- Morning: asks about energy, planned workout, any health intention for the day
- Evening: asks about food, water, workout completion, how the body felt
- Proactively surfaces: workout suggestions based on trainer notes and fitness records, nutrition observations, recovery nudges
- Tracks PRs, flags fatigue patterns, adapts suggestions to current life phase

**Skill state table:**
```sql
CREATE TABLE skill_state_health_coach (
  id                  TEXT PRIMARY KEY,
  current_phase       TEXT,    -- e.g. "building_strength" | "weight_loss" | "maintenance"
  weekly_workout_goal INTEGER,
  daily_calorie_goal  INTEGER,
  daily_water_goal_ml INTEGER,
  current_focus       TEXT,    -- e.g. "legs" | "cardio" | "full_body"
  trainer_name        TEXT,
  trainer_notes       TEXT,    -- latest trainer observations
  check_in_frequency  TEXT,    -- daily | every_2_days | every_3_days (phase-aware)
  updated_at          DATETIME
);
```

#### Skill: Budget Coach (`budget_coach`)

**Persona scope:** finance_profile, spending_log, preferences (spending, lifestyle), self_goals (finance), identity (occupation)

**Ambient behaviour:**
- Ingests any financial mentions from Gmail, iMessage, or captures
- Passively builds a picture of spending patterns and financial context
- Syncs Plaid in background once connected — no user action required

**Active behaviour:**
- Onboarding conversation: monthly budget, income range, top spending categories, savings goals
- Walks user through Sub-Brain rule configuration in plain language
- Morning: surfaces rule-triggered alerts (e.g. unmatched transactions, budget proximity)
- Evening: asks about any significant spend that day (rule-configured frequency)
- Weekly summary delivered per user's output preferences (format, tone, depth, timing)
- Proactively proposes new rules based on observed patterns

**Sub-Brain — Default rules on activation:**

| Rule | Trigger | Action |
|---|---|---|
| Receipt Matching | Receipt uploaded | Match to Plaid, flag gaps, ask about unmatched items |
| Large Transaction Alert | Transaction > user-set threshold | Notify immediately, ask for context |
| Budget Category Proximity | Category spend > 80% of limit | Alert user with current vs. limit |
| Weekly Summary | Every Sunday evening (configurable) | Deliver summary in user's preferred format |
| Auto-categorisation | New Plaid transaction | Apply learned category rules, flag unknowns |
| Savings Milestone | Savings target % reached | Celebrate and ask if target should update |

**Integrations:**
- **Plaid** — bank/card transaction sync (OAuth, read-only)
- **Receipt capture** — photo import via camera or share sheet, parsed on-device by vision model
- **Apple Wallet** — Apple Pay transaction history (local HealthKit-equivalent, no OAuth)

**Skill state table:**
```sql
CREATE TABLE skill_state_budget_coach (
  id                    TEXT PRIMARY KEY,
  monthly_budget        REAL,
  currency              TEXT,
  budget_categories     TEXT,    -- JSON: [{category, limit, current_spend, auto_rules}]
  savings_goal          REAL,
  savings_current       REAL,
  savings_target_date   DATE,
  large_txn_threshold   REAL,    -- user-configured alert threshold
  plaid_connected       BOOLEAN,
  last_plaid_sync       DATETIME,
  current_month_spend   REAL,
  updated_at            DATETIME
);
```

#### Skill: Sleep Coach (`sleep_coach`) — Post-MVP

**Persona scope:** health_daily_log (sleep), preferences (sleep, evening routine), health_profile, mood

**Active behaviour:**
- Evening: asks about wind-down routine, screen time, stress level
- Morning: asks about sleep quality, dream recall if relevant, energy on waking
- Proactively suggests: bedtime based on sleep target, routine changes, pattern observations

### 5.5 Skill Preference Learning

Skills learn user preferences within their domain through the same hard/soft preference model as the core Genie. Examples:

- Health Coach learns: "User prefers leg day on Mondays", "User does not want food logging reminders before 6pm", "User responds well to PR celebrations but dislikes being told to rest"
- Budget Coach learns: "User is comfortable discussing finances in evening sessions but not morning", "User prefers weekly summary over daily nudges after month 2"

These are stored in `skill_preferences` and fed into the skill's session persona scope. Phase overrides apply — the user can configure more aggressive behaviour in early phases of a skill and lighter touch as habits form.

### 5.6 Skill-to-Genie Integration

When a skill is active, it participates in the Session Persona assembly. The morning and evening sessions are dynamically constructed to include skill-contributed questions and observations alongside the core Genie's check-ins. The user experiences one seamless conversation — not separate apps or modes.

Skills also contribute to reasoning traces. Every coaching suggestion a skill makes is logged with its rationale and vault references, visible to the user in the transparency view.

---


---

## 5A. Skill Sub-Brain Architecture

### 5A.1 Overview

Every skill in PersonalGenie has its own **Sub-Brain** — a self-contained reasoning and execution layer that sits between the skill's data and the core Genie. The Sub-Brain is not hardcoded logic. It is a living rule graph that:

- The user configures in plain language at a high level
- The skill formalises into structured, executable rules
- The skill refines autonomously as it learns more about the user
- The user can inspect, edit, approve, or delete at any time

This means the skill's behaviour — what it does, when it does it, how it reasons, how it communicates results — is fully programmable by the user without any technical knowledge, and self-improving over time.

The Sub-Brain is the mechanism that makes a skill genuinely personal, not just personalised.

### 5A.2 Sub-Brain Components

Each skill's Sub-Brain consists of four layers:

```
┌──────────────────────────────────────────────────┐
│              RULE GRAPH                          │
│  Triggers · Conditions · Actions · Cadence       │
│  User-configured intent → Skill-formalised rules │
├──────────────────────────────────────────────────┤
│              INTEGRATION LAYER                   │
│  External data sources owned by this skill       │
│  Plaid · Apple Health · Calendar · Receipts      │
├──────────────────────────────────────────────────┤
│              OUTPUT PREFERENCES                  │
│  How, when, and in what format the skill         │
│  communicates with the user                      │
├──────────────────────────────────────────────────┤
│              SKILL REASONING TRACES              │
│  Every rule execution logged with full rationale │
│  References vault records + rule IDs             │
└──────────────────────────────────────────────────┘
```

### 5A.3 Rule Graph Schema

```sql
CREATE TABLE skill_rules_{skill_id} (
  rule_id           TEXT PRIMARY KEY,        -- UUID
  rule_name         TEXT,                    -- human-readable label
  rule_description  TEXT,                    -- plain language: what this rule does
  user_intent       TEXT,                    -- the original plain-language instruction from user
  status            TEXT,                    -- active | paused | draft | archived
  
  -- Trigger
  trigger_type      TEXT,                    -- event | schedule | condition | data_arrival
  trigger_config    TEXT,                    -- JSON: trigger-specific configuration
  
  -- Conditions (optional pre-checks before action fires)
  conditions        TEXT,                    -- JSON array of condition objects
  
  -- Action
  action_type       TEXT,                    -- notify | ask | summarise | match | flag
                                             -- | write_vault | call_integration | propose_rule
  action_config     TEXT,                    -- JSON: action-specific configuration
  
  -- Cadence
  cadence_type      TEXT,                    -- once | recurring | triggered
  cadence_config    TEXT,                    -- JSON: frequency, day, time, cooldown
  
  -- Learning
  user_confirmed    BOOLEAN DEFAULT FALSE,   -- user explicitly approved this rule
  auto_proposed     BOOLEAN DEFAULT FALSE,   -- skill proposed this rule autonomously
  execution_count   INTEGER DEFAULT 0,
  last_executed_at  DATETIME,
  success_rate      REAL,                    -- 0.0–1.0 based on user responses
  
  created_at        DATETIME,
  updated_at        DATETIME
);
```

### 5A.4 Rule Anatomy

Every rule has four parts: **Trigger**, **Conditions**, **Action**, and **Cadence**.

**Trigger types:**

| Type | Description | Example |
|---|---|---|
| `event` | A specific data event occurs | Receipt uploaded, transaction synced |
| `schedule` | Time-based recurring trigger | Every Sunday at 6pm |
| `condition` | A vault or skill state condition is met | Spending exceeds 80% of budget category |
| `data_arrival` | New external data arrives from integration | Plaid sync returns new transactions |

**Action types:**

| Type | Description | Example |
|---|---|---|
| `notify` | Surface a message to the user | "You have 3 unmatched transactions this week" |
| `ask` | Initiate a structured question sequence | Ask about purpose of flagged transactions |
| `summarise` | Generate and deliver a summary | Weekly budget summary in user's preferred format |
| `match` | Cross-reference two data sets, identify gaps | Match receipts to Plaid transactions |
| `flag` | Mark a vault record for user review | Flag transaction with no category |
| `write_vault` | Write structured output to vault | Write confirmed transaction category to finance log |
| `call_integration` | Fetch data from external integration | Trigger Plaid sync |
| `propose_rule` | Skill proposes a new rule to the user | "I noticed a pattern — want me to make this a rule?" |

### 5A.5 User-Configured Logic Flow

The user configures skill logic in plain language. The skill formalises it into a rule. The user confirms. The rule executes.

**Step 1 — User states intent (plain language):**
> "Every time I upload a receipt, match it to my Plaid transactions and tell me about any gaps."

**Step 2 — Skill formalises into a rule:**
```json
{
  "rule_name": "Receipt-to-Plaid Matching",
  "rule_description": "On each receipt upload, match to Plaid transactions. Flag any unmatched receipts or transactions within ±10% amount and ±2 days.",
  "trigger_type": "event",
  "trigger_config": { "event": "receipt_uploaded" },
  "conditions": [],
  "action_type": "match",
  "action_config": {
    "source_a": "uploaded_receipts",
    "source_b": "plaid_transactions",
    "match_fields": ["amount", "date", "merchant"],
    "amount_tolerance_pct": 10,
    "date_tolerance_days": 2,
    "on_gap": "ask"
  },
  "cadence_type": "triggered",
  "auto_proposed": false,
  "user_confirmed": false
}
```

**Step 3 — Skill presents rule for confirmation:**
> "Here's how I'd handle that: when you upload a receipt, I'll match it against your Plaid transactions. If anything doesn't line up — within 10% on amount and 2 days on date — I'll ask you about it. Sound right?"

**Step 4 — User confirms (or adjusts):**
> "Yes, but also flag anything over £50 with no matching receipt automatically."

**Step 5 — Skill updates rule and writes to `skill_rules_budget_coach`:**
```json
{
  "conditions": [
    {
      "field": "plaid_transaction.amount",
      "operator": "gt",
      "value": 50,
      "action_on_true": "flag_for_review"
    }
  ]
}
```

**Step 6 — Rule is active. Skill executes autonomously from now on.**

### 5A.6 Self-Writing Rules

The skill observes patterns in its own execution and the user's responses, and autonomously proposes new rules.

**Pattern detection triggers a proposal:**

After 6 weeks of Budget Coach usage, the skill notices:
- User consistently re-categorises food delivery transactions from "Food & Drink" to "Takeaway"
- User has corrected this 14 times

**Skill proposes a new rule:**
> "I've noticed you always move food delivery charges to 'Takeaway' — I've been doing that manually for you 14 times. Want me to make that automatic? I'll create a rule: any transaction from Deliveroo, Uber Eats, or Just Eat goes straight to Takeaway."

User confirms → rule is written to `skill_rules_budget_coach` with `auto_proposed: true`.

**Self-writing rule schema:**
```json
{
  "rule_name": "Auto-categorise Food Delivery",
  "trigger_type": "data_arrival",
  "trigger_config": { "source": "plaid_transactions" },
  "conditions": [
    {
      "field": "merchant_name",
      "operator": "in",
      "value": ["Deliveroo", "Uber Eats", "Just Eat", "DoorDash"]
    }
  ],
  "action_type": "write_vault",
  "action_config": {
    "target": "spending_log",
    "field": "category",
    "value": "Takeaway"
  },
  "cadence_type": "triggered",
  "auto_proposed": true,
  "user_confirmed": true
}
```

### 5A.7 Output Preferences

The user configures not just what the skill does, but how it communicates results. Output preferences are stored per skill and loaded into the skill's session persona scope.

```sql
CREATE TABLE skill_output_preferences_{skill_id} (
  id                TEXT PRIMARY KEY,
  output_type       TEXT,     -- summary | alert | question | suggestion | report
  format            TEXT,     -- conversational | bullet_points | table | narrative
  tone              TEXT,     -- direct | warm | analytical | motivational
  frequency         TEXT,     -- daily | weekly | monthly | on_event
  preferred_time    TEXT,     -- morning | evening | specific time
  depth             TEXT,     -- brief | standard | detailed
  include_fields    TEXT,     -- JSON: which data points to always include
  exclude_fields    TEXT,     -- JSON: what to never surface
  user_confirmed    BOOLEAN,
  created_at        DATETIME,
  updated_at        DATETIME
);
```

**Budget Coach output preference example:**

User says: "Every week give me a summary of what I need to hear — not everything, just the important stuff. Keep it honest but not depressing."

Skill writes:
```json
{
  "output_type": "summary",
  "format": "conversational",
  "tone": "direct",
  "frequency": "weekly",
  "preferred_time": "Sunday evening",
  "depth": "brief",
  "include_fields": ["budget_vs_actual", "top_3_categories", "biggest_single_spend", "savings_progress"],
  "exclude_fields": ["full_transaction_list", "subcategory_breakdown"]
}
```

The weekly summary the user receives is then assembled using these preferences as formatting instructions to the LLM, alongside the skill's data output.

### 5A.8 Integration Layer

Each skill owns its external integration connections. Integrations are declared in the skill manifest and managed through the skill's settings UI — not the core Genie settings.

```sql
CREATE TABLE skill_integrations_{skill_id} (
  integration_id    TEXT PRIMARY KEY,
  integration_name  TEXT,       -- e.g. "Plaid" | "Strava" | "MyFitnessPal"
  integration_type  TEXT,       -- oauth | api_key | file_import | local_framework
  status            TEXT,       -- connected | disconnected | error | pending
  last_synced_at    DATETIME,
  sync_frequency    TEXT,       -- realtime | hourly | daily | on_demand
  scope             TEXT,       -- JSON: what permissions are granted
  credentials_ref   TEXT,       -- reference to Secure Enclave stored credential (never raw)
  connected_at      DATETIME
);
```

**Budget Coach integrations:**
- **Plaid** — bank/card transaction sync (OAuth, read-only)
- **Receipt capture** — photo import via camera or share sheet, parsed by vision model
- **Apple Wallet** — Apple Pay transaction history (local, no OAuth needed)

**Health Coach integrations:**
- **Apple Health** — HealthKit (local framework, no OAuth)
- **Strava** — workout import (OAuth, read-only) — optional
- **MyFitnessPal** — food log import (OAuth, read-only) — optional

### 5A.9 Rule Execution & Reasoning Traces

Every rule execution is logged in `skill_reasoning_traces` with:
- Which rule fired and why
- What data it acted on (vault record references)
- What action it took
- What the user's response was

This creates a complete, auditable history of every autonomous action the skill has taken. The user can see it, question it, and use it to refine the rule.

**Example trace — Receipt matching rule:**
```json
{
  "rule_id": "rule_receipt_plaid_match_001",
  "rule_name": "Receipt-to-Plaid Matching",
  "trigger": "receipt_uploaded — Waitrose, £47.20, 8 March",
  "action": "Matched to Plaid transaction TXN_8821 (£47.20, 8 March, Waitrose). Full match. No gap.",
  "vault_refs": ["receipt_291", "txn_8821"],
  "user_response": null,
  "outcome": "auto_resolved"
}
```

```json
{
  "rule_id": "rule_receipt_plaid_match_001",
  "trigger": "Plaid sync — Amazon, £124.99, 7 March. No matching receipt.",
  "action": "Flagged for user review. Asked: 'I see a £124.99 Amazon charge on 7 March with no receipt — do you remember what this was for?'",
  "vault_refs": ["txn_8803"],
  "user_response": "Work equipment — laptop stand",
  "outcome": "categorised: Work Expenses. Rule note: Amazon transactions over £50 with no receipt — always ask."
}
```

### 5A.10 Skill Sub-Brain Transparency View

Users can open any skill and see:

1. **Rule Graph** — all active rules, their triggers, conditions, and actions. Edit or delete any rule.
2. **Proposed Rules** — rules the skill has proposed but the user hasn't confirmed yet.
3. **Execution Log** — chronological list of every rule that has fired, with full trace.
4. **Integration Status** — each connected integration, last sync time, what data is flowing.
5. **Output Preferences** — how the skill talks to the user, editable at any time.
6. **Skill Preferences** — the hard and soft preferences the skill has learned, with confidence scores.

Everything is editable. Nothing is locked. The skill never acts on a self-proposed rule until the user confirms it.


---

## 6. Onboarding Experience

### 6.0 Two Paths (Flow A / Flow B)

**Flow A — Mac Connected (primary):** User has a Mac on the same WiFi. Mac companion server reads `~/Library/Messages/chat.db` directly. Batch-counts all contacts, analyzes top 15 by message count overnight, delivers full relationship graph on Day 1. This is the magic path — target 80%+ of users.

**Flow B — No Mac:** User pastes iMessage exports manually or connects contacts only. Relationship graph is thin initially. Maturity tracker gaps drive the user to add data over time. Build Flow B after Flow A is stable.

### 6.1 Phase 1 — Data Intake (Day 0)

#### 6.1.1 Connection Flow

1. **Mac companion check** — App pings local network for Mac companion server. If found, confirms automatically.
2. **Google sign-in** — OAuth read-only Gmail + Google Calendar access.
3. **Contacts permission** — Apple Contacts read access.
4. **Apple Health** — HealthKit read access (steps, workouts, sleep, heart rate).

All ingestion is local. No raw data leaves the device.

#### 6.1.2 Parallel Onboarding Interview

While data ingestion runs in the background, the Genie asks **exactly 4 questions** — one per domain — conversationally, not as a form:

| # | Domain | Question Intent |
|---|--------|----------------|
| 1 | **Relationships** | "Who are the most important people in your life right now?" — captures names, roles, and what the user wants from those relationships. Sets initial vault targets before iMessage data arrives. |
| 2 | **Physical Health** | "How would you describe where you're at physically right now?" — captures baseline, current routine, and any professional support (trainer, physio). |
| 3 | **Nutrition** | "What does eating look like for you day to day?" — captures diet type, meal pattern, relationship with food. No judgment. |
| 4 | **Exercise** | "What does your movement/exercise routine look like?" — captures types, frequency, current goals. Completes the physical picture. |

These answers seed the 4 maturity domains immediately. Data ingestion fills the gaps.

### 6.2 Phase 2 — Overnight Build (Night 0)

The overnight engine runs its first full pass:

- **Relationship graph** — batch-counts all iMessage contacts, analyzes top 15 by message count. Per contact: relationship type, tier, emotional valence, key memory, patterns, what you want, maturity vectors.
- **Cross-domain synthesis** — connects relationship data with health and calendar signals to find patterns that span domains.
- **Maturity scoring** — scores all 4 domains across 5 vectors each (0–4). Identifies the highest-value gaps.
- **Morning reveal draft** — generates the first morning reveal in the Genie's voice: warm, direct, specific to real data. 400–600 words. References actual moments from messages.
- **WhatsApp notification** — when the morning reveal is ready, sends a WhatsApp message: *"I spent the night reading through your messages. I'm ready when you are."*

### 6.3 Phase 3 — The First Morning (Day 1)

The morning reveal is delivered as a **flowing chat conversation**, not cards. The Genie speaks first — one long opening message with specific observations across relationships and health — then invites response.

**Format:** Conversational prose. The Genie addresses the user directly ("you"), references real things from their messages, connects across domains (relationships + health + how they're doing as a person). Ends by naming what the Genie still wants to understand — framing gaps as curiosity, not incompleteness.

**Voice:** Warm, perceptive, direct. Like a brilliant chief of staff who read everything and is now telling you what they noticed. Not a list of facts — a conversation that feels like someone finally sees you clearly.

**Length:** 400–600 words for the opening reveal. User responds naturally. Session continues as conversation.

**What it is NOT:** Cards, bullet points, a list of relationship summaries, or a generic "here's what I know about you" interface.

> *"You and TJ have 11,000 messages. That's years of daily life in text form. What I noticed most isn't the big moments — it's the scaffolding. You carry a lot of the emotional load in that dynamic, and you seem to do it willingly. I want to ask you about that."*

### 6.4 Ongoing Onboarding

The first morning is not the end of onboarding — it is the beginning of a continuous process. The Genie uses the maturity tracker to surface gaps naturally in conversation, never as a form.

Gaps are filled through:
- Daily morning and evening sessions
- In-context prompts when the Genie references something and asks for confirmation
- Voluntary vault browsing (user can annotate records at any time)

**Target:** All 4 domains at 50%+ by end of week 2. All 4 domains at 75%+ by end of month 1.

### 6.5 Maturity Tracker

The Genie maintains a 4-domain maturity model. Each domain has 5 signal vectors scored 0–4 (20 points max). Displayed to user as a phase label + percentage. Full spec: `maturity_tracker.md`.

| Domain | Phases (0→100%) |
|--------|----------------|
| **Relationships** (per person) | Stranger → Acquaintance → Known → Close → Understood |
| **Physical Health** | Blank → Signal → Tracked → Active → Optimized |
| **Nutrition** | Dark → Surface → Pattern → Detailed → Calibrated |
| **Exercise** | Cold → Warming → Active → Training → Performing |

Gaps surface conversationally:
> *"I know your training schedule well but I'm almost blind on your nutrition. What did you eat yesterday? Just roughly — I'm building a picture."*

Gap completion is the primary engagement mechanic in month one.

---

### 6.6 Socratic Onboarding — Invited Users

When a new user is invited by an existing user (e.g. Leo invites TJ), the Genie has a head start: third-party signals from the inviting user's sessions, a shared text chain, and structured person_facts about the new user before they've said a word.

This creates a fundamentally different onboarding path — and a powerful one.

**The core principle:** Third-party signals inform question selection, never answer content. The Genie never says what it already knows. It asks questions whose answers it already has, lets the user arrive at the insight themselves, then reflects it back shaped.

This is **Socratic Onboarding**.

---

#### 6.6.1 Why It's Different

A standard new user starts from zero. The Genie knows nothing. Every session is information gathering.

An invited user's Genie starts with:
- The shape of a key relationship (from the inviter's iMessage history)
- Structured facts the inviting Genie surfaced (via `third_party_signals`, abstracted)
- The inviter's stated goals for the relationship
- What the inviting Genie learned the new user is carrying emotionally

The Genie's job is not to recite this. It's to **ask the questions that let the new user say it themselves.**

---

#### 6.6.2 The Three-Act Structure

**Act 1 — Disarm**

The Genie opens by acknowledging the asymmetry transparently without revealing what it knows:

> *"[Name] invited you here, so I already know a little about your world — but only their side of it. I'd rather hear yours.*
>
> *How are you doing right now — honestly? Not the version you'd tell someone who'd worry."*

This does three things: signals the Genie has context, makes clear it wants the user's perspective, and opens with a question that bypasses the social performance layer.

**Act 2 — Draw Out**

The Genie uses the third-party signals to select questions that lead the user toward the topics that matter. It never states what it knows. It asks toward it.

The question-selection logic (see 6.6.4) maps each signal type to a question pattern:

| Signal | Question pattern |
|---|---|
| Financial tension | *"The financial side of things — is that a pressure point right now, or have you found a way to hold it lightly?"* |
| Job uncertainty | *"How's the job search feeling — like something you're in control of, or more like you're waiting for something to land?"* |
| Relationship asymmetry | *"What does it feel like being supported by someone you're that close to? Some people find it straightforward. Others find it sits in a weird way."* |
| Emotional dependency | *"Is there anyone in your life right now who you feel like you can be fully honest with — not managing how they receive it?"* |
| Confidence gap | *"When you walk into an interview, what's the version of yourself you're trying to be? Is it different from the version you actually are?"* |

The user names the tension themselves. The Genie didn't put it there. It just asked the question that made the path visible.

**Act 3 — Reflect and Recommend**

Once the user has surfaced the thing they're carrying, the Genie reflects it back with a concrete shape:

> *"Here's what I think could actually help. When you land — not before, just when you're stable — go back to Leo and say you want to pay back what he's given you during this stretch. Not because he'll ask. Because you'll want to.*
>
> *It won't be about the money for either of you. It'll be about the friendship you're building on the other side of this. Doing it on your terms, before anyone has to ask, is what closes it properly."*

The recommendation carries weight because the user surfaced the discomfort five minutes earlier. The Genie gave it form. They arrived here together.

---

#### 6.6.3 The iMessage Invite (end of first session)

After the first session, once the Genie has demonstrated value with limited data:

> *"I can see the outline of your relationship with [Name] from what they shared when they set this up. But I'm only getting one angle.*
>
> *If you share your messages with me, I can read the actual thread — your side of it, not just theirs. What I suggest will be a lot more specific to you, rather than to the version of you that exists in someone else's story.*
>
> *You don't have to. But it changes what I'm able to do."*

This ask is earned. The user just experienced a session where the Genie was clearly working with incomplete information and was honest about it. Data access is requested after demonstrated value — not at signup.

---

#### 6.6.4 Question Selection Schema

The Genie's question-selection logic is stored and auditable:

```sql
CREATE TABLE socratic_question_templates (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  signal_type       TEXT NOT NULL,
  -- financial_tension | job_uncertainty | relationship_asymmetry
  -- emotional_dependency | confidence_gap | relational_shift
  -- grief | resentment | unresolved_feeling

  question_text     TEXT NOT NULL,
  -- the actual question to ask

  follow_up_text    TEXT,
  -- optional follow-up if user gives a surface answer

  leads_to_domain   TEXT,
  -- relationships | health | finance | self | goals

  intensity         TEXT DEFAULT 'medium',
  -- light | medium | direct
  -- light = safe opener, direct = goes straight to the nerve

  use_after_turn    INTEGER DEFAULT 2,
  -- don't ask in first N turns — let user settle first

  created_at        TIMESTAMPTZ DEFAULT NOW()
);
```

**Selection logic:**
1. At session start, load `third_party_signals` for the invited user
2. Map each signal to matching `signal_type` in question templates
3. Sort by `intensity` — start light, move to direct as trust builds
4. Never ask two questions in the same domain consecutively
5. If user answers a question with genuine depth — don't follow up, let it breathe

---

#### 6.6.5 The Sanitization Guarantee

At no point does TJ's Genie reveal that Leo shared anything. The rules are absolute:

| Forbidden | Permitted |
|---|---|
| *"Leo told me..."* | Questions that lead toward the same topic |
| *"I know Leo thinks..."* | *"How does it feel from your side?"* |
| *"He plans to..."* | Reflecting back what the user just said |
| *"A conversation is coming..."* | Recommendations the user can act on independently |
| Specific figures ($1K, August) unless user states them | Framing shaped by those figures without citing them |

The test: **if you removed all the third-party signals, could this question still have been asked?** If yes, it's safe. If the question only makes sense because of what the other Genie said — it's not.

---

#### 6.6.6 Why This Is the Product's Most Powerful Moment

Standard AI products ask you to fill in forms about yourself. The insight comes later, maybe.

Socratic Onboarding inverts this. The Genie already knows the shape of what matters. It asks you toward it. You say the thing you've been carrying. It gives it form. You feel seen — not because the Genie told you something about yourself, but because it asked exactly the right question.

That first session, for an invited user, is the highest-value moment in the entire product. It's when the user thinks: *"How did it know to ask that?"*

The answer is: it knew. It just didn't say.

---

## 7. Daily Operating Rhythm

### 7.1 Morning Session

**Timing:** User-configured. Default: 7:30am.
**Duration:** 3–7 minutes.
**Tone:** Forward-looking, energising, grounded.

**Structure:**

1. Mood and energy check-in
2. Calendar preview — any significant meetings or events today, Genie asks relevant preparation questions
3. Active skill contributions — e.g. Health Coach asks about planned workout; Budget Coach surfaces any relevant financial note
4. One proactive suggestion — based on overnight processing (music mood, a person to reach out to, a goal reminder)
5. Close — brief, never prolonged

**Persona adaptation:**
- Sentinel: more structured, goal-referenced, holds previous commitments
- Companion: warm, conversational, one or two light questions
- Whisper: minimal — one question or observation only, closes quickly

### 7.2 Evening Session

**Timing:** User-configured. Default: 9:00pm.
**Duration:** 5–10 minutes.
**Tone:** Reflective, non-judgmental, curious.

**Structure:**

1. General mood and energy — how did the day feel overall?
2. Calendar debrief — "You had that investor meeting this afternoon — how did it go?" (references actual calendar, not generic)
3. Active skill contributions — Health Coach asks food, water, workout; Budget Coach asks about any significant spend
4. Relationship signal — "Did you connect with anyone meaningful today?"
5. One open question — something the Genie wants to understand better about the user, rotated to avoid repetition
6. Close — Genie summarises what it's learned tonight, confirms it will process overnight

**Key design principle:** The evening session should feel like a conversation with someone who was with you all day — not a form. Questions reference what the Genie already knows. "You mentioned last week you wanted to sleep earlier — how did that go tonight?"

---

## 8. Wearable Memory Engine

### 8.1 Overview

One press on Apple Watch starts a memory capture session. The Genie records ambient audio, transcribes in 30-second chunks, extracts structured insights, and routes them to the correct vault domains. Audio is deleted after each chunk is processed. By session end, no audio exists — only structured memories.

### 8.2 Watch UI

Three elements only:

- **Large record button** — green when capturing, grey in privacy mode
- **Session type label** — set automatically by Genie (Gym Session · Meeting · In Transit · Medical · Personal)
- **Stop button**

Session type is inferred from: location, calendar, time of day, Apple Health motion data, and recent conversation context. User can override.

### 8.3 Capture Pipeline

```
Audio chunk (30s)
  → On-device transcription (Apple Speech framework)
  → Chunk transcript → LLM insight extraction
  → Structured output → memory_writer.py → vault domains
  → Audio chunk deleted
  → Repeat
```

**Insight extraction prompt structure:**

```
Given this transcript chunk from a [session_type] session,
extract structured insights across these categories:
- People mentioned (match to relationship vault)
- Health/fitness facts (PRs, fatigue notes, trainer observations)
- Preferences revealed (food, activity, plans)
- Goals mentioned
- Memories or events referenced
- Any facts about the user's life worth storing
- Emotional signals (mood, stress, energy)

Return JSON only. Flag confidence for each insight.
```

### 8.4 Privacy Mode

Press and hold Watch crown → Privacy Mode activated.
- No audio captured
- No insights extracted
- Genie goes silent
- Visual indicator: grey pulsing ring (vs green when active)
- Toggle off with same gesture

### 8.5 End-of-Session Summary

After stopping capture, the Genie presents a brief summary:

> "Here's what I captured from your training session: new deadlift PR at 140kg, your trainer noted left shoulder fatigue, you mentioned wanting to focus on legs next week. Should I store all of this?"

User confirms, edits, or deletes individual items before anything is written to the vault.

### 8.6 Skill Integration

If a skill is active, the capture session is tagged to that skill. The Health Coach skill, for example, receives gym session captures and uses them to update its coaching model. The user does not need to do anything — the tagging is automatic based on session type.

---

## 9. Overnight Processing Engine

### 9.1 Overview

Every night, the Genie runs a full processing pass across the Personal Vault. No latency pressure — this job can be computationally expensive. It runs while the device charges, typically 2am–4am.

### 9.2 Processing Jobs

**Memory Consolidation**
- Deduplicates redundant records
- Upgrades inferred records to confirmed where multiple sources agree
- Archives stale records (low confidence, no recent reinforcement)

**Preference Drift Detection**
- Compares recent behaviour signals against stored preferences
- Flags where behaviour consistently diverges from stored preference
- Proposes preference updates to surface to user next morning

**Phase Detection**
- Analyses mood logs, energy levels, activity patterns, message sentiment over trailing 14–30 days
- Detects significant life phase shifts (e.g. stressed → energetic, sedentary → active)
- Updates phase labels in preference_phases table
- Adjusts active skill behaviours for new phase

**Relationship Signal Processing**
- Updates last_contact timestamps
- Calculates contact frequency drift (e.g. was weekly, now monthly)
- Flags relationships that may need attention based on user's stated goals for them

**Skill State Updates**
- Each active skill runs its own overnight job within the engine
- Health Coach: recalculates weekly workout completion, updates phase, refreshes trainer note context
- Budget Coach: tallies monthly spend by category, calculates budget proximity

**Rule Refinement**
- Reviews reasoning traces where user corrected or ignored Genie suggestions
- Updates inference rules to reduce future errors of that type
- Logs rule changes with rationale in reasoning_traces

**Morning Preparation**
- Assembles morning session content based on all overnight findings
- Selects the one most relevant proactive suggestion
- Prepares calendar-aware questions for the day ahead

---

## 10. Genie Personas

### 10.1 Overview

At onboarding, the user selects a starting persona. The persona controls the Genie's communication style, check-in frequency, coaching intensity, and proactivity level across all sessions and skills. The persona evolves over time — the Genie detects when the user's behaviour is misaligned with their chosen persona and proposes adjustments.

### 10.2 The Three Personas

#### Sentinel — Aggressive

> *"You said this mattered to you. Does it still?"*

- Daily check-ins enforced — morning and evening sessions are non-optional nudges
- Holds previous commitments explicitly ("Yesterday you said you'd work out — did you?")
- Goal references frequent across all sessions
- Skills run in maximum coaching intensity
- Phase-aware preference reminders on shortest cycle (daily by default)
- Surfaces reasoning traces proactively — shows its work unprompted

**Best for:** Users building new habits, accountability-seekers, high-performers wanting structured support

#### Companion — Moderate

> *"I noticed something. Want to talk about it?"*

- Daily sessions present but conversational, not evaluative
- References goals naturally without scorekeeping
- Celebrates progress, reflects patterns without judgment
- Skills at moderate coaching intensity
- Surfaces suggestions when confidence is high, not on a fixed schedule
- Persona that most users drift toward over time

**Best for:** Users wanting consistent presence without pressure, relationship-focused, balanced

#### Whisper — Ambient

> *"One thing, then I'll leave you to it."*

- Sessions are brief and optional — one question or observation, closes fast
- Does not reference goals unless user raises them
- Skills in ambient mode only unless user explicitly activates
- Surfaces suggestions rarely — only when highly confident and highly relevant
- Maximum privacy feel — the Genie is present but never intrusive

**Best for:** Autonomy-valuing users, those sensitive to being managed, privacy-first personalities

### 10.3 Persona Drift Detection

The overnight engine monitors alignment between chosen persona and user behaviour:

- Sentinel user consistently skipping sessions → surfaces after 7 days: "You've been missing our evening check-ins. Want to try Companion for a while?"
- Whisper user consistently engaging deeply and asking follow-ups → surfaces after 14 days: "You've been engaging a lot more — would Companion feel right?"

Persona changes require user confirmation. History of persona changes is logged.

---

## 11. Genie-to-Genie Protocol

### 11.1 Overview

Two Genies can create shared moments — a perfect dinner suggestion, a thoughtful gift, a planned call — without either person's private vault data being shared with the other. The Genies negotiate via structured signals. Raw data never crosses the pairing boundary.

**Core promise:** *Your Genie and their Genie can create magic together. Neither of them tells the other your secrets.*

### 11.2 Consent Pairing

Pairing is explicit, bilateral, and revocable:

1. User A sends pairing invitation with proposed relationship type
2. User B receives invitation, reviews what signals will be shared (category-level, never raw data), confirms
3. Pairing is established — encrypted pairing key stored locally on both devices
4. Either party can unpair at any time — connection severs immediately, no residual data

**Pairing types and signal permissions:**

| Type | Signals Permitted |
|---|---|
| Partner | Mood, openness to social plans, love language signals, shared preference outputs |
| Family | Shared memories, logistical signals, milestone awareness |
| Friend | Shared experience suggestions, availability signals |
| Co-parent | Logistics, child-related scheduling signals only |

### 11.3 Negotiation Layer

Genies communicate via structured yes/no queries — never raw data:

```json
{
  "query_type": "openness_check",
  "context": "spontaneous_evening_out",
  "timeframe": "tonight",
  "from_genie": "genie_uuid_A"
}
```

Response:
```json
{
  "response": "yes",
  "suggested_context": "prefers_low_key",
  "from_genie": "genie_uuid_B"
}
```

No names, no facts, no memories transmitted. Signal vocabulary is fixed and defined at the protocol level.

### 11.4 Moment Engine

When both Genies have sufficient signal, the Moment Engine generates a shared suggestion — a restaurant, an activity, a date, a gift — using both Genies' preference outputs without either seeing the other's raw preferences.

Each person receives a suggestion that feels perfectly calibrated to them. Neither knows exactly what the other's Genie contributed.

---

### 11.5 Network Signal Intelligence

Beyond bilateral pairs, the Genie aggregates signals about a person from every node in the network that has mentioned them — with permission. This is the product's core network effect: **the more people in your orbit on PersonalGenie, the smarter your Genie becomes about the people you share.**

**The example:**
- Anjali (sister-in-law) has a conversation with her niece Jiya
- Anjali's Genie extracts a signal: *"Jiya has an upcoming date she's excited about"*
- Leo (Jiya's uncle) is connected to Anjali in the permission graph
- Leo's Genie wants to surface a moment: Leo checking in on Jiya
- Before surfacing anything, Leo's Genie requests Anjali's consent
- Anjali says yes → Leo gets a specific, human suggestion he couldn't have generated alone

**What Leo's Genie surfaces (after consent):**

> *"Your niece Jiya has something exciting coming up — sounds like a date she's been looking forward to. You haven't really talked with her about that side of her life before. As her gay uncle, you might be exactly the person she'd want to talk to — probably easier than her parents. She's studying abroad, navigating all of this far from home. Worth reaching out."*

Four separate data points — signal from Anjali, Leo's relationship to Jiya, Leo's personal attributes, interaction history — synthesised into one specific, emotionally intelligent suggestion. None of those sources could have produced it alone.

---

### 11.6 Consent-on-Demand Protocol

Network signals about third parties require **explicit, in-context consent from the signal source before they can be used**. This is not a blanket permission set at onboarding. It is a specific ask, at the moment of use, for the specific thing being shared.

#### The Flow

```
Step 1 — Signal extracted, quarantined
  Anjali's Genie extracts signal about Jiya from their conversation.
  Signal stored in third_party_signals with status: PENDING_CONSENT.
  Signal cannot flow to any other Genie until consent is granted.

Step 2 — Consent request generated
  Leo's Genie identifies the signal and wants to use it.
  Generates a consent_request to Anjali's Genie:
  {
    "requesting_genie": Leo's Genie,
    "about_person": Jiya,
    "beneficiary": Leo,
    "proposed_share": "Jiya has an upcoming date she's excited about",
    "purpose": "suggest Leo check in with Jiya",
    "expires_at": 7 days
  }

Step 3 — Anjali's Genie asks Anjali
  Conversationally, at her next natural session or via WhatsApp:
  "Leo's Genie picked up that Jiya has something exciting coming up
   and thinks it might be a nice moment for Leo to reach out.
   I'd share that she has a date she's been looking forward to —
   nothing more specific than that. Want me to pass it along?"

Step 4a — Anjali says YES
  → signal_consent_requests.status = GRANTED
  → third_party_signals.consent_status = GRANTED
  → audit log entry written (immutable)
  → Leo's Genie surfaces the moment
  → Leo never knows a consent request happened

Step 4b — Anjali says NO
  → signal_consent_requests.status = DENIED
  → signal is permanently blocked for this use
  → Leo's Genie drops the moment entirely
  → Leo never knows the signal existed
  → Anjali's denial is logged in her own transparency view only
```

#### What Anjali Sees

The consent ask shows Anjali **exactly** what would be shared — the abstracted signal, not the raw conversation. She is never asked to approve a vague category. She approves a specific sentence.

She can also respond with nuance:
- *"Yes, share it"* → full signal flows
- *"Yes, but just say she's doing well — not the dating part"* → Anjali's Genie modifies the signal before release
- *"No"* → signal blocked permanently for this request
- *"Not yet — ask me again in a week"* → request snoozed, re-asked at Anjali's next session

#### The Audit Trail

Every consent decision is immutable and permanently logged:

```sql
CREATE TABLE signal_consent_requests (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  signal_id             UUID NOT NULL REFERENCES third_party_signals(id),
  requesting_user_id    UUID NOT NULL REFERENCES users(id),
  -- whose Genie wants to use the signal (Leo)
  granting_user_id      UUID NOT NULL REFERENCES users(id),
  -- whose Genie extracted the signal (Anjali)
  about_person_id       UUID REFERENCES people(id),
  -- who the signal is about (Jiya)
  beneficiary_user_id   UUID NOT NULL REFERENCES users(id),
  -- who would receive the surfaced moment (Leo)

  proposed_share_text   TEXT NOT NULL,
  -- exactly what would be shared — shown to Anjali verbatim

  purpose_text          TEXT NOT NULL,
  -- why — shown to Anjali: "suggest Leo check in with Jiya"

  status                TEXT NOT NULL DEFAULT 'pending',
  -- pending | granted | denied | snoozed | expired | modified

  modified_share_text   TEXT,
  -- if Anjali approved but with edits — what actually flows

  requested_at          TIMESTAMPTZ DEFAULT NOW(),
  responded_at          TIMESTAMPTZ,
  expires_at            TIMESTAMPTZ NOT NULL,
  -- signal expires if Anjali doesn't respond — moment never surfaces

  granting_user_note    TEXT
  -- optional: Anjali's own note about her decision
);

-- Immutable audit log — append only, never updated
CREATE TABLE signal_consent_audit_log (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  consent_request_id UUID NOT NULL REFERENCES signal_consent_requests(id),
  event_type        TEXT NOT NULL,
  -- requested | granted | denied | snoozed | expired | modified | used | revoked
  actor_user_id     UUID NOT NULL REFERENCES users(id),
  event_detail      TEXT,
  -- human-readable: "Anjali granted permission to share date signal with Leo"
  created_at        TIMESTAMPTZ DEFAULT NOW()
  -- NO updated_at — this table is append-only
);
```

#### Three Guarantees

**1. Leo never knows if Anjali said no.**
The moment simply never surfaces. There is no *"your contact declined to share."* The signal disappears silently.

**2. Anjali always knows what she approved.**
Her transparency view shows every consent she has granted or denied, the exact text that was shared, and when it was used. She can revoke at any time — which removes the signal from Leo's Genie going forward, though it cannot un-surface a moment already delivered.

**3. The signal never flows without an audit trail.**
Every use of a network signal has a corresponding `signal_consent_audit_log` entry. If Anjali ever asks *"what have you shared about Jiya with others?"* — her Genie can answer completely and accurately.

---

### 11.7 Network Intelligence Permissions Model

**One hop (launch):** Signals only flow between directly connected nodes. Anjali must have a direct permission relationship with Leo. This is auditable and understandable.

**Two hops (Phase 2):** A signal from Anjali about Jiya flows to Leo at full confidence. A signal from Anjali's friend about Jiya flows to Leo at 0.5 confidence, with softer language. The Genie surfaces lower-confidence signals with appropriate hedging: *"I've heard through the network that Jiya might have something exciting going on..."*

**The about-person opt-out:** Jiya (if she joins PersonalGenie) can set her signal permission to level 0 — which stops signals about her propagating to anyone in the network, regardless of what others have extracted. Her signal sovereignty is absolute.

---

## 12. Social Onboarding & Network Effects

### 12.1 Cold Start Problem

New users who join with no data sources connected start with a thin brain-state. The Genie knows little, the morning reveal is generic, the magic takes longer to arrive.

Social onboarding solves this by leveraging the relationship graph of existing users.

### 12.2 How It Works

When User A invites User B (e.g. a sibling):

1. User A's Genie identifies what it knows about User B from its own vault — relationship record, shared memories, inferred personality signals, relevant context
2. This is distilled into a **shared context contribution** — structured data about User B as seen through User A's lens. Never User A's private data. Only the intersection of their shared lives.
3. Shared context contribution is encrypted and delivered to User B's onboarding Genie
4. User B's Genie ingests this contribution alongside their own data sources
5. User B's first morning reveal is personalised — it already knows things that are true about them

**Example shared context contribution from sibling A to sibling B:**

```json
{
  "relationship_to_inviter": "sibling",
  "shared_memories": ["family holidays", "specific cities visited together"],
  "personality_signals": ["close family unit", "regular contact pattern"],
  "family_context": ["parents' names", "shared family dynamics inferred from message patterns"]
}
```

### 12.3 Network Compounding

The more PersonalGenie users in a person's circle, the richer their onboarding and the faster their brain-state matures. This creates genuine network value without requiring a social graph or public data — it compounds through private, bilateral relationships.

A family of five on PersonalGenie produces a deeply interconnected web of shared context. Each person's Genie is private and sovereign. But the family collective has accumulated shared context that makes every individual Genie more accurate, more personal, and more magical.

---

## 13. Privacy Architecture

### 13.1 Core Principle

Privacy is not a policy. It is the architecture.

All personal data is stored locally on the user's device. No raw data leaves the device under any circumstances. The Genie-to-Genie protocol transmits only structured signals — never raw facts, memories, or preferences. Skill modules receive persona-scoped subsets only — never raw vault access.

### 13.2 Local-First Stack

| Layer | Implementation |
|---|---|
| **Vault storage** | SQLite on-device, encrypted with AES-256 |
| **Vault encryption key** | Stored in iOS Secure Enclave |
| **Cross-device sync** | CloudKit with client-side encryption — server sees only ciphertext |
| **Inference** | On-device (Core ML / MLX) preferred; cloud hybrid for complex reasoning |
| **Cloud inference** | Session Persona only — compressed, no raw vault data. HTTPS with certificate pinning |
| **Genie-to-Genie** | End-to-end encrypted signal exchange — structured signals only |
| **Audio capture** | On-device transcription (Apple Speech) — audio never leaves device, deleted per chunk |
| **Skill data** | Namespaced in vault — skill receives scoped persona, not raw domain tables |

### 13.3 User Control

The user has complete, unmediated control over their vault:

- **Transparency view:** browse every record in the vault, see its source, confidence, and any reasoning traces that reference it
- **Correction:** edit any record at any time
- **Deletion:** delete any individual record or entire domains
- **Export:** export full vault as JSON at any time
- **Audit log:** see every action the Genie has taken and why
- **Skill permissions:** view and revoke each skill's read/write permissions independently
- **Genie pairings:** view all active pairings, see what signal types are enabled, unpair instantly

### 13.4 Network Signal Privacy Guarantees

Third-party network signals (Section 11.5–11.7) are subject to additional privacy rules beyond the core architecture:

| Guarantee | Implementation |
|---|---|
| **No signal flows without explicit consent** | All third_party_signals start with status PENDING_CONSENT. Cannot be used until granting_user approves. |
| **Consent is specific, not blanket** | Every consent request shows the exact abstracted text that would be shared. No categorical approvals. |
| **The about-person is never identifiable from the signal** | signal_abstract contains structured facts only — no names, no verbatim quotes, no identifying details beyond what the beneficiary already knows |
| **Denial is invisible to the requester** | If Anjali says no, Leo's moment never surfaces. Leo receives no indication a signal existed. |
| **Audit trail is immutable** | signal_consent_audit_log is append-only. Every consent decision is permanently recorded. |
| **The about-person can opt out** | If Jiya joins PersonalGenie, she can set signal permission = 0 and stop all signals about her propagating across the network — regardless of what others have extracted. |
| **Consent can be revoked** | Anjali can revoke a granted consent at any time. Removes the signal going forward; cannot un-surface moments already delivered. |

### 13.5 What We Never Do

- Store raw audio beyond the 30-second processing window
- Send raw vault data to any cloud service
- Share user data between users' accounts (only structured signals via Genie protocol)
- Use personal data to train models
- Sell or licence any user data
- Allow skills to access vault domains outside their declared scope
- Use a network signal without documented consent from its source
- Surface a moment to User A based on a signal User B denied sharing
- Tell User A that User B declined to share a signal about a third party

---

## 14. Session Persona Assembly

The Session Persona is a compressed, runtime object assembled fresh at the start of every session. It is the context the Genie loads — not the raw vault, which is too large and too sensitive to pass wholesale into inference.

### 14.1 Assembly Logic

```python
def assemble_session_persona(user_id, session_type, active_skills):
    persona = {
        "identity_core": vault.get_confirmed_identity(user_id),
        "top_relationships": vault.get_relationships(user_id, tier=[1,2], limit=10),
        "active_goals": vault.get_goals(user_id, status="active"),
        "hard_preferences": vault.get_preferences(user_id, type="hard"),
        "soft_preferences": vault.get_preferences(user_id, type="soft", confidence_min=0.7),
        "current_phase": vault.get_current_phase(user_id),
        "persona_mode": vault.get_persona_mode(user_id),
        "recent_mood": vault.get_mood_log(user_id, days=7),
        "recent_reasoning": vault.get_reasoning_traces(user_id, limit=20),
        "skill_personas": {
            skill_id: skills[skill_id].get_scoped_persona(user_id)
            for skill_id in active_skills
        },
        "session_context": {
            "type": session_type,
            "calendar_today": calendar.get_today(user_id),
            "overnight_findings": overnight_engine.get_latest_findings(user_id)
        }
    }
    return persona
```

### 14.2 Persona Size Management

The assembled persona must fit within the inference model's context window while leaving room for the conversation. Target: 4,000–8,000 tokens for persona, depending on session type. Assembly logic prioritises:

1. Confirmed records over inferred
2. High-confidence over low-confidence
3. Recently updated over stale
4. Relevant to session type over general

---

## 15. Data Ingestion Sources

### 15.1 iMessage (Mac)

- **Access:** Direct SQLite access to `~/Library/Messages/chat.db`
- **Requires:** Mac app, user permission, Full Disk Access grant
- **Extracts:** Relationship signals, emotional sentiment, preferences revealed in conversation, shared memories, recurring topics, personality patterns
- **Privacy:** Processed locally, never transmitted. Original database untouched (read-only).

### 15.2 WhatsApp

- **Access:** User exports specific chats (Settings → Chat → Export Chat) and imports via drag-and-drop or share sheet
- **Extracts:** Same as iMessage — relationship signals, preferences, memories, sentiment
- **Roadmap:** Direct integration via Mac WhatsApp app file access

### 15.3 Gmail

- **Access:** OAuth 2.0, read-only scope
- **Extracts:** Travel bookings, restaurant receipts, subscription services, key contacts, financial signals, health appointments
- **Privacy:** Email bodies processed locally after OAuth fetch. Metadata only transmitted for index building.

### 15.4 Google Photos

- **Access:** OAuth 2.0, metadata and captions only — no raw image transfer to vault
- **Extracts:** Travel history (location metadata), people present (from captions/tags), memorable events
- **Privacy:** Images never stored in vault. Only structured metadata extracted.

### 15.5 Apple Contacts

- **Access:** ContactsKit framework, user permission
- **Extracts:** Seeds relationship graph with names, roles, contact frequency

### 15.6 Apple Calendar

- **Access:** EventKit framework, user permission
- **Extracts:** Regular commitments, recurring meetings, travel patterns, key people in professional life

### 15.7 Apple Health

- **Access:** HealthKit framework, user permission
- **Extracts:** Sleep patterns, activity levels, workout history, weight trends, heart rate patterns

### 15.8 Wearable Capture

- **Access:** Apple Watch microphone, WatchKit
- **Extracts:** Per-session structured insights — see Section 8

---

## 16. Functional Requirements

### 16.1 Onboarding

| ID | Requirement | Priority |
|---|---|---|
| FR-01 | Support iMessage ingestion via Mac Messages.db (read-only) | Must Have |
| FR-02 | Support WhatsApp export import (drag-and-drop) | Must Have |
| FR-03 | Support Gmail OAuth read-only ingestion | Must Have |
| FR-04 | Support Apple Contacts, Calendar, Health ingestion | Must Have |
| FR-05 | Run overnight processing job on completion of ingestion | Must Have |
| FR-06 | Deliver personalised morning reveal on Day 1 | Must Have |
| FR-07 | Allow user to confirm, correct, or skip each reveal item | Must Have |
| FR-08 | Present three personas with concrete examples, capture selection | Must Have |
| FR-09 | Support Google Photos metadata ingestion | Should Have |

### 16.2 Daily Sessions

| ID | Requirement | Priority |
|---|---|---|
| FR-10 | Morning session with mood, calendar, skill contributions, one suggestion | Must Have |
| FR-11 | Evening session with debrief, skill contributions, open question | Must Have |
| FR-12 | Sessions reference known calendar events by name | Must Have |
| FR-13 | Sessions adapt tone and depth to active persona mode | Must Have |
| FR-14 | Sessions never repeat the same question within 7 days | Should Have |
| FR-15 | User can skip or shorten any session | Must Have |

### 16.3 Wearable Capture

| ID | Requirement | Priority |
|---|---|---|
| FR-16 | One-press capture start on Apple Watch | Must Have |
| FR-17 | 30-second chunk transcription via on-device Apple Speech | Must Have |
| FR-18 | LLM insight extraction per chunk | Must Have |
| FR-19 | Audio deleted after each chunk is processed | Must Have |
| FR-20 | Session type auto-detected from context | Must Have |
| FR-21 | End-of-session summary with user confirmation before vault write | Must Have |
| FR-22 | Privacy mode via press-and-hold gesture | Must Have |
| FR-23 | Skill tagging of capture sessions | Should Have |

### 16.4 Skills Platform

| ID | Requirement | Priority |
|---|---|---|
| FR-24 | Skill registry with install, activate, pause, remove | Must Have |
| FR-25 | Ambient and active mode per skill | Must Have |
| FR-26 | Skill-scoped persona assembly (no raw vault access) | Must Have |
| FR-27 | Skill state namespaced tables per skill | Must Have |
| FR-28 | Skill contributions to morning and evening sessions | Must Have |
| FR-29 | Skill preferences (hard/soft) with phase overrides | Must Have |
| FR-30 | Skill reasoning traces | Must Have |
| FR-31 | Health Coach skill — V1 | Must Have |
| FR-32 | Budget Coach skill — V1 | Must Have |

### 16.4A Skill Sub-Brain

| ID | Requirement | Priority |
|---|---|---|
| FR-33A | User can configure skill logic in plain language — skill formalises into executable rules | Must Have |
| FR-33B | Rule graph with trigger, condition, action, cadence per rule | Must Have |
| FR-33C | User confirmation required before any rule activates | Must Have |
| FR-33D | Skill proposes new rules autonomously based on observed patterns | Must Have |
| FR-33E | User can view, edit, pause, or delete any rule at any time | Must Have |
| FR-33F | Every rule execution logged in skill reasoning traces with vault references | Must Have |
| FR-33G | Output preferences configurable per skill — format, tone, frequency, depth | Must Have |
| FR-33H | Skill integration layer — per-skill external data source connections | Must Have |
| FR-33I | Plaid integration for Budget Coach (OAuth, read-only, transaction sync) | Must Have |
| FR-33J | Receipt capture and on-device parsing for Budget Coach | Must Have |
| FR-33K | Sub-Brain transparency view — rule graph, execution log, integration status | Must Have |
| FR-33L | Self-proposed rules never execute without explicit user confirmation | Must Have |

### 16.5 Genie-to-Genie

| ID | Requirement | Priority |
|---|---|---|
| FR-33 | Bilateral consent pairing with relationship type | Must Have |
| FR-34 | Structured signal exchange only — no raw data | Must Have |
| FR-35 | Moment Engine for shared experience suggestions | Should Have |
| FR-36 | Social onboarding shared context contribution | Should Have |
| FR-37 | Instant unpair with full connection severance | Must Have |

### 16.6 Privacy & Transparency

| ID | Requirement | Priority |
|---|---|---|
| FR-38 | Full vault transparency view — browse all records | Must Have |
| FR-39 | Per-record correction and deletion | Must Have |
| FR-40 | Full vault export as JSON | Must Have |
| FR-41 | Reasoning trace view — see why Genie did anything | Must Have |
| FR-42 | Skill permission view and revocation | Must Have |
| FR-43 | Vault encryption with Secure Enclave key | Must Have |

---

## 17. Non-Functional Requirements

| ID | Requirement | Description | Priority |
|---|---|---|---|
| NFR-01 | **Local-first** | All personal data stored on device. No raw data to cloud. | Must Have |
| NFR-02 | **Session latency** | Session response under 2 seconds for on-device inference; under 4 seconds for cloud hybrid | Must Have |
| NFR-03 | **Overnight job** | Completes full processing pass within 2-hour window on device charge | Must Have |
| NFR-04 | **Capture reliability** | Zero audio chunk loss — retry on failure before deletion | Must Have |
| NFR-05 | **Vault scale** | Supports 5 years of daily logging without lookup degradation | Should Have |
| NFR-06 | **Persona size** | Session Persona assembly under 8,000 tokens for any session type | Must Have |
| NFR-07 | **Battery** | Overnight engine and capture pipeline do not degrade battery life measurably in daily use | Should Have |
| NFR-08 | **Cross-device sync** | Vault syncs across user's Apple devices via CloudKit client-side encryption | Should Have |
| NFR-09 | **App Store compliance** | Microphone, Health, Contacts, Calendar usage strings accurate and minimal | Must Have |

---

## 18. Tech Stack

| Layer | Technology |
|---|---|
| **Platform** | iOS 17+ · watchOS 10+ · macOS 14+ |
| **Language** | Swift (app) · Python (backend processing, overnight engine, ingestion) |
| **On-device inference** | Core ML · MLX (Apple Silicon) |
| **Cloud inference** | Anthropic Claude API (Session Persona as context, no raw vault data) |
| **Vault storage** | SQLite via GRDB (Swift) · Encrypted with CryptoKit |
| **Encryption** | AES-256-GCM · Key in Secure Enclave |
| **Cross-device sync** | CloudKit (CKAsset with client-side encryption) |
| **Audio transcription** | Apple Speech framework (on-device, SFSpeechRecognizer) |
| **iMessage ingestion** | Read-only SQLite access to Messages.db (Mac) |
| **Gmail ingestion** | Google OAuth 2.0 · Gmail API read-only scope |
| **Health ingestion** | HealthKit (iOS) |
| **Calendar ingestion** | EventKit (iOS/Mac) |
| **Contacts ingestion** | ContactsKit (iOS/Mac) |
| **Watch app** | WatchKit · AVFoundation (microphone) |
| **Genie protocol** | CloudKit private database (encrypted signals only) |
| **Skill Sub-Brain** | `skill_rules_{id}` SQLite tables · Rule execution engine in Python · Output preference renderer |
| **Plaid integration** | Plaid Link SDK (iOS) · Plaid API (transactions, read-only) |
| **Receipt parsing** | Apple Vision framework (on-device OCR) · LLM field extraction |

---

## 19. Build Milestones

| Phase | Name | Deliverable | Est. |
|---|---|---|---|
| **P1** | **Vault Foundation** | SQLite schema all 8 domains, GRDB integration, encryption, basic CRUD, transparency view shell | 3 days |
| **P2** | **Ingestion Pipeline** | iMessage parser, WhatsApp import, Gmail OAuth, Contacts/Calendar/Health ingestion, memory_writer routing | 5 days |
| **P3** | **Overnight Engine** | Memory consolidation, preference drift detection, phase detection, relationship signals, morning prep | 4 days |
| **P4** | **Session Persona** | Assembly logic, context window management, persona mode integration | 2 days |
| **P5** | **Daily Sessions** | Morning and evening session flows, calendar integration, persona adaptation, skill contribution hooks | 4 days |
| **P6** | **Onboarding** | Data intake flow, overnight build trigger, morning reveal, persona selection | 3 days |
| **P7** | **Wearable Capture** | Watch app, 30s chunk pipeline, on-device transcription, insight extraction, end-of-session summary | 4 days |
| **P8** | **Skills Platform** | Skill registry, skill schema, scoped persona assembly, ambient/active toggle, skill session integration | 4 days |
| **P8A** | **Skill Sub-Brain** | Rule graph schema, rule execution engine, user-facing rule configuration flow, output preferences, integration layer, transparency view | 5 days |
| **P9** | **Health Coach Skill** | Full Health Coach implementation — ambient, active, coaching logic, state table, HealthKit integration | 3 days |
| **P10** | **Budget Coach Skill** | Full Budget Coach — Sub-Brain rules, Plaid integration, receipt capture/parsing, Apple Wallet, weekly summary engine | 5 days |
| **P11** | **Genie Protocol** | Pairing flow, signal exchange, Moment Engine, social onboarding contribution | 5 days |
| **P12** | **Integration & Polish** | End-to-end testing, edge cases, performance, battery profiling, App Store prep | 4 days |

**Total estimated build: ~51 engineering days**

---

## 20. Post-MVP Roadmap

### Phase 2 — Deeper Intelligence
- Sleep Coach skill
- Relationship Coach skill (proactive relationship maintenance)
- Travel Planner skill
- Improved on-device inference (reduce cloud dependency)

### Phase 3 — Platform Expansion
- Third-party skill SDK (external developers can build skills)
- Android support
- Web transparency dashboard (read-only vault view on desktop)

### Phase 4 — Ambient Expansion
- Smart home integration via same voice loop (lights, music, thermostat)
- Apple TV control (FamilyGenie integration)
- Proactive ambient suggestions without session (Whisper mode evolution)

### Phase 5 — Family & Social
- Family Genie mode — shared household context layer
- Child-safe skill set
- Co-Genie for couples (deeper Genie-to-Genie integration)

---

*— End of Document — PersonalGenie PRD v9.1 — March 2026*
