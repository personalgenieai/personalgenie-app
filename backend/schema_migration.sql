-- PersonalGenie Schema Migration — PRD v4
-- Run this in Supabase SQL Editor.
-- Safe to run multiple times — uses IF NOT EXISTS and ADD COLUMN IF NOT EXISTS everywhere.
-- Never drops any existing table or column.

create extension if not exists "uuid-ossp";

-- ── Expand existing users table with new columns ────────────────────────────
alter table users add column if not exists email text unique;
alter table users add column if not exists google_token_expiry timestamp;
alter table users add column if not exists reddit_access_token text;
alter table users add column if not exists reddit_refresh_token text;
alter table users add column if not exists readwise_access_token text;
alter table users add column if not exists stripe_customer_id text;
alter table users add column if not exists subscription_status text default 'trial';
alter table users add column if not exists subscription_plan text default 'free';
alter table users add column if not exists subscription_expiry timestamp;
alter table users add column if not exists trial_started_at timestamp default now();
alter table users add column if not exists trial_ends_at timestamp default now() + interval '14 days';
alter table users add column if not exists imessage_consented boolean default false;
alter table users add column if not exists imessage_consented_at timestamp;
alter table users add column if not exists apple_music_consented boolean default false;
alter table users add column if not exists biometric_consented boolean default false;
alter table users add column if not exists biometric_consented_at timestamp;
alter table users add column if not exists agent_diplomacy_consented boolean default false;
alter table users add column if not exists apple_tv_connected boolean default false;
alter table users add column if not exists onboarding_completed boolean default false;
alter table users add column if not exists onboarding_step integer default 0;
alter table users add column if not exists onboarding_started_at timestamp;
alter table users add column if not exists timezone text default 'UTC';
alter table users add column if not exists location_country text;
alter table users add column if not exists location_state text;
alter table users add column if not exists jurisdiction text default 'OTHER';
alter table users add column if not exists quiet_hours_start time default '22:00';
alter table users add column if not exists quiet_hours_end time default '08:00';
alter table users add column if not exists notification_max_per_day integer default 5;
alter table users add column if not exists consecutive_dismissals integer default 0;
alter table users add column if not exists genie_proactivity text default 'normal';
alter table users add column if not exists preferred_language text default 'en';
alter table users add column if not exists last_active timestamp default now();
alter table users add column if not exists deleted_at timestamp;
alter table users add column if not exists deletion_requested_at timestamp;

-- ── Expand existing people table with new columns ───────────────────────────
alter table people add column if not exists photo_url text;
alter table people add column if not exists relationship_confirmed boolean default false;
alter table people add column if not exists status text default 'living';
alter table people add column if not exists deceased_handled_with_care boolean default false;
alter table people add column if not exists last_meaningful_exchange timestamp;
alter table people add column if not exists last_meaningful_exchange_summary text;
alter table people add column if not exists communication_style text;
alter table people add column if not exists preferred_language text default 'en';
alter table people add column if not exists shared_interests text[];
alter table people add column if not exists relationship_health_score float default 0.7;
alter table people add column if not exists drift_alert boolean default false;
alter table people add column if not exists consent_scope text[];
alter table people add column if not exists invite_sent boolean default false;
alter table people add column if not exists invite_sent_at timestamp;
alter table people add column if not exists invite_accepted_at timestamp;
alter table people add column if not exists data_sources text[];
alter table people add column if not exists conflict_flags jsonb[] default array[]::jsonb[];
alter table people add column if not exists communication_dna jsonb default '{}'::jsonb;
alter table people add column if not exists linguistic_profile jsonb default '{}'::jsonb;
alter table people add column if not exists updated_at timestamp default now();

