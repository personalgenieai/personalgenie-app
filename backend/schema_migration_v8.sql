-- PersonalGenie Schema v8 additions
-- Run after existing schema_migration.sql

create extension if not exists "uuid-ossp";

-- WORLD MODEL (unified context object)
create table if not exists world_model (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references users(id) on delete cascade unique,
  relationship_context jsonb default '{}'::jsonb,
  emotional_context jsonb default '{}'::jsonb,
  communication_context jsonb default '{}'::jsonb,
  financial_context jsonb default '{}'::jsonb,
  physical_context jsonb default '{}'::jsonb,
  coordination_context jsonb default '{}'::jsonb,
  last_updated timestamp default now(),
  version integer default 1
);

-- CAPABILITY LIFECYCLE
create table if not exists capability_lifecycle (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references users(id) on delete cascade,
  capability_id text not null,
  stage integer default 0,
  signal_score float default 0.0,
  trust_score float default 0.0,
  offer_sent_at timestamp,
  offer_message text,
  user_response text,
  user_responded_at timestamp,
  decline_count integer default 0,
  last_declined_at timestamp,
  data_sources_connected text[],
  learning_questions_asked integer default 0,
  ambient_since timestamp,
  observations jsonb default '[]'::jsonb,
  learned_rules jsonb default '[]'::jsonb,
  created_at timestamp default now(),
  updated_at timestamp default now(),
  unique(user_id, capability_id)
);

-- CONSENT (replaces ad-hoc consent tracking)
create table if not exists consent (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references users(id) on delete cascade,
  consent_type text not null,
  granted boolean not null,
  granted_at timestamp,
  revoked_at timestamp,
  revocation_completed_at timestamp,
  ip_address text,
  platform text
);

-- NOTIFICATIONS
create table if not exists notifications (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references users(id) on delete cascade,
  channel text not null,
  message text not null,
  sent_at timestamp default now(),
  opened boolean default false,
  notification_type text,
  related_moment_id uuid
);

-- NIGHTLY CONVERSATIONS
create table if not exists nightly_conversations (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references users(id) on delete cascade,
  person_id uuid references people(id),
  conversation_purpose text not null,
  capability_id text,
  genie_opening text not null,
  exchanges jsonb[] default array[]::jsonb[],
  insight_extracted text,
  world_model_field_updated text,
  world_model_update_value jsonb,
  user_engaged boolean default false,
  ignored boolean default false,
  created_at timestamp default now()
);

-- CAPABILITY OFFERS
create table if not exists capability_offers (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references users(id) on delete cascade,
  capability_id text not null,
  offer_message text not null,
  offer_channel text default 'whatsapp',
  response text,
  responded_at timestamp,
  sent_at timestamp default now()
);

-- GENIE RULES
create table if not exists genie_rules (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references users(id) on delete cascade,
  name text not null,
  natural_language_source text not null,
  trigger_config jsonb not null,
  action_config jsonb not null,
  implied_conditions jsonb,
  frequency_limit text default 'no_limit',
  active boolean default true,
  execution_count integer default 0,
  last_executed timestamp,
  last_execution_success boolean,
  user_feedback jsonb default '[]'::jsonb,
  created_at timestamp default now(),
  updated_at timestamp default now()
);

create table if not exists rule_executions (
  id uuid primary key default uuid_generate_v4(),
  rule_id uuid references genie_rules(id),
  user_id uuid references users(id) on delete cascade,
  trigger_event_type text,
  trigger_event_data jsonb,
  conditions_evaluated jsonb,
  conditions_result boolean,
  action_executed boolean,
  action_result jsonb,
  execution_time_ms integer,
  error text,
  executed_at timestamp default now()
);

-- SMART HOME
create table if not exists smart_home_devices (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references users(id) on delete cascade,
  device_type text not null,
  device_name text,
  local_ip text,
  credentials_encrypted text,
  companion_credentials_encrypted text,
  last_seen timestamp,
  active boolean default true,
  created_at timestamp default now()
);

create table if not exists device_macros (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references users(id) on delete cascade,
  device_id uuid references smart_home_devices(id),
  macro_name text not null,
  description text,
  trigger_phrases text[] not null,
  trigger_pattern text,
  steps jsonb not null,
  verified boolean default false,
  last_executed timestamp,
  last_success boolean,
  execution_count integer default 0,
  failure_count integer default 0,
  created_at timestamp default now(),
  updated_at timestamp default now()
);

create table if not exists device_commands (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references users(id) on delete cascade,
  device_id uuid references smart_home_devices(id),
  raw_intent text,
  parsed_command jsonb,
  execution_sequence jsonb,
  success boolean,
  failure_reason text,
  retry_count integer default 0,
  executed_at timestamp default now()
);

create table if not exists watch_history (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references users(id) on delete cascade,
  app_name text,
  content_title text,
  content_type text,
  season integer,
  episode integer,
  watch_position_seconds integer,
  total_duration_seconds integer,
  completed boolean default false,
  watched_at timestamp default now()
);

-- MUSIC
create table if not exists music_connections (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references users(id) on delete cascade,
  provider text not null,
  access_token_encrypted text,
  refresh_token_encrypted text,
  token_expires_at timestamp,
  spotify_user_id text,
  spotify_devices jsonb default '[]'::jsonb,
  spotify_device_name_map jsonb default '{}'::jsonb,
  connected_at timestamp default now(),
  last_synced timestamp,
  active boolean default true,
  unique(user_id, provider)
);

create table if not exists music_listening_history (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references users(id) on delete cascade,
  provider text not null,
  track_name text,
  artist_name text,
  album_name text,
  spotify_track_id text,
  apple_music_id text,
  played_at timestamp not null,
  duration_ms integer,
  valence float,
  energy float,
  context_type text,
  context_name text,
  created_at timestamp default now()
);

