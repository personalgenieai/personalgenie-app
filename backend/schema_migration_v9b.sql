-- ============================================================
-- PersonalGenie — Schema Migration v9b
-- Person Facts + Recommendations with Reasoning Chain
-- 2026-03-10
-- ============================================================

-- ------------------------------------------------------------
-- person_facts
-- Structured, queryable facts about a specific person in the
-- user's life. Different from memories (episodic) and from
-- relationship_signals (behavioral events). These are stable
-- facts the Genie has confirmed or inferred:
--   "TJ receives $1K/month support"
--   "TJ's support ends August 2026"
--   "TJ is applying to jobs independently"
--   "Malakani is based in Hawaii"
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS person_facts (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    person_id           UUID REFERENCES people(id) ON DELETE CASCADE,
    -- NULL person_id = fact about the owner themselves

    fact_key            TEXT NOT NULL,
    -- e.g. "monthly_support_amount" | "support_end_date"
    --      "job_search_status" | "sobriety_status" | "base_city"
    --      "relationship_goal" | "communication_style"

    fact_value          TEXT NOT NULL,
    -- always stored as text; cast by consumer based on fact_type

    fact_type           TEXT NOT NULL DEFAULT 'text',
    -- text | number | date | boolean | json

    domain              TEXT,
    -- relationships | health | finance | logistics | preferences | goals

    confidence          FLOAT NOT NULL DEFAULT 1.0,
    -- 0.0–1.0: 1.0 = user_stated, 0.7 = genie_inferred, 0.5 = from_messages

    source              TEXT NOT NULL DEFAULT 'user_stated',
    -- user_stated | genie_inferred | imessage_analysis | session | gmail_analysis

    expires_at          TIMESTAMPTZ,
    -- NULL = permanent. Use for time-bounded facts.
    -- e.g. "support_end_date" expires after August 2026

    user_confirmed      BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(owner_user_id, person_id, fact_key)
    -- one canonical value per fact per person
    -- update in place rather than append
);

-- ------------------------------------------------------------
-- recommendations
-- Specific, actionable recommendations the Genie has surfaced,
-- with the full reasoning chain stored so the Genie can explain
-- itself later. Includes optional script (exact words to use).
--
-- The reasoning_chain JSONB field stores:
--   observations:        what the Genie saw in the data
--   pattern_identified:  the named behavioral pattern
--   goal:                what the user wants from this domain
--   why_this_approach:   rationale for this recommendation
--   why_this_framing:    rationale for the specific language
--   what_not_to_do:      explicit anti-patterns to avoid
--   fact_refs:           person_fact ids used as inputs
--   memory_refs:         moment ids referenced in reasoning
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS recommendations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    person_id           UUID REFERENCES people(id) ON DELETE CASCADE,
    -- NULL = recommendation about the user themselves

    title               TEXT NOT NULL,
    -- short label: "The TJ Financial Bridge Conversation"

    recommendation_text TEXT NOT NULL,
    -- plain language summary of what to do

    script              TEXT,
    -- optional: exact words to say, verbatim

    timing              TEXT,
    -- right_now | this_week | plan_ahead | when_ready

    domain              TEXT,
    -- relationships | health | finance | exercise | nutrition | self

    status              TEXT NOT NULL DEFAULT 'pending',
    -- pending | delivered | acted_on | dismissed | snoozed | expired

    reasoning_chain     JSONB NOT NULL DEFAULT '{}',
    -- full reasoning chain — see shape above

    delivered_at        TIMESTAMPTZ,
    -- when the Genie surfaced this to the user

    user_response       TEXT,
    -- what the user said after receiving it (free text)

    outcome             TEXT,
    -- acted_on | dismissed | modified | deferred | pending

    outcome_notes       TEXT,
    -- optional: what actually happened / user correction

    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ------------------------------------------------------------
-- Row Level Security
-- ------------------------------------------------------------
ALTER TABLE person_facts ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can manage own person_facts"
    ON person_facts FOR ALL
    USING (auth.uid() = owner_user_id);

ALTER TABLE recommendations ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can manage own recommendations"
    ON recommendations FOR ALL
    USING (auth.uid() = owner_user_id);

-- ------------------------------------------------------------
-- Indexes
-- ------------------------------------------------------------
CREATE INDEX idx_person_facts_person
    ON person_facts(person_id);
CREATE INDEX idx_person_facts_lookup
    ON person_facts(owner_user_id, fact_key);