-- ── Expand existing messages table ──────────────────────────────────────────
alter table messages add column if not exists to_person_id uuid references people(id);
alter table messages add column if not exists group_id text;
alter table messages add column if not exists body_language text default 'en';
alter table messages add column if not exists processing_attempts integer default 0;
alter table messages add column if not exists processing_error text;
alter table messages add column if not exists processing_priority integer default 0;
alter table messages add column if not exists media_type text;
alter table messages add column if not exists emotion_confidence float;
alter table messages add column if not exists topics_detected text[];
alter table messages add column if not exists is_from_owner boolean default false;
alter table messages add column if not exists raw_retained_until timestamp;
alter table messages add column if not exists created_at timestamp default now();

-- ── Expand existing moments table ───────────────────────────────────────────
alter table moments add column if not exists suggestion_detail text;
alter table moments add column if not exists trigger_data jsonb;
alter table moments add column if not exists urgency text default 'normal';
alter table moments add column if not exists snoozed_until timestamp;
alter table moments add column if not exists drafted_message text;
alter table moments add column if not exists drafted_message_language text;
alter table moments add column if not exists feedback text;
alter table moments add column if not exists feedback_detail text;
alter table moments add column if not exists acted_on_at timestamp;
alter table moments add column if not exists dismissed_at timestamp;
alter table moments add column if not exists snoozed_at timestamp;

-- ── Expand existing invites table ───────────────────────────────────────────
alter table invites add column if not exists invite_message text;
alter table invites add column if not exists invite_language text default 'en';
alter table invites add column if not exists pre_built_insights jsonb;
alter table invites add column if not exists reminder_count integer default 0;
alter table invites add column if not exists last_reminder_at timestamp;
alter table invites add column if not exists opened_at timestamp;
alter table invites add column if not exists expires_at timestamp default now() + interval '7 days';

-- ── Expand existing call_notes table ────────────────────────────────────────
alter table call_notes add column if not exists audio_deleted_at timestamp;
alter table call_notes add column if not exists duration_seconds integer;
alter table call_notes add column if not exists transcript_language text;
alter table call_notes add column if not exists urgency_flags jsonb[];
alter table call_notes add column if not exists suggested_followups jsonb[];
alter table call_notes add column if not exists processed boolean default false;

-- ── Policy Engine tables (new) ───────────────────────────────────────────────
create table if not exists policies (
  id uuid primary key default uuid_generate_v4(),
  name text unique not null,
  category text not null,
  jurisdiction text[],
  content text not null,
  compiled_function text,
  version integer default 1,
  active boolean default true,
  last_tested timestamp,
  test_results jsonb,
  created_at timestamp default now(),
  updated_at timestamp default now()
);

create table if not exists policy_decisions (
  id uuid primary key default uuid_generate_v4(),
  operation text not null,
  context jsonb not null,
  applicable_policies text[],
  decision boolean not null,
  reason text not null,
  required_actions text[],
  execution_time_ms integer,
  created_at timestamp default now()
);

create table if not exists policy_actions_log (
  id uuid primary key default uuid_generate_v4(),
  decision_id uuid references policy_decisions(id),
  action text not null,
  executed boolean default false,
  executed_at timestamp,
  result jsonb,
  created_at timestamp default now()
);

-- ── New feature tables ───────────────────────────────────────────────────────
create table if not exists interests (
  id uuid primary key default uuid_generate_v4(),
  owner_user_id uuid references users(id) on delete cascade,
  source text not null,
  item_type text,
  title text,
  url text,
  content_summary text,
  topics text[],
  emotional_weight text,
  highlight_text text,
  language text default 'en',
  processed boolean default false,
  created_at timestamp default now()
);

create table if not exists emotional_states (
  id uuid primary key default uuid_generate_v4(),
  owner_user_id uuid references users(id) on delete cascade,
  timestamp timestamp default now(),
  inferred_mood text,
  confidence float,
  signals jsonb,
  intervention_threshold text default 'normal',
  recommended_action text,
  acted_on boolean default false,
  created_at timestamp default now()
);