-- BLUETOOTH SPEAKERS
create table if not exists bluetooth_speakers (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references users(id) on delete cascade,
  user_given_name text not null,
  bluetooth_device_id text,
  bluetooth_device_name text,
  spotify_connect_device_id text,
  room_location text,
  active boolean default true,
  last_connected timestamp,
  created_at timestamp default now()
);

-- FINANCIAL
create table if not exists financial_accounts (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references users(id) on delete cascade,
  plaid_item_id text not null,
  plaid_account_id text unique,
  institution_name text,
  account_name text,
  account_type text,
  current_balance float,
  available_balance float,
  currency text default 'USD',
  access_token_encrypted text,
  last_synced timestamp,
  created_at timestamp default now()
);

create table if not exists financial_transactions (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references users(id) on delete cascade,
  plaid_transaction_id text unique,
  account_id text,
  amount float not null,
  currency text default 'USD',
  merchant_name text,
  merchant_category text[],
  date date not null,
  pending boolean default false,
  reviewed_by_genie boolean default false,
  surfaced_to_user boolean default false,
  user_label text,
  significance_score float default 0.0,
  relationship_context text,
  person_id uuid references people(id),
  genie_interpretation text,
  notes text,
  created_at timestamp default now()
);

create table if not exists financial_rules (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references users(id) on delete cascade,
  rule_type text not null,
  rule_description text not null,
  parameters jsonb,
  learned_from_exchange text,
  active boolean default true,
  created_at timestamp default now()
);

-- TRAINER PERSONA
create table if not exists trainer_persona (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references users(id) on delete cascade,
  trainer_person_id uuid references people(id),
  coaching_style jsonb default '{}'::jsonb,
  progression_model jsonb default '{}'::jsonb,
  user_response_patterns jsonb default '{}'::jsonb,
  known_limitations jsonb default '{}'::jsonb,
  known_capabilities jsonb default '{}'::jsonb,
  goals jsonb default '{}'::jsonb,
  current_program jsonb default '{}'::jsonb,
  genie_trainer_active boolean default false,
  persona_confidence float default 0.0,
  last_updated timestamp default now()
);

-- GROUP CHATS
create table if not exists group_chat_profiles (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references users(id) on delete cascade,
  platform text not null,
  group_id text not null,
  group_name text,
  member_count integer,
  user_role text,
  message_ratio float,
  direct_address_patterns jsonb,
  subrelationship_signals jsonb,
  topics_only_in_group text[],
  topics_never_in_group text[],
  created_at timestamp default now(),
  updated_at timestamp default now()
);

-- INGESTION TRACKING
create table if not exists ingestion_sessions (
  id uuid primary key,
  user_id uuid references users(id) on delete cascade,
  sources text[] not null,
  source_progress jsonb default '{}'::jsonb,
  source_status jsonb default '{}'::jsonb,
  activity_texts jsonb default '{}'::jsonb,
  activity_indices jsonb default '{}'::jsonb,
  insights_generated jsonb default '[]'::jsonb,
  work_items_filtered integer default 0,
  overall_complete boolean default false,
  started_at timestamp default now(),
  completed_at timestamp
);

create table if not exists ingestion_progress_events (
  id uuid primary key default uuid_generate_v4(),
  session_id uuid references ingestion_sessions(id),
  source text not null,
  progress float not null,
  activity_text text,
  insight_text text,
  created_at timestamp default now()
);

-- WORK FILTER LOG (counts only — no content)
create table if not exists work_filter_log (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references users(id) on delete cascade,
  source text not null,
  item_type text not null,
  classification text not null,
  confidence float,
  excluded_at timestamp default now()
);

-- CALENDAR SELECTIONS
create table if not exists calendar_selections (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references users(id) on delete cascade,
  platform text not null,
  calendar_id text not null,
  calendar_name text not null,
  included boolean not null,
  created_at timestamp default now(),
  unique(user_id, platform, calendar_id)
);

-- SUBSCRIPTIONS
create table if not exists subscriptions (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references users(id) on delete cascade,
  stripe_subscription_id text unique,
  tier text not null,
  status text not null,
  current_period_start timestamp,
  current_period_end timestamp,
  trial_end timestamp,
  cancelled_at timestamp,
  created_at timestamp default now()
);

-- v8 INDEXES
create index if not exists idx_world_model_user on world_model(user_id);
create index if not exists idx_capability_lifecycle_user on capability_lifecycle(user_id);
create index if not exists idx_capability_lifecycle_stage on capability_lifecycle(stage);
create index if not exists idx_genie_rules_user on genie_rules(user_id);
create index if not exists idx_genie_rules_active on genie_rules(active);
create index if not exists idx_rule_executions_rule on rule_executions(rule_id);
create index if not exists idx_financial_transactions_user on financial_transactions(user_id, date);
create index if not exists idx_device_macros_user on device_macros(user_id);
create index if not exists idx_nightly_conversations_user on nightly_conversations(user_id);
create index if not exists idx_music_connections_user on music_connections(user_id);
create index if not exists idx_music_history_user_time on music_listening_history(user_id, played_at);
create index if not exists idx_bluetooth_speakers_user on bluetooth_speakers(user_id);
create index if not exists idx_ingestion_sessions_user on ingestion_sessions(user_id);
create index if not exists idx_ingestion_events_session on ingestion_progress_events(session_id);
create index if not exists idx_work_filter_log_user on work_filter_log(user_id);
create index if not exists idx_calendar_selections_user on calendar_selections(user_id);
create index if not exists idx_trainer_persona_user on trainer_persona(user_id);
create index if not exists idx_group_chat_profiles_user on group_chat_profiles(owner_user_id);
