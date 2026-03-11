/**
 * PersonalGenie API client.
 *
 * Base URL: stored in AsyncStorage (defaults to Railway production URL).
 * Auth: X-App-Token header, set after OTP verification.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';
import type { User, Person, Moment, HealthSummary } from './types';

const STORAGE_BASE_URL = 'pg_base_url';
const STORAGE_TOKEN    = 'pg_app_token';
const STORAGE_USER_ID  = 'pg_user_id';
const STORAGE_NAME     = 'pg_user_name';

const DEFAULT_BASE_URL = 'https://marty-unfocusing-latoya.ngrok-free.dev';

// ── Storage helpers ──────────────────────────────────────────────────────────

export async function getBaseUrl(): Promise<string> {
  return (await AsyncStorage.getItem(STORAGE_BASE_URL)) ?? DEFAULT_BASE_URL;
}

export async function saveSession(userId: string, name: string, token: string): Promise<void> {
  await Promise.all([
    AsyncStorage.setItem(STORAGE_USER_ID, userId),
    AsyncStorage.setItem(STORAGE_NAME, name),
    AsyncStorage.setItem(STORAGE_TOKEN, token),
  ]);
}

export async function clearSession(): Promise<void> {
  await Promise.all([
    AsyncStorage.removeItem(STORAGE_USER_ID),
    AsyncStorage.removeItem(STORAGE_NAME),
    AsyncStorage.removeItem(STORAGE_TOKEN),
  ]);
}

export async function getStoredSession(): Promise<{ userId: string; name: string; token: string } | null> {
  const [userId, name, token] = await Promise.all([
    AsyncStorage.getItem(STORAGE_USER_ID),
    AsyncStorage.getItem(STORAGE_NAME),
    AsyncStorage.getItem(STORAGE_TOKEN),
  ]);
  if (userId && token) return { userId, name: name ?? '', token };
  return null;
}

// ── HTTP core ─────────────────────────────────────────────────────────────────

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  requireAuth = true,
): Promise<T> {
  const [base, token] = await Promise.all([
    getBaseUrl(),
    AsyncStorage.getItem(STORAGE_TOKEN),
  ]);

  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (requireAuth && token) headers['X-App-Token'] = token;

  const res = await fetch(`${base}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

// ── Auth ─────────────────────────────────────────────────────────────────────

export function requestOTP(phone: string): Promise<{ status: string }> {
  return request('POST', '/auth/app/request-otp', { phone }, false);
}

export function verifyOTP(
  phone: string,
  code: string,
): Promise<{ user_id: string; name: string; token: string }> {
  return request('POST', '/auth/app/verify-otp', { phone, code }, false);
}

export function getMe(): Promise<User> {
  return request('GET', '/auth/app/me', undefined, true);
}

// ── People ───────────────────────────────────────────────────────────────────

export async function getPeople(userId: string): Promise<Person[]> {
  const res = await request<{ people: Person[] }>('GET', `/people/${userId}`);
  return res.people;
}

export async function getPerson(userId: string, personId: string): Promise<Person> {
  return request<Person>('GET', `/people/${userId}/${personId}`);
}

// ── Moments ──────────────────────────────────────────────────────────────────

export async function getMoments(userId: string): Promise<Moment[]> {
  const res = await request<{ moments: Moment[] }>('GET', `/people/${userId}/moments`);
  return res.moments;
}

// ── Health ───────────────────────────────────────────────────────────────────

export function getHealthSummary(userId: string): Promise<HealthSummary> {
  return request<HealthSummary>('GET', `/health/summary/${userId}`);
}

export function logFood(
  userId: string,
  rawInput: string,
): Promise<{ acknowledgment: string | null; total_calories: number; total_protein: number }> {
  return request('POST', '/health/food-log', {
    user_id: userId,
    raw_input: rawInput,
    input_type: 'text',
  });
}

// ── Chat ──────────────────────────────────────────────────────────────────────

export async function sendChat(userId: string, message: string): Promise<string> {
  const res = await request<{ reply: string }>('POST', '/messages/ios-chat', {
    user_id: userId,
    message,
  });
  return res.reply;
}

// ── Rules ─────────────────────────────────────────────────────────────────────

export async function getRules(userId: string): Promise<import('./types').GenieRule[]> {
  const res = await request<{ rules: import('./types').GenieRule[] }>('GET', `/rules/${userId}`);
  return res.rules;
}

export async function createRule(
  userId: string,
  naturalLanguage: string,
): Promise<import('./types').GenieRule> {
  return request<import('./types').GenieRule>('POST', '/rules', {
    user_id: userId,
    natural_language: naturalLanguage,
  });
}

export async function deleteRule(userId: string, ruleId: string): Promise<void> {
  await request('DELETE', `/rules/${ruleId}`, { user_id: userId });
}

// ── Spotify ───────────────────────────────────────────────────────────────────

export async function getSpotifyConnectUrl(): Promise<{ auth_url: string }> {
  return request<{ auth_url: string }>('GET', '/spotify/connect');
}

export async function getSpotifyStatus(): Promise<{ connected: boolean; display_name?: string }> {
  return request<{ connected: boolean; display_name?: string }>('GET', '/spotify/status');
}

// ── Permissions ───────────────────────────────────────────────────────────────

export async function grantPermission(
  beneficiaryPhone: string,
  level: number,
  scope: string = 'wellbeing',
): Promise<{ status: string; description: string }> {
  return request('POST', '/permissions/grant', {
    beneficiary_phone: beneficiaryPhone,
    permission_level: level,
    scope,
  });
}

export async function getOutboundPermissions(): Promise<{ grants: any[] }> {
  return request('GET', '/permissions/outbound');
}

// ── Push notifications ────────────────────────────────────────────────────────

export async function registerPushToken(
  userId: string,
  deviceToken: string,
): Promise<{ status: string }> {
  return request('POST', '/push/register', {
    user_id: userId,
    device_token: deviceToken,
    platform: 'ios',
  });
}

// ── Billing ───────────────────────────────────────────────────────────────────

export interface Plan {
  id: string;
  name: string;
  price_monthly: number;
  features: string[];
}

export interface Subscription {
  plan: string;
  status: string;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
}

export async function getPlans(): Promise<Plan[]> {
  const res = await request<{ plans: Plan[] }>('GET', '/billing/plans', undefined, false);
  return res.plans;
}

export async function getSubscription(userId: string): Promise<Subscription> {
  return request<Subscription>('GET', `/billing/subscription/${userId}`);
}

export async function createCheckoutSession(
  userId: string,
  plan: string,
): Promise<{ checkout_url: string }> {
  const base = await getBaseUrl();
  return request('POST', '/billing/checkout', {
    user_id: userId,
    plan,
    success_url: `${base}/billing/success`,
    cancel_url: `${base}/billing/cancel`,
  });
}

export async function getBillingPortalUrl(userId: string): Promise<{ portal_url: string }> {
  const base = await getBaseUrl();
  return request('POST', '/billing/portal', {
    user_id: userId,
    return_url: base,
  });
}

// ── Trainer ───────────────────────────────────────────────────────────────────

export interface TrainingSession {
  id: string;
  session_date: string;
  duration_minutes: number | null;
  exercises: Array<{
    name: string;
    sets: Array<{ reps: number; weight_kg: number }>;
  }>;
  summary: string;
  trainer_notes: string;
  calories_burned: number | null;
}

export async function getTrainingSessions(userId: string): Promise<TrainingSession[]> {
  const res = await request<{ sessions: TrainingSession[] }>('GET', `/trainer/sessions/${userId}`);
  return res.sessions;
}

export async function getTrainerStats(userId: string): Promise<{
  sessions_this_month: number;
  sessions_this_week: number;
  favorite_exercise: string | null;
  total_volume_this_month: number;
  personal_records: Array<{ exercise: string; weight_kg: number; date: string }>;
}> {
  return request('GET', `/trainer/stats/${userId}`);
}

// ── Ingestion ─────────────────────────────────────────────────────────────────

export async function createIngestionSession(): Promise<{ session_id: string }> {
  return request('POST', '/ingestion/session', undefined, false);
}

export async function linkIngestionSession(
  userId: string,
  sessionId: string,
): Promise<void> {
  await request('POST', '/ingestion/link-user', { user_id: userId, session_id: sessionId }, false);
}

export async function getGoogleConnectUrl(): Promise<{ auth_url: string }> {
  return request('GET', '/auth/google/url');
}

export async function getPlaidLinkToken(userId: string): Promise<{ link_token: string }> {
  return request('POST', '/financial/link-token', { user_id: userId });
}

// ── Relationship Analysis ─────────────────────────────────────────────────────

export interface RelationshipInsights {
  summary: string;
  message_count: number | null;
  who_initiates: 'user' | 'them' | 'equal' | 'unknown';
  memories: string[];
  relationship_score: number | null;
  tip: string;
}

export async function analyzeRelationship(params: {
  userId: string;
  contactName: string;
  contactPhone: string;
  conversationText: string;
}): Promise<RelationshipInsights> {
  return request<RelationshipInsights>('POST', '/analyze/relationship', {
    user_id: params.userId,
    contact_name: params.contactName,
    contact_phone: params.contactPhone,
    conversation_text: params.conversationText,
  }, false);
}
