-- ============================================================
-- PersonalGenie — Schema Migration v9c
-- Network Signal Consent-on-Demand
-- 2026-03-10
-- Implements Section 11.5–11.7: Network Signal Intelligence
-- and Consent-on-Demand Protocol
-- ============================================================

-- ------------------------------------------------------------
-- Update third_party_signals
-- Add consent_status to the existing table.
-- Signals are quarantined (PENDING_CONSENT) until the source
-- user explicitly approves sharing them.
-- ------------------------------------------------------------
ALTER TABLE third_party_signals
  ADD COLUMN IF NOT EXISTS consent_status TEXT NOT NULL DEFAULT 'pending_consent',
  -- pending_consent | granted | denied | expired | not_required
  -- not_required = signal about a public fact, no consent needed

  ADD COLUMN IF NOT EXISTS consent_request_id UUID;
  -- FK to signal_consent_requests once a request is created

-- Signals cannot be used until consent_status = 'granted'
-- The application layer enforces this; the index makes it fast.
CREATE INDEX IF NOT EXISTS idx_third_party_signals_consent
  ON third_party_signals(consent_status)
  WHERE consent_status = 'granted';

-- ------------------------------------------------------------
-- signal_consent_requests
-- One record per consent request. Tracks the specific ask:
-- what signal, who wants it, who must approve, what text
-- would be shared, and the outcome.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS signal_consent_requests (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  signal_id             UUID NOT NULL REFERENCES third_party_signals(id) ON DELETE CASCADE,
  -- the signal being requested

  requesting_user_id    UUID NOT NULL REFERENCES users(id),
  -- whose Genie wants to use the signal (e.g. Leo)

  granting_user_id      UUID NOT NULL REFERENCES users(id),
  -- whose Genie extracted the signal and must approve (e.g. Anjali)

  about_person_id       UUID REFERENCES people(id),
  -- who the signal is about (e.g. Jiya) — may be NULL if not on platform

  about_person_name     TEXT,
  -- display name for the about-person shown in the consent ask

  beneficiary_user_id   UUID NOT NULL REFERENCES users(id),
  -- who would receive the surfaced moment (usually = requesting_user_id)

  proposed_share_text   TEXT NOT NULL,
  -- exactly what would be shared — shown to granting_user verbatim
  -- e.g. "Jiya has an upcoming date she's excited about"

  purpose_text          TEXT NOT NULL,
  -- why this would be shared — shown to granting_user
  -- e.g. "suggest Leo check in with Jiya"

  status                TEXT NOT NULL DEFAULT 'pending',
  -- pending | granted | denied | snoozed | expired | modified

  modified_share_text   TEXT,
  -- if granting_user approved with edits — what actually flows
  -- NULL if no modification

  granting_user_note    TEXT,
  -- optional: granting user's own note about their decision

  requested_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  responded_at          TIMESTAMPTZ,
  expires_at            TIMESTAMPTZ NOT NULL,
  -- if granting_user doesn't respond by expires_at:
  -- status → expired, signal never flows, requester never notified

  snooze_until          TIMESTAMPTZ
  -- if snoozed: re-surface to granting_user at this time
);

-- ------------------------------------------------------------
-- signal_consent_audit_log
-- Immutable append-only audit trail of every consent event.
-- Never updated — only inserted. Provides full accountability
-- for what was shared, when, by whose approval, and how used.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS signal_consent_audit_log (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  consent_request_id  UUID NOT NULL REFERENCES signal_consent_requests(id),

  event_type          TEXT NOT NULL,
  -- requested | granted | denied | snoozed | expired
  -- modified | used | revoked

  actor_user_id       UUID NOT NULL REFERENCES users(id),
  -- who triggered this event (Anjali granting, Leo's Genie requesting, etc.)

  event_detail        TEXT NOT NULL,
  -- human-readable:
  -- "Anjali granted permission to share date signal with Leo"
  -- "Leo's Genie used signal in morning session"
  -- "Anjali revoked consent — signal removed from Leo's Genie"

  actual_share_text   TEXT,
  -- what was actually shared (may differ from proposed if Anjali modified)
  -- only populated on event_type = 'used'

  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
  -- NO updated_at — this table is append-only, never modified
);

-- Prevent updates to audit log rows (belt + suspenders)
CREATE RULE no_update_audit_log AS
  ON UPDATE TO signal_consent_audit_log
  DO INSTEAD NOTHING;

-- ------------------------------------------------------------
-- Row Level Security
-- ------------------------------------------------------------
ALTER TABLE signal_consent_requests ENABLE ROW LEVEL SECURITY;

-- Requesting user sees requests they initiated
CREATE POLICY "Requesting user sees own requests"
  ON signal_consent_requests FOR SELECT
  USING (auth.uid() = requesting_user_id);

-- Granting user sees requests they must respond to
CREATE POLICY "Granting user sees requests to approve"
  ON signal_consent_requests FOR SELECT
  USING (auth.uid() = granting_user_id);

-- Only the granting user can update status (respond to the request)
CREATE POLICY "Granting user responds to own requests"
  ON signal_consent_requests FOR UPDATE
  USING (auth.uid() = granting_user_id);

ALTER TABLE signal_consent_audit_log ENABLE ROW LEVEL SECURITY;

-- Each user sees audit entries where they are the actor
-- OR where the consent request involves them
CREATE POLICY "Users see relevant audit entries"
  ON signal_consent_audit_log FOR SELECT
  USING (
    auth.uid() = actor_user_id
    OR auth.uid() IN (
      SELECT requesting_user_id FROM signal_consent_requests
      WHERE id = consent_request_id
      UNION
      SELECT granting_user_id FROM signal_consent_requests
      WHERE id = consent_request_id
    )
  );

-- Audit log is insert-only from application
CREATE POLICY "Insert only — no user updates to audit log"
  ON signal_consent_audit_log FOR INSERT
  WITH CHECK (true);

-- ------------------------------------------------------------
-- Indexes
-- ------------------------------------------------------------
CREATE INDEX idx_consent_requests_granting_pending
  ON signal_consent_requests(granting_user_id, status)
  WHERE status = 'pending';
  -- fast lookup: "what requests does Anjali need to respond to?"

CREATE INDEX idx_consent_requests_signal
  ON signal_consent_requests(signal_id);

CREATE INDEX idx_consent_requests_about_person
  ON signal_consent_requests(about_person_id);

CREATE INDEX idx_consent_requests_expires
  ON signal_consent_requests(expires_at)
  WHERE status = 'pending';
  -- for expiry job: find requests that have timed out

CREATE INDEX idx_audit_log_request
  ON signal_consent_audit_log(consent_request_id, created_at);

CREATE INDEX idx_audit_log_actor
  ON signal_consent_audit_log(actor_user_id, created_at);
