-- schema_migration_v9.sql
-- New tables for push notifications, billing, rule executions,
-- nightly conversations, capability lifecycle, world model, and supporting indexes.

-- push_tokens: APNs and FCM device tokens
CREATE TABLE IF NOT EXISTS push_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device_token TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT 'ios',   -- 'ios' | 'android'
    bundle_id TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    registered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ,
    UNIQUE(user_id, device_token)
);

-- subscriptions: Stripe subscription state
CREATE TABLE IF NOT EXISTS subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT UNIQUE,
    plan TEXT NOT NULL DEFAULT 'free',  -- 'free' | 'individual' | 'family' | 'pro'
    status TEXT NOT NULL DEFAULT 'active',  -- 'active' | 'past_due' | 'canceled' | 'trialing'
    current_period_start TIMESTAMPTZ,
    current_period_end TIMESTAMPTZ,
    cancel_at_period_end BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id)
);

-- rule_executions: deduplication for rule engine firings
CREATE TABLE IF NOT EXISTS rule_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_id UUID NOT NULL,
    user_id UUID NOT NULL,
    fired_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    action_taken TEXT,
    result TEXT
);

-- nightly_conversations: track Genie-initiated evening conversations
CREATE TABLE IF NOT EXISTS nightly_conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    seed_type TEXT NOT NULL,
    opening_message TEXT NOT NULL,
    sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_replied BOOLEAN NOT NULL DEFAULT FALSE,
    reply_count INTEGER NOT NULL DEFAULT 0
);

-- capability_lifecycle: track capability stage per user per area
CREATE TABLE IF NOT EXISTS capability_lifecycle (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    capability_area TEXT NOT NULL,
    stage INTEGER NOT NULL DEFAULT 0,
    signal_score FLOAT NOT NULL DEFAULT 0.0,
    trust_score FLOAT NOT NULL DEFAULT 0.0,
    last_offer_at TIMESTAMPTZ,
    last_evaluated_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, capability_area)
);

-- world_model: snapshot store for audit/debug
CREATE TABLE IF NOT EXISTS world_model (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    snapshot JSONB NOT NULL,
    assembled_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- genie_rules (already created in v8, add if missing)
CREATE TABLE IF NOT EXISTS genie_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plain_english TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    trigger_config JSONB NOT NULL DEFAULT '{}',
    action_type TEXT NOT NULL,
    action_config JSONB NOT NULL DEFAULT '{}',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- user_interests: full interest graph
CREATE TABLE IF NOT EXISTS user_interests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    subcategory TEXT,
    value TEXT NOT NULL,
    confidence FLOAT NOT NULL DEFAULT 0.5,
    source TEXT NOT NULL DEFAULT 'message',
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    seen_count INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, category, value)
);

-- third_party_signals (already in v8b, add if missing)
CREATE TABLE IF NOT EXISTS third_party_signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    about_person_id UUID REFERENCES people(id) ON DELETE SET NULL,
    about_phone_hash TEXT,
    signal_type TEXT NOT NULL,
    signal_abstract TEXT NOT NULL,
    signal_valence FLOAT NOT NULL DEFAULT 0.0,
    signal_intensity FLOAT NOT NULL DEFAULT 0.5,
    confidence FLOAT NOT NULL DEFAULT 0.5,
    expires_at TIMESTAMPTZ,
    source_message_hash TEXT UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- cross_user_permissions (already in v8b, add if missing)
CREATE TABLE IF NOT EXISTS cross_user_permissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    granting_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    beneficiary_phone_hash TEXT NOT NULL,
    beneficiary_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    permission_level INTEGER NOT NULL DEFAULT 0,
    scope TEXT NOT NULL DEFAULT 'wellbeing',
    granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at TIMESTAMPTZ,
    is_active BOOLEAN GENERATED ALWAYS AS (revoked_at IS NULL) STORED
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_push_tokens_user_id ON push_tokens(user_id) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_subscriptions_user_id ON subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_rule_executions_rule_id ON rule_executions(rule_id, executed_at DESC);
CREATE INDEX IF NOT EXISTS idx_nightly_user_id ON nightly_conversations(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_capability_user_area ON capability_lifecycle(user_id, capability_id);
CREATE INDEX IF NOT EXISTS idx_world_model_user ON world_model(user_id, last_updated DESC);
CREATE INDEX IF NOT EXISTS idx_user_interests_user ON user_interests(user_id, category, confidence DESC);
CREATE INDEX IF NOT EXISTS idx_third_party_signals_about ON third_party_signals(about_phone_hash, extracted_at DESC);
CREATE INDEX IF NOT EXISTS idx_cross_user_perms ON cross_user_permissions(granting_user_id, beneficiary_phone_hash);
