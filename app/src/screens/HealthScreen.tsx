/**
 * HealthScreen — Health & Training dashboard.
 *
 * Two tabs: Nutrition (food log, calories, streak) and Training (sessions, PRs).
 * Food can be logged from either WhatsApp or directly here.
 */
import React, { useEffect, useState, useCallback } from 'react';
import {
  View, Text, ScrollView, StyleSheet, TextInput,
  TouchableOpacity, Alert, ActivityIndicator, RefreshControl,
  KeyboardAvoidingView, Platform, FlatList,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { getHealthSummary, logFood, getTrainingSessions, getTrainerStats } from '../api';
import type { HealthSummary, TrainingSession } from '../types';
import { COLORS, FONTS, CARD } from '../theme';

type Tab = 'nutrition' | 'training';

export default function HealthScreen() {
  const [userId, setUserId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>('nutrition');

  useEffect(() => {
    AsyncStorage.getItem('pg_user_id').then((id) => { if (id) setUserId(id); });
  }, []);

  return (
    <View style={s.root}>
      {/* Tab bar */}
      <View style={s.tabBar}>
        <TabPill label="Nutrition" active={tab === 'nutrition'} onPress={() => setTab('nutrition')} />
        <TabPill label="Training"  active={tab === 'training'}  onPress={() => setTab('training')}  />
      </View>

      {tab === 'nutrition' && userId && <NutritionTab userId={userId} />}
      {tab === 'training'  && userId && <TrainingTab  userId={userId} />}
      {!userId && <View style={s.center}><ActivityIndicator color={COLORS.accent} /></View>}
    </View>
  );
}

// ── Tab pill ──────────────────────────────────────────────────────────────────

function TabPill({ label, active, onPress }: { label: string; active: boolean; onPress: () => void }) {
  return (
    <TouchableOpacity
      style={[s.pill, active && s.pillActive]}
      onPress={onPress}
      activeOpacity={0.7}
    >
      <Text style={[s.pillText, active && s.pillTextActive]}>{label}</Text>
    </TouchableOpacity>
  );
}

// ── Nutrition tab ─────────────────────────────────────────────────────────────

function NutritionTab({ userId }: { userId: string }) {
  const [health, setHealth]       = useState<HealthSummary | null>(null);
  const [loading, setLoading]     = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [foodInput, setFoodInput] = useState('');
  const [logging, setLogging]     = useState(false);
  const [lastAck, setLastAck]     = useState<string | null>(null);

  const load = useCallback(async () => {
    try { setHealth(await getHealthSummary(userId)); } catch (_) {}
  }, [userId]);

  useEffect(() => {
    setLoading(true);
    load().finally(() => setLoading(false));
  }, [load]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }, [load]);

  async function handleLogFood() {
    if (!foodInput.trim()) return;
    setLogging(true);
    try {
      const res = await logFood(userId, foodInput.trim());
      setFoodInput('');
      setLastAck(res.acknowledgment ?? `Logged — ${Math.round(res.total_calories)} cal`);
      await load();
    } catch (e: any) {
      Alert.alert('Could not log', e.message ?? 'Try again.');
    } finally {
      setLogging(false);
    }
  }

  if (loading) return <View style={s.center}><ActivityIndicator color={COLORS.accent} /></View>;

  const today = health?.today;
  const days  = health?.days_logging ?? 0;

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView
        style={s.scroll}
        contentContainerStyle={s.content}
        keyboardShouldPersistTaps="handled"
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={COLORS.accent} />}
      >
        <Text style={s.heading}>Nutrition</Text>

        {/* Today stats */}
        <View style={s.statsRow}>
          <BigStat value={today?.total_calories ? Math.round(today.total_calories).toString() : '—'} unit="cal" />
          <BigStat value={today?.total_protein  ? `${Math.round(today.total_protein)}g`          : '—'} unit="protein" />
          <BigStat value={today?.trained ? '✓' : '—'} unit="trained" accent={!!today?.trained} />
        </View>

        {/* Habit streak */}
        {days > 0 && (
          <View style={[CARD, s.habitCard]}>
            <Text style={s.habitText}>
              {health?.habit_established
                ? `Habit established — ${days} days of logging.`
                : `Day ${days} of ${Math.max(7, days)}. ${Math.max(0, 7 - days)} more to lock in the habit.`}
            </Text>
          </View>
        )}

        {/* Log food */}
        <Text style={s.sectionLabel}>Log food</Text>
        {lastAck && (
          <View style={[CARD, s.ackCard]}>
            <Text style={s.ackText}>{lastAck}</Text>
          </View>
        )}
        <View style={s.logRow}>
          <TextInput
            style={s.logInput}
            placeholder="e.g. grilled chicken and rice"
            placeholderTextColor={COLORS.muted}
            value={foodInput}
            onChangeText={setFoodInput}
            returnKeyType="send"
            onSubmitEditing={handleLogFood}
            editable={!logging}
          />
          <TouchableOpacity
            style={[s.logBtn, (!foodInput.trim() || logging) && { opacity: 0.4 }]}
            onPress={handleLogFood}
            disabled={!foodInput.trim() || logging}
          >
            {logging
              ? <ActivityIndicator color={COLORS.bg} size="small" />
              : <Text style={s.logBtnText}>Log</Text>}
          </TouchableOpacity>
        </View>
        <Text style={s.logHint}>You can also text Genie on WhatsApp — same data.</Text>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

// ── Training tab ──────────────────────────────────────────────────────────────

function TrainingTab({ userId }: { userId: string }) {
  const [sessions, setSessions] = useState<TrainingSession[]>([]);
  const [stats, setStats]       = useState<any>(null);
  const [loading, setLoading]   = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [sess, st] = await Promise.all([
        getTrainingSessions(userId),
        getTrainerStats(userId),
      ]);
      setSessions(sess);
      setStats(st);
    } catch (_) {}
  }, [userId]);

  useEffect(() => {
    setLoading(true);
    load().finally(() => setLoading(false));
  }, [load]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }, [load]);

  if (loading) return <View style={s.center}><ActivityIndicator color={COLORS.accent} /></View>;

  return (
    <ScrollView
      style={s.scroll}
      contentContainerStyle={s.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={COLORS.accent} />}
    >
      <Text style={s.heading}>Training</Text>

      {/* Stats bar */}
      {stats && (
        <View style={s.statsRow}>
          <BigStat value={stats.sessions_this_week?.toString() ?? '—'} unit="this week" />
          <BigStat value={stats.sessions_this_month?.toString() ?? '—'} unit="this month" />
          <BigStat
            value={stats.total_volume_this_month
              ? `${Math.round(stats.total_volume_this_month / 1000)}k`
              : '—'}
            unit="kg vol"
          />
        </View>
      )}

      {/* PRs */}
      {stats?.personal_records?.length > 0 && (
        <>
          <Text style={s.sectionLabel}>Personal Records</Text>
          {stats.personal_records.slice(0, 3).map((pr: any, i: number) => (
            <View key={i} style={[CARD, s.prRow]}>
              <View style={{ flex: 1 }}>
                <Text style={FONTS.sub}>{pr.exercise.replace(/_/g, ' ')}</Text>
                <Text style={FONTS.label}>{new Date(pr.date).toLocaleDateString()}</Text>
              </View>
              <Text style={s.prWeight}>{pr.weight_kg} kg</Text>
            </View>
          ))}
        </>
      )}

      {/* Session history */}
      <Text style={s.sectionLabel}>Sessions</Text>
      {sessions.length === 0 ? (
        <View style={[CARD, s.emptyCard]}>
          <Text style={s.emptyText}>
            No sessions yet.{'\n'}Say "starting session" to Genie on WhatsApp, then send a voice note when you're done.
          </Text>
        </View>
      ) : (
        sessions.map((sess) => (
          <TouchableOpacity
            key={sess.id}
            onPress={() => setExpanded(expanded === sess.id ? null : sess.id)}
            activeOpacity={0.8}
          >
            <View style={[CARD, s.sessionCard]}>
              <View style={s.sessionHeader}>
                <View style={{ flex: 1 }}>
                  <Text style={FONTS.sub}>
                    {new Date(sess.session_date).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })}
                  </Text>
                  <Text style={FONTS.label}>
                    {sess.exercises?.length ?? 0} exercises
                    {sess.duration_minutes ? ` · ${sess.duration_minutes} min` : ''}
                    {sess.calories_burned ? ` · ${sess.calories_burned} cal` : ''}
                  </Text>
                </View>
                <Text style={s.chevron}>{expanded === sess.id ? '↑' : '↓'}</Text>
              </View>

              {expanded === sess.id && (
                <View style={s.sessionBody}>
                  {sess.summary ? (
                    <Text style={[FONTS.body, s.summaryText]}>{sess.summary}</Text>
                  ) : null}
                  {sess.exercises?.map((ex, ei) => (
                    <View key={ei} style={s.exerciseRow}>
                      <Text style={s.exName}>{ex.name.replace(/_/g, ' ')}</Text>
                      <Text style={s.exSets}>
                        {ex.sets?.map((set) => `${set.reps}×${set.weight_kg}kg`).join('  ') || '—'}
                      </Text>
                    </View>
                  ))}
                  {sess.trainer_notes ? (
                    <Text style={[FONTS.label, { marginTop: 8, lineHeight: 18 }]}>
                      📝 {sess.trainer_notes}
                    </Text>
                  ) : null}
                </View>
              )}
            </View>
          </TouchableOpacity>
        ))
      )}
    </ScrollView>
  );
}

