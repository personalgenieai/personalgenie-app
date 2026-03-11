-- schema_migration_v8b.sql
-- Bilateral graph: third-party signal extraction + cross-user permission grants
-- Run after schema_migration_v8.sql

-- ── third_party_signals ───────────────────────────────────────────────────────
-- Stores signals extracted from conversations where a person is MENTIONED but
-- not a participant. Raw transcript is never stored here — only the abstracted
-- signal. Source attribution is stored but NEVER surfaced to the about_person.

CREATE TABLE IF NOT EXISTS third_party_signals (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    about_person_id     UUID REFERENCES people(id) ON DELETE SET NULL,
    about_phone_hash    TEXT,          -- matched when person signs up
    signal_type         TEXT NOT NULL, -- emotional_concern | factual_update | relational_shift | avoidance | positive_regard | unresolved_feeling
    signal_abstract     TEXT NOT NULL, -- anonymized, no verbatim content, no names
    signal_valence      FLOAT,         -- -1.0 (negative) → 0 (neutral) → 1.0 (positive)
    signal_intensity    FLOAT,         -- 0.0 (weak) → 1.0 (strong)
    confidence          FLOAT NOT NULL DEFAULT 0.7,
    extracted_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at          TIMESTAMPTZ,   -- NULL = never expires; default 90 days in app
    source_message_hash TEXT,          -- hash of source message (for dedup, never full content)
    used_count          INTEGER DEFAULT 0,  -- how many times injected into World Model
    last_used_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_third_party_signals_about_person ON third_party_signals(about_person_id);
CREATE INDEX IF NOT EXISTS idx_third_party_signals_phone_hash ON third_party_signals(about_phone_hash);
CREATE INDEX IF NOT EXISTS idx_third_party_signals_source_user ON third_party_signals(source_user_id);
CREATE INDEX IF NOT EXISTS idx_third_party_signals_expires ON third_party_signals(expires_at);

-- ── cross_user_permissions ────────────────────────────────────────────────────
-- Explicit permission grants. A granting user allows Genie to use their signals
-- about a person to help that person. Instantly revocable. Never shown to the
-- beneficiary — they see only Genie's behavior, never the permission structure.

CREATE TABLE IF NOT EXISTS cross_user_permissions (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    granting_user_id        UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    beneficiary_phone_hash  TEXT NOT NULL,     -- hashed phone of the person being helped
    beneficiary_user_id     UUID REFERENCES users(id) ON DELETE CASCADE,  -- populated if they sign up
    permission_level        INTEGER NOT NULL DEFAULT 0,  -- 0=silent 1=passive 2=soft_bridge 3=named
    scope                   TEXT NOT NULL DEFAULT 'wellbeing',  -- wellbeing | factual | all
    granted_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at              TIMESTAMPTZ,       -- instant revocation
    granting_note           TEXT,              -- optional: what Leo said when granting ("I want Genie to help TJ")
    is_active               BOOLEAN GENERATED ALWAYS AS (revoked_at IS NULL) STORED
);

CREATE INDEX IF NOT EXISTS idx_cup_granting_user ON cross_user_permissions(granting_user_id);
CREATE INDEX IF NOT EXISTS idx_cup_beneficiary_hash ON cross_user_permissions(beneficiary_phone_hash);
CREATE INDEX IF NOT EXISTS idx_cup_beneficiary_user ON cross_user_permissions(beneficiary_user_id);
CREATE INDEX IF NOT EXISTS idx_cup_active ON cross_user_permissions(is_active);