CREATE INDEX idx_person_facts_domain
    ON person_facts(owner_user_id, domain);
CREATE INDEX idx_person_facts_expires
    ON person_facts(expires_at)
    WHERE expires_at IS NOT NULL;

CREATE INDEX idx_recommendations_person
    ON recommendations(person_id);
CREATE INDEX idx_recommendations_status
    ON recommendations(owner_user_id, status);
CREATE INDEX idx_recommendations_domain
    ON recommendations(owner_user_id, domain);
CREATE INDEX idx_recommendations_timing
    ON recommendations(owner_user_id, timing, status);

-- ------------------------------------------------------------
-- socratic_question_templates
-- Question bank for Socratic Onboarding (Section 6.6).
-- Maps third_party signal types to questions that lead the
-- invited user toward the topic without revealing the source.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS socratic_question_templates (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    signal_type         TEXT NOT NULL,
    -- financial_tension | job_uncertainty | relationship_asymmetry
    -- emotional_dependency | confidence_gap | relational_shift
    -- grief | resentment | unresolved_feeling

    question_text       TEXT NOT NULL,
    -- the actual question to ask

    follow_up_text      TEXT,
    -- optional follow-up if user gives a surface answer

    leads_to_domain     TEXT,
    -- relationships | health | finance | self | goals

    intensity           TEXT NOT NULL DEFAULT 'medium',
    -- light = safe opener | medium = goes a layer deeper | direct = straight to the nerve

    use_after_turn      INTEGER DEFAULT 2,
    -- don't ask before this turn number — let user settle first

    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Seed: question bank
INSERT INTO socratic_question_templates
    (signal_type, question_text, follow_up_text, leads_to_domain, intensity, use_after_turn)
VALUES
-- financial_tension
('financial_tension',
 'The financial side of things — is that a pressure point right now, or have you found a way to hold it lightly?',
 'What does that feel like day to day?',
 'finance', 'medium', 2),

('financial_tension',
 'When you think about where you want to be financially in six months — what does stable actually look like for you?',
 NULL,
 'finance', 'light', 1),

-- job_uncertainty
('job_uncertainty',
 'How''s the job search feeling — like something you''re in control of, or more like you''re waiting for something to land?',
 'What''s the hardest part of it right now?',
 'goals', 'medium', 2),

('job_uncertainty',
 'When you walk into an interview, what''s the version of yourself you''re trying to be? Is it different from the version you actually are?',
 NULL,
 'self', 'direct', 3),

-- relationship_asymmetry
('relationship_asymmetry',
 'What does it feel like being supported by someone you''re that close to? Some people find it straightforward. Others find it sits in a weird way.',
 'Do you ever think about what it looks like from their side?',
 'relationships', 'direct', 3),

('relationship_asymmetry',
 'Is there anything in that relationship that feels unresolved — not broken, just sitting there?',
 NULL,
 'relationships', 'medium', 4),

-- emotional_dependency
('emotional_dependency',
 'Is there anyone in your life right now who you feel like you can be fully honest with — not managing how they receive it?',
 'What makes that possible with them?',
 'relationships', 'light', 1),

-- confidence_gap
('confidence_gap',
 'How do you feel about your own momentum right now — like you''re building something, or more like you''re waiting to feel ready?',
 'What would feeling ready actually look like?',
 'self', 'medium', 2),

-- relational_shift
('relational_shift',
 'How has that relationship changed over the last year or so — is it different from what it used to be?',
 'Is that change something you chose, or did it just happen?',
 'relationships', 'medium', 3),

-- grief
('grief',
 'Is there anything you''ve lost recently — a relationship, a version of yourself, a plan — that you haven''t fully processed yet?',
 NULL,
 'self', 'direct', 4),

-- unresolved_feeling
('unresolved_feeling',
 'Is there anything you''re carrying right now that you haven''t said out loud to anyone?',
 NULL,
 'self', 'direct', 5);

-- RLS
ALTER TABLE socratic_question_templates ENABLE ROW LEVEL SECURITY;
-- Public read — these are templates, not user data
CREATE POLICY "Public read socratic templates"
    ON socratic_question_templates FOR SELECT
    USING (true);

-- Index
CREATE INDEX idx_socratic_signal_type
    ON socratic_question_templates(signal_type, intensity);

-- ------------------------------------------------------------
-- Seed: TJ facts from 2026-03-10 session
-- (replace owner_user_id and person_id with real values)
-- ------------------------------------------------------------
-- INSERT INTO person_facts
--     (owner_user_id, person_id, fact_key, fact_value, fact_type, domain, confidence, source)
-- VALUES
--     ('d7e78b66-517b-43c9-8462-555855fd34f2', '<TJ_person_id>', 'monthly_support_amount', '1000', 'number', 'finance', 1.0, 'user_stated'),
--     ('d7e78b66-517b-43c9-8462-555855fd34f2', '<TJ_person_id>', 'support_end_date', '2026-08-01', 'date', 'finance', 1.0, 'user_stated'),
--     ('d7e78b66-517b-43c9-8462-555855fd34f2', '<TJ_person_id>', 'support_pre_august_type', 'gift_no_payback', 'text', 'finance', 1.0, 'user_stated'),
--     ('d7e78b66-517b-43c9-8462-555855fd34f2', '<TJ_person_id>', 'support_post_august_type', 'loan_when_stable', 'text', 'finance', 1.0, 'user_stated'),
--     ('d7e78b66-517b-43c9-8462-555855fd34f2', '<TJ_person_id>', 'job_search_status', 'applying_independently', 'text', 'relationships', 1.0, 'user_stated'),
--     ('d7e78b66-517b-43c9-8462-555855fd34f2', '<TJ_person_id>', 'interview_weakness', 'confidence_not_effort', 'text', 'relationships', 1.0, 'user_stated'),
--     ('d7e78b66-517b-43c9-8462-555855fd34f2', '<TJ_person_id>', 'relationship_goal', 'equal_friendship', 'text', 'relationships', 1.0, 'user_stated');

-- ------------------------------------------------------------
-- Seed: TJ financial bridge recommendation from 2026-03-10
-- ------------------------------------------------------------
-- INSERT INTO recommendations
--     (owner_user_id, person_id, title, recommendation_text, script, timing, domain, reasoning_chain)
-- VALUES (
--     'd7e78b66-517b-43c9-8462-555855fd34f2',
--     '<TJ_person_id>',
--     'The TJ Financial Bridge Conversation',
--     'Have an explicit conversation with TJ framing pre-August support as a gift and post-August as a loan payable when stable. Name the goal out loud: real friendship on the other side.',
--     'Hey — I want to talk about something and I want it to feel easy, not heavy.

-- You know my severance runs out in August and my insurance coverage ends then too. So that''s my real deadline — not something I''m choosing, it''s just what it is. Until August I''ve got you, fully, whatever you need. And everything up until August — don''t think about paying any of it back. That''s just me, that''s just us, that''s off the table.

-- After August, once you''ve landed — whatever I''ve helped with from that point on, I want you to pay that back when you''re stable. Not on a schedule, not with pressure. Just when it feels right and you''re on your feet.

-- I''m not saying it because I need the money. I''m saying it because I think it''ll matter to you that you did it. And I want us to be real friends on the other side of all this without anything sitting between us.

-- That''s it. Nothing heavy. Just wanted to say it out loud.',
--     'when_ready',
--     'relationships',
--     '{
--         "observations": [
--             "Leo has raised credit card separation 3+ times without resolution",
--             "TJ is applying to jobs independently — dependency is confidence not motivation",
--             "Leo severance ends August 2026 — external constraint already communicated to TJ",
--             "TJ responds to dignity framing, shame is the real friction not the money",
--             "Leo uses generosity to maintain proximity — giving keeps him needed"
--         ],
--         "pattern_identified": "Leo''s generosity outpaces TJ''s independence development; financial entanglement is emotional proxy for closeness",
--         "goal": "Transition to equal friendship with no financial residue sitting between them",
--         "why_this_approach": "August is external not personal — removes the sting of withdrawal. Clean start from now, not retroactive accounting.",
--         "why_this_framing": "Pre-August as gift removes shame. Post-August loan restores TJ''s agency and dignity. No dollar total, no schedule — keeps it human not transactional.",
--         "what_not_to_do": "Do not introduce a formal agreement or specific dollar total. Do not make it retroactive. Do not send over text.",
--         "fact_refs": ["monthly_support_amount", "support_end_date", "job_search_status"],
--         "memory_refs": ["Valentine dinner", "Credit card conversation(s)", "TJ sober and broke"]
--     }'::jsonb
-- );
