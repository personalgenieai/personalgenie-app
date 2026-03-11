# PersonalGenie — Product Requirements Document v8
## Complete Build Bible

---

# PART ONE: THE SOUL

## 1. What PersonalGenie Is

PersonalGenie is a single continuously evolving personal intelligence. It begins by understanding the user's relationships. Over time, as it observes patterns and builds genuine trust, it quietly expands into every area of the user's personal life — financial health, physical wellbeing, home automation, daily rituals, and the rules by which they want to live.

There are no modes. There are no features to activate. There are no apps to install. There is only Genie — one intelligence that knows more about this person with every passing week, becoming more capable without ever becoming intrusive.

The long-term vision: PersonalGenie becomes the most complete record of who a person is. Their relationships. Their values. Their memories. Their voice. Their way of seeing the world.

## 2. The Brand

**Name:** PersonalGenie. The intelligence is Genie. When Genie speaks, it is Genie speaking — never "the AI," never "the assistant."

**Color palette:**
- Primary Background: #0A0A0F
- Accent Gold: #C9A84C
- Accent Glow: #E8D5A3
- Surface: #12121A
- Surface Elevated: #1A1A26
- Text Primary: #F5F0E8
- Text Secondary: #8A8070
- Text Tertiary: #4A4438
- Success: #4CAF7D
- Destructive: #C44B4B

**Typography:** Display: Canela (fallback: Georgia Italic). Body/UI: Inter. Mono: JetBrains Mono.

**Spacing:** 4px base unit. Multiples of 4: 4, 8, 12, 16, 24, 32, 48, 64, 96.

**Border radius:** 16px cards, 12px inputs, 8px small, 24px large sheets.

**The Genie Particle System:** Gold particles drift upward whenever Genie is thinking. 8–15 particles maximum. Never distracting.

**Motion:** Transitions 400–600ms. Spring physics. Elements enter from below, fade in. Exit upward, fade out.

**The Lamp:** PersonalGenie's logo is an antique oil lamp — simple, clean, gold line art on dark background.

## 3. Genie's Voice

Every word Genie produces must conform to these guidelines.

**Tone:** Warm but never gushing. Direct but never cold. Personal but never invasive. Confident but never presumptuous.

**Forbidden phrases:**
- "I noticed from your messages"
- "Based on your data"
- "According to my analysis"
- "As an AI"
- "Optimize" / "Leverage"
- "Hey there!" with exclamation
- "Is there anything else I can help you with?"
- Any corporate language
- Any reference to work

**The silence principle:** When Genie has nothing worth saying, it says nothing.

---

# PART TWO: HARD BOUNDARIES

## 4. Work Exclusion

PersonalGenie is a personal life intelligence. Work data never enters the system. Enforced at the data layer.

What counts as work: work emails, work calendar events, professional-only iMessage/WhatsApp conversations, Maps visits to workplace during work hours.

Explicitly included: friends who are also colleagues (if conversation is personal), after-work social events, personal messages about work stress, side projects, work friends discussing non-work topics.

All data passes through WorkFilter before any processing. WorkFilter outputs: personal, work, or ambiguous. Work and ambiguous are discarded.

Settings → Privacy → "What Genie skips" shows counts only — never content.

---

# PART THREE: ALL CONNECTIONS

## 5. Data Connections

### 5.1 Google Suite
Gmail, Google Photos, Google Calendar (personal only), Google Maps.

### 5.2 iMessage
iOS (Messages entitlement). Mac companion app (Phase 2). All processing local — only extracted patterns sent to backend.

### 5.3 iCalendar
Calendar selection during setup. User chooses which calendars to include.

### 5.4 WhatsApp
Primary interface. First-class message source.

### 5.5 Music — Apple Music and Spotify

Both supported. User can connect either or both. If both connected, Genie merges listening data into unified music profile.

**Apple Music:** MusicKit framework. Read access to listening history, library, playback state. Genie can play music via MusicKit, route to Apple TV via AirPlay, route to Bluetooth speaker.

**Spotify:** OAuth 2.0 with PKCE. Scopes: user-read-recently-played, user-read-playback-state, user-modify-playback-state, user-read-currently-playing, user-library-read, playlist-read-private, user-top-artists-and-tracks.