create table if not exists life_events (
  id uuid primary key default uuid_generate_v4(),
  owner_user_id uuid references users(id) on delete cascade,
  person_id uuid references people(id),
  event_type text,
  title text,
  description text,
  date date,
  is_annual boolean default false,
  emotional_weight text,
  how_to_handle text default 'acknowledge_gently',
  photo_url text,
  last_acknowledged_at timestamp,
  created_at timestamp default now()
);

create table if not exists notifications (
  id uuid primary key default uuid_generate_v4(),
  owner_user_id uuid references users(id) on delete cascade,
  moment_id uuid references moments(id),
  channel text not null,
  content text not null,
  language text default 'en',
  status text default 'pending',
  sent_at timestamp,
  opened_at timestamp,
  dismissed_at timestamp,
  response text,
  created_at timestamp default now()
);

create table if not exists job_queue (
  id uuid primary key default uuid_generate_v4(),
  job_type text not null,
  payload jsonb not null,
  status text default 'pending',
  attempts integer default 0,
  max_attempts integer default 3,
  last_attempted_at timestamp,
  last_error text,
  scheduled_for timestamp default now(),
  completed_at timestamp,
  created_at timestamp default now()
);

create table if not exists bilateral_conflicts (
  id uuid primary key default uuid_generate_v4(),
  person_a_user_id uuid references users(id),
  person_b_user_id uuid references users(id),
  conflict_type text,
  field_in_conflict text,
  person_a_value text,
  person_b_value text,
  resolution text,
  resolved_value text,
  resolved_at timestamp,
  created_at timestamp default now()
);

create table if not exists genie_feedback (
  id uuid primary key default uuid_generate_v4(),
  owner_user_id uuid references users(id) on delete cascade,
  moment_id uuid references moments(id),
  feedback_type text,
  original_content text,
  correction text,
  learned_rule text,
  applied_to_future boolean default true,
  created_at timestamp default now()
);

create table if not exists subscriptions (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references users(id) on delete cascade,
  stripe_subscription_id text unique,
  stripe_customer_id text,
  plan text not null,
  status text not null,
  current_period_start timestamp,
  current_period_end timestamp,
  cancel_at_period_end boolean default false,
  family_seats integer default 1,
  family_member_ids uuid[],
  created_at timestamp default now(),
  updated_at timestamp default now()
);

create table if not exists group_chat_profiles (
  id uuid primary key default uuid_generate_v4(),
  owner_user_id uuid references users(id) on delete cascade,
  group_id text not null,
  group_name text,
  platform text not null,
  member_phones text[],
  member_people_ids uuid[],
  owner_role text,
  owner_message_ratio float,
  most_responsive_to_owner uuid references people(id),
  direct_address_patterns jsonb,
  subrelationship_signals jsonb[],
  recurring_topics text[],
  topics_only_in_group text[],
  topics_never_in_group text[],
  group_health_score float,
  last_analyzed timestamp,
  sample_size integer,
  created_at timestamp default now(),
  updated_at timestamp default now()
);

create table if not exists genie_conversations (
  id uuid primary key default uuid_generate_v4(),
  owner_user_id uuid references users(id) on delete cascade,
  person_id uuid references people(id),
  conversation_type text,
  genie_opening text,
  exchanges jsonb[],
  insight_extracted text,
  profile_field_updated text,
  profile_update_value jsonb,
  user_engaged boolean,
  created_at timestamp default now()
);