// ── Shared components ─────────────────────────────────────────────────────────

function BigStat({ value, unit, accent }: { value: string; unit: string; accent?: boolean }) {
  return (
    <View style={s.bigTile}>
      <Text style={[s.bigValue, accent && { color: COLORS.success }]}>{value}</Text>
      <Text style={s.bigUnit}>{unit}</Text>
    </View>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────

const s = StyleSheet.create({
  root:        { flex: 1, backgroundColor: COLORS.bg },
  scroll:      { flex: 1 },
  content:     { padding: 20, paddingBottom: 40 },
  center:      { flex: 1, justifyContent: 'center', alignItems: 'center' },
  heading:     { ...FONTS.heading, marginBottom: 20, marginTop: 60 },
  sectionLabel:{ ...FONTS.label, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 10, marginTop: 8 },

  // Tab bar
  tabBar:      {
    flexDirection: 'row', paddingHorizontal: 20, paddingTop: 16,
    paddingBottom: 4, gap: 8, backgroundColor: COLORS.bg,
  },
  pill:        {
    flex: 1, paddingVertical: 8, borderRadius: 20,
    backgroundColor: COLORS.surface,
    alignItems: 'center',
    borderWidth: 1, borderColor: COLORS.border,
  },
  pillActive:  { backgroundColor: COLORS.accent + '22', borderColor: COLORS.accent },
  pillText:    { ...FONTS.label, fontWeight: '600' },
  pillTextActive: { color: COLORS.accent },

  // Stats
  statsRow:    { flexDirection: 'row', gap: 10, marginBottom: 16 },
  bigTile:     {
    flex: 1, backgroundColor: COLORS.surface, borderRadius: 14,
    padding: 14, alignItems: 'center',
    borderWidth: 1, borderColor: COLORS.border,
  },
  bigValue:    { ...FONTS.sub, fontSize: 22, marginBottom: 2 },
  bigUnit:     { ...FONTS.label },

  // Nutrition
  habitCard:   { marginBottom: 24 },
  habitText:   { ...FONTS.body, color: COLORS.muted, lineHeight: 20 },
  ackCard:     {
    backgroundColor: COLORS.accent + '22',
    borderLeftWidth: 3, borderLeftColor: COLORS.accent,
    marginBottom: 10,
  },
  ackText:     { ...FONTS.body },
  logRow:      { flexDirection: 'row', gap: 10 },
  logInput:    {
    flex: 1, backgroundColor: COLORS.surface, borderRadius: 12,
    padding: 14, fontSize: 15, color: COLORS.text,
    borderWidth: 1, borderColor: COLORS.border,
  },
  logBtn:      {
    backgroundColor: COLORS.accent, borderRadius: 12,
    paddingHorizontal: 18, justifyContent: 'center', alignItems: 'center',
  },
  logBtnText:  { color: COLORS.bg, fontWeight: '700', fontSize: 15 },
  logHint:     { ...FONTS.label, marginTop: 10, lineHeight: 18 },

  // Training
  prRow:       { flexDirection: 'row', alignItems: 'center' },
  prWeight:    { ...FONTS.sub, color: COLORS.accent, fontSize: 18 },
  sessionCard: { borderLeftWidth: 3, borderLeftColor: COLORS.border },
  sessionHeader: { flexDirection: 'row', alignItems: 'center' },
  chevron:     { color: COLORS.muted, fontSize: 16, paddingLeft: 8 },
  sessionBody: { marginTop: 12, paddingTop: 12, borderTopWidth: 1, borderTopColor: COLORS.border },
  summaryText: { marginBottom: 12, lineHeight: 22, color: COLORS.muted },
  exerciseRow: { marginBottom: 8 },
  exName:      { ...FONTS.body, fontWeight: '600', textTransform: 'capitalize' },
  exSets:      { ...FONTS.label, marginTop: 2 },
  emptyCard:   { alignItems: 'center', paddingVertical: 28 },
  emptyText:   { ...FONTS.body, color: COLORS.muted, textAlign: 'center', lineHeight: 22 },
});