Spotify can: play on any Spotify Connect device (including Apple TV, Bluetooth speakers), pause/resume/skip/volume control, queue tracks, target specific devices by name.

Audio features (valence, energy, danceability) used for mood inference.

**Music Provider Abstraction:** All music actions in codebase go through unified MusicProvider interface. Prefers Spotify when both connected (better device targeting). Falls back to Apple Music. World Model always includes music emotional context when either provider is connected.

### 5.6 Apple TV
pyatv. Macro recording system. Full device control.

### 5.7 Bluetooth Speaker
CoreBluetooth detection. User names each speaker. TTS output for Genie voice. Spotify Connect targeting for music.

### 5.8 Plaid (Financial)
Read-only. Never write. Never transfers.

### 5.9 Readwise
Books, articles, highlights. Intellectual capability (Phase 2).

### 5.10 Reddit
Personal interest signals. Intellectual capability (Phase 2). Work subreddits excluded.

---

# PART FOUR: INGESTION PROGRESS

## 7. Ingestion Progress System

When a user connects a data source, Genie processes years of history. Real-time progress — not a spinner.

WhatsApp: max 5 messages during ingestion. At 0%, 20%, 80%, 100%.

iOS: Full-screen progress view. Per-source progress rows with activity text. Live insights feed below. Completion: bars fill, brief gold light, three real insights shown.

Activity text in Genie's voice: "Reading your messages from 2021" not "Processing batch 47."

WebSocket endpoint: /ws/ingestion/{session_id} — broadcasts progress events to iOS.

---

# PART FIVE: THE EXPERIENCE

## 9. WhatsApp Onboarding — Five Messages

Message 1: "I've been waiting for you..." → asks for name.
Message 2: Uses name, asks who they most want to stay closer to.
Message 3: Offers Google connection or asks for a story about the person.
Message 4a (Google connected): Ingestion milestone updates then real first insight.
Message 4b (story given): Reflects back specifically, asks about notification preference.
Message 5: "Your Genie is ready." — explains WhatsApp as primary, voice notes work, can tell Genie anything.

Work disclosure (sent once after first insight): "One thing worth knowing: I only look at your personal life. Work emails, work meetings, anything professional — I skip all of it."

## 10. iOS App

### iOS Onboarding — Nine Screens + Ingestion Progress Screen

Screen 1: Introduction — lamp, particles, "Your Genie is here."
Screen 2: Name — minimal input, gold cursor.
Screen 3: First relationship — who matters most.
Screen 4: Connect sources — toggles for Google (shared OAuth), iMessage, Apple Calendar, Apple Music, Spotify.
Screen 5: Apple permissions — Health, Location.
Screen 6: Notification preference — Mornings, Evenings, When it matters.
Screen 7: WhatsApp + Bluetooth speakers.
Screen 8: First Genie moment — real insight from actual data.
Screen 9: Ready — gold atmospheric, lamp flares, "Your Genie is ready."

Ingestion Progress Screen: between Screen 4 and Screen 8. Full-screen. Real-time WebSocket updates.

### iOS Dashboard — Five Tabs

Tab 1 Home: Ambient header, feed of moment cards.
Tab 2 People: List by recency × closeness. Relationship Card sheet on tap.
Tab 3 Chat: Full-screen conversation with Genie. Gold thinking dots. Voice notes via mic.
Tab 4 Rules: Rule list with trigger/action in plain English. Floating create button.
Tab 5 Settings: Connections (Google, iMessage, Apple Calendar, Apple Health, Apple Music, Spotify, WhatsApp, Financial, Bluetooth Speakers), Privacy, Capabilities.

---

# PART SIX: THE INTELLIGENCE

## 11. Technical Stack

Python FastAPI. Railway. Twilio WhatsApp Business API. Supabase PostgreSQL. Claude claude-sonnet-4-5. OpenAI Whisper. SwiftUI iOS. Stripe. Plaid. Apple: HealthKit, MusicKit, EventKit, CoreBluetooth. Google APIs. Spotify Web API + iOS SDK. pyatv. WebSocket for ingestion progress.