-- ── Indexes on new tables ────────────────────────────────────────────────────
create index if not exists idx_messages_owner on messages(owner_user_id);
create index if not exists idx_messages_processed on messages(processed);
create index if not exists idx_messages_timestamp on messages(timestamp);
create index if not exists idx_people_owner on people(owner_user_id);
create index if not exists idx_people_subject on people(subject_user_id);
create index if not exists idx_moments_owner on moments(owner_user_id);
create index if not exists idx_moments_status on moments(status);
create index if not exists idx_emotional_states_owner on emotional_states(owner_user_id);
create index if not exists idx_emotional_states_timestamp on emotional_states(timestamp);
create index if not exists idx_job_queue_status on job_queue(status);
create index if not exists idx_job_queue_scheduled on job_queue(scheduled_for);
create index if not exists idx_notifications_owner on notifications(owner_user_id);
create index if not exists idx_notifications_status on notifications(status);
create index if not exists idx_group_chat_owner on group_chat_profiles(owner_user_id);
create index if not exists idx_genie_conversations_owner on genie_conversations(owner_user_id);
create index if not exists idx_policy_decisions_created on policy_decisions(created_at);
create index if not exists idx_policy_actions_decision on policy_actions_log(decision_id);

-- ── Health Genie POC — Sprint 1 (2026-03-09) ────────────────────────────────
-- Safe to run multiple times: uses IF NOT EXISTS and ADD COLUMN IF NOT EXISTS.

create table if not exists nutrition_log (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references users(id) on delete cascade,
  logged_at timestamptz default now(),
  meal_type text,                        -- breakfast | lunch | dinner | snack | inferred
  raw_input text not null,               -- exactly what the user said/sent
  input_type text default 'text',        -- text | voice
  parsed_foods jsonb not null default '[]'::jsonb,
  total_calories float default 0,
  total_protein float default 0,
  total_carbs float default 0,
  total_fat float default 0,
  parsing_confidence float default 1.0,  -- 0.0–1.0
  genie_clarified boolean default false, -- did Genie ask a follow-up to resolve ambiguity
  notes text
);

create table if not exists training_sessions (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references users(id) on delete cascade,
  trainer_person_id uuid references people(id),
  session_date date not null,
  duration_minutes integer,
  session_type text,                     -- strength | cardio | mobility | mixed
  audio_transcript text,                 -- raw Whisper output
  exercises jsonb default '[]'::jsonb,
  session_summary text,
  trainer_feedback jsonb default '{}'::jsonb,
  personal_records jsonb default '[]'::jsonb,
  whatsapp_summary_sent boolean default false,
  created_at timestamptz default now()
);

create table if not exists exercise_history (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references users(id) on delete cascade,
  training_session_id uuid references training_sessions(id) on delete cascade,
  exercise_name text not null,
  exercise_canonical_name text,
  set_number integer,
  reps integer,
  weight_kg float,
  rpe float,
  is_personal_record boolean default false,
  previous_best_weight float,
  notes text,
  logged_at timestamptz default now()
);

create table if not exists health_daily_summary (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references users(id) on delete cascade,
  summary_date date not null,
  total_calories float default 0,
  total_protein float default 0,
  calorie_goal float,
  protein_goal float,
  trained boolean default false,
  training_session_id uuid references training_sessions(id),
  nudge_sent boolean default false,
  genie_health_note text,
  created_at timestamptz default now(),
  unique(user_id, summary_date)
);

create index if not exists idx_nutrition_log_user_date
  on nutrition_log(user_id, logged_at);
create index if not exists idx_training_sessions_user
  on training_sessions(user_id, session_date);
create index if not exists idx_exercise_history_user
  on exercise_history(user_id, exercise_canonical_name);
create index if not exists idx_health_daily_user_date
  on health_daily_summary(user_id, summary_date);

-- ── Sprint 3: Habit Formation ──────────────────────────────────────────────

create table if not exists health_profile (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references users(id) on delete cascade unique,
  -- Learning question answers
  calorie_goal int,
  protein_goal_g int,
  training_days_per_week int,
  goal_type text,              -- lose | gain | maintain
  food_restrictions text,
  biggest_struggle text,
  -- Learning flow state
  questions_completed int default 0,
  pending_question_idx int,    -- set while awaiting an answer, null otherwise
  last_question_date date,     -- prevents asking more than one question per day
  -- Nudge state
  last_nudge_variant_idx int default -1,  -- prevents repeating the same copy
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists idx_health_profile_user
  on health_profile(user_id);
