-- Personal Genie — Supabase Schema
-- Run this in your Supabase SQL editor to create all tables
-- Dashboard → SQL Editor → New query → paste this → Run

-- ── Users ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT,
  phone TEXT UNIQUE,
  apple_id TEXT,
  google_id TEXT,
  google_access_token TEXT,
  google_refresh_token TEXT,
  whatsapp_consented BOOLEAN DEFAULT false,
  whatsapp_consented_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- ── People (the relationship graph) ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS people (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  subject_user_id UUID REFERENCES users(id),   -- null until subject joins
  name TEXT NOT NULL,
  phone TEXT,
  email TEXT,
  relationship_type TEXT,
  closeness_score REAL DEFAULT 0.5,
  last_contact TIMESTAMPTZ,
  topics JSONB DEFAULT '[]',
  memories JSONB DEFAULT '[]',
  suggested_moments JSONB DEFAULT '[]',
  emotions_history JSONB DEFAULT '[]',
  consent_status TEXT DEFAULT 'pending',
  bilateral BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_people_owner ON people(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_people_closeness ON people(owner_user_id, closeness_score DESC);

-- ── Messages ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  from_person_id UUID REFERENCES people(id),
  platform TEXT,
  body TEXT,
  timestamp TIMESTAMPTZ,
  processed BOOLEAN DEFAULT false,
  media_url TEXT,
  emotion_detected TEXT,
  topics_detected JSONB DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_messages_unprocessed ON messages(owner_user_id, processed);

-- ── Call Notes (voice note transcriptions) ────────────────────────────────────
CREATE TABLE IF NOT EXISTS call_notes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  person_id UUID REFERENCES people(id),
  audio_url TEXT,
  transcript TEXT,
  topics JSONB DEFAULT '[]',
  emotions JSONB,
  extracted_memories JSONB DEFAULT '[]',
  created_at TIMESTAMPTZ DEFAULT now()
);

-- ── Moments (suggested actions) ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS moments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  person_id UUID REFERENCES people(id),
  suggestion TEXT,
  triggered_by TEXT,
  status TEXT DEFAULT 'pending',
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_moments_pending ON moments(owner_user_id, status);

-- ── Consent (audit log) ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS consent (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  person_id UUID REFERENCES people(id),
  scope JSONB DEFAULT '[]',
  consented_at TIMESTAMPTZ,
  revoked_at TIMESTAMPTZ,
  audit_log JSONB DEFAULT '[]'
);

-- ── Invites ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS invites (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  inviter_user_id UUID REFERENCES users(id),
  invitee_phone TEXT,
  invitee_name TEXT,
  invite_token TEXT UNIQUE,
  status TEXT DEFAULT 'sent',
  pre_built_graph JSONB,
  sent_at TIMESTAMPTZ DEFAULT now(),
  accepted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_invites_token ON invites(invite_token);

-- ── Shared Nodes (bilateral relationship tracking) ────────────────────────────
CREATE TABLE IF NOT EXISTS shared_nodes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  person_a_user_id UUID REFERENCES users(id),
  person_b_user_id UUID REFERENCES users(id),
  shared_person_id UUID REFERENCES people(id),
  created_at TIMESTAMPTZ DEFAULT now()
);