## 14. Policy Engine

Policies: stop_revocation, data_minimization, capability_offer_consent, financial_data_scope, nightly_opt_out, prompt_injection_safety, rule_rate_limit, cascade_protection, work_data_exclusion, music_data_scope.

music_data_scope: Music data used only for personal emotional context and playback. Never used to infer work patterns.

## 15. Genie Rule Engine

Trigger types: time, incoming_message, calendar_event, calendar_free, transaction, music_playing, health_metric, genie_observation, rule_fired.

Action types: send_whatsapp, claude_analysis, device_command, play_music, start_conversation, log_data, send_reminder, update_world_model, notify_ios, speak_on_speaker.

play_music action: { "type": "play_music", "parameters": { "query": "my wind-down playlist", "device_name": "living room speaker", "provider_preference": "spotify" } }

Rules created through natural language conversation. Claude parses to structured object. Always confirms in plain English before activating.

## 17. Capability Lifecycle

Eight areas: financial, physical, professional, coordination, communication, intellectual, family, emotional.
Five stages: 0 unaware → 1 observing → 2 ready → 3 offered → 4 active learning → 5 ambient.
Signal threshold: 0.70. Trust threshold: 0.60. Minimum days: 14. Minimum interactions: 20. Max offers/month: 1. Decline cooldown: 90 days.

Music: automatically Stage 5 (ambient) once either provider connected. No learning questions needed.

## 23. Monetization

Free: 1 source, 10 people, 2 moments/day, 30-day history.
Individual $9.99/month: all sources including both music providers, unlimited people, 5 moments/day, full history, all capabilities, 5 active rules.
Family $14.99/month: 6 seats, bilateral graph, 15 rules/person.
Genie Pro $24.99/month: everything + unlimited rules + trainer persona + 7-year history.

14-day free trial. No credit card.

## 27. Build Sequence

1. Supabase schema — all tables, indexes, RLS
2. Policy Engine — all policies including work exclusion and music scope
3. WorkFilter — full implementation, 50-example test suite
4. Security architecture — encryption, JWT, rate limiting, PKCE
5. FastAPI skeleton — all endpoints stubbed, WebSocket stubbed
6. World Model class — assembly, section update, Claude context string, music context
7. Google OAuth + ingestion with WorkFilter on all ingestion
8. Ingestion progress tracker — WebSocket broadcast, WhatsApp milestones
9. iMessage integration with WorkFilter
10. iCalendar integration with calendar selection UI
11. Spotify OAuth + SpotifyClient — token management, play, search, devices, listening history, audio features
12. Apple Music MusicKit integration
13. MusicProvider abstraction layer — unified interface, emotional context merger
14. WhatsApp webhook + consent + STOP revocation (<5 seconds)
15. Message processing pipeline + Communication DNA + Linguistic Intimacy
16. Capability Lifecycle Engine
17. Core Genie conversation handler — full World Model injection including music context
18. WhatsApp onboarding — five messages exactly as specified
19. iOS onboarding — nine screens + ingestion progress screen
20. iOS dashboard — all five tabs
21. Financial capability — Plaid, transaction evaluation, learning loop
22. Health capability — nutrition logging, trainer detection, session intelligence
23. Nightly conversation engine
24. Bluetooth speaker connection + TTS routing
25. Apple TV control — pyatv, macro recording
26. Genie Rule Engine — all trigger/action types including music
27-35. iMessage Mac, Apple Music deep integration, interest graph, life events, billing, multilanguage, error audit, tests, App Store

## 29. Non-Negotiable Principles

There are no modes. There are no features to activate. There is only Genie.
Genie never cites its sources. It simply knows.
Genie only speaks when silence would cost the user something.
Work data never enters the system. Period.
Music context is always in the World Model when either music provider is connected.
Rules are defined in natural language. Never in code. Never in a form.
The visual design is dark, gold, warm, and slow.
Every word Genie writes is earned. Silence is the default. Speech is the exception.
The product is a Genie. Build it like one.

---
*PersonalGenie PRD v8 — Supersedes all previous versions.*
