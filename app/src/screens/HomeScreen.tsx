/**
 * HomeScreen — Ambient daily view.
 *
 * Header: time-based greeting + lamp.
 * Feed: pending Genie moments, each with a person + suggestion.
 * Bottom: today's health snapshot tiles.
 */
import React, { useEffect, useState, useCallback, useRef } from 'react';
import {
  View, Text, ScrollView, StyleSheet,
  RefreshControl, ActivityIndicator, TouchableOpacity,
  Animated,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { getMoments, getHealthSummary } from '../api';
import type { Moment, HealthSummary } from '../types';
import { COLORS, FONTS, CARD, SPACING, RADIUS, SHADOW } from '../theme';

export default function HomeScreen() {
  const [userId, setUserId]     = useState<string | null>(null);
  const [userName, setUserName] = useState('');
  const [moments, setMoments]   = useState<Moment[]>([]);
  const [health, setHealth]     = useState<HealthSummary | null>(null);
  const [loading, setLoading]   = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const fadeAnim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Promise.all([
      AsyncStorage.getItem('pg_user_id'),
      AsyncStorage.getItem('pg_user_name'),
    ]).then(([id, name]) => {
      if (id)   setUserId(id);
      if (name) setUserName(name);
    });
  }, []);

  const load = useCallback(async (uid: string) => {
    try {
      const [m, h] = await Promise.all([getMoments(uid), getHealthSummary(uid)]);
      setMoments(m);
      setHealth(h);
    } catch (_) {}
  }, []);

  useEffect(() => {
    if (!userId) return;
    setLoading(true);
    load(userId).finally(() => {
      setLoading(false);
      Animated.timing(fadeAnim, {
        toValue: 1, duration: 600, useNativeDriver: true,
      }).start();
    });
  }, [userId, load, fadeAnim]);

  const onRefresh = useCallback(async () => {
    if (!userId) return;
    setRefreshing(true);
    await load(userId);
    setRefreshing(false);
  }, [userId, load]);

  if (loading) {
    return (
      <View style={s.center}>
        <ActivityIndicator color={COLORS.accent} size="large" />
      </View>
    );
  }

  const today   = health?.today;
  const greeting = getGreeting(userName);

  return (
    <Animated.View style={[s.root, { opacity: fadeAnim }]}>
      <ScrollView
        style={s.scroll}
        contentContainerStyle={s.content}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor={COLORS.accent}
          />
        }
      >
        {/* ── Header ── */}
        <View style={s.header}>
          <View>
            <Text style={s.greetingText}>{greeting}</Text>
            {moments.length > 0 && (
              <Text style={s.headerSub}>
                {moments.length === 1
                  ? 'Genie noticed something worth your attention.'
                  : `Genie has ${moments.length} things worth your attention.`}
              </Text>
            )}
          </View>
          <Text style={s.lamp}>🪔</Text>
        </View>

        {/* ── Moments feed ── */}
        {moments.length === 0 ? (
          <EmptyMoments />
        ) : (
          moments.slice(0, 5).map((m, i) => (
            <MomentCard key={m.id} moment={m} isTop={i === 0} />
          ))
        )}

        {/* ── Health snapshot ── */}
        {(today || health) && (
          <>
            <View style={s.sectionRow}>
              <Text style={s.sectionLabel}>TODAY</Text>
              {health && health.days_logging > 0 && (
                <Text style={s.streakText}>
                  {health.habit_established
                    ? `${health.days_logging}-day streak`
                    : `Day ${health.days_logging}`}
                </Text>
              )}
            </View>
            <View style={s.healthRow}>
              <HealthTile
                value={today?.total_calories ? `${Math.round(today.total_calories)}` : '—'}
                unit="cal"
              />
              <HealthTile
                value={today?.total_protein ? `${Math.round(today.total_protein)}g` : '—'}
                unit="protein"
              />
              <HealthTile
                value={today?.trained ? '✓' : '—'}
                unit="trained"
                highlight={today?.trained}
              />
            </View>
          </>
        )}

        <View style={{ height: SPACING.xxxl }} />
      </ScrollView>
    </Animated.View>
  );
}

function MomentCard({ moment, isTop }: { moment: Moment; isTop: boolean }) {
  return (
    <View style={[s.momentCard, isTop && s.momentCardTop, isTop && SHADOW.gold]}>
      {/* Person row */}
      <View style={s.momentPersonRow}>
        <View style={s.momentAvatar}>
          <Text style={s.momentAvatarText}>
            {moment.people?.name?.[0]?.toUpperCase() ?? '?'}
          </Text>
        </View>
        <View style={s.momentPersonInfo}>
          <Text style={s.momentPersonName}>
            {moment.people?.name ?? 'Someone close to you'}
          </Text>
          <Text style={s.momentTrigger}>{triggerLabel(moment.triggered_by)}</Text>
        </View>
      </View>

      {/* Suggestion */}
      <Text style={[s.momentSuggestion, isTop && s.momentSuggestionTop]}>
        {moment.suggestion}
      </Text>
    </View>
  );
}

function EmptyMoments() {
  const pulseAnim = useRef(new Animated.Value(0.6)).current;

  useEffect(() => {
    Animated.loop(
      Animated.sequence([
        Animated.timing(pulseAnim, { toValue: 1,   duration: 1800, useNativeDriver: true }),
        Animated.timing(pulseAnim, { toValue: 0.6, duration: 1800, useNativeDriver: true }),
      ])
    ).start();
  }, [pulseAnim]);

  return (
    <View style={s.emptyWrap}>
      <Animated.Text style={[s.emptyLamp, { opacity: pulseAnim }]}>🪔</Animated.Text>
      <Text style={s.emptyHeadline}>Still learning your world.</Text>
      <Text style={s.emptyBody}>
        Genie is reading your connections.{'\n'}Something worth your attention will appear here.
      </Text>
    </View>
  );
}

function HealthTile({
  value, unit, highlight,
}: { value: string; unit: string; highlight?: boolean }) {
  return (
    <View style={[s.healthTile, highlight && s.healthTileHighlight]}>
      <Text style={[s.healthValue, highlight && s.healthValueHighlight]}>{value}</Text>
      <Text style={s.healthUnit}>{unit}</Text>
    </View>
  );
}

function getGreeting(name: string): string {
  const h = new Date().getHours();
  const first = name.split(' ')[0];
  const suffix = first ? `, ${first}.` : '.';
  if (h < 12) return `Good morning${suffix}`;
  if (h < 17) return `Good afternoon${suffix}`;
  if (h < 21) return `Good evening${suffix}`;
  return `Hey${suffix}`;
}

function triggerLabel(triggeredBy: string): string {
  const map: Record<string, string> = {
    life_event:       'Upcoming event',
    drift_detection:  'Time to reconnect',
    message_analysis: 'From your conversations',
    google_ingestion: 'Relationship insight',
    birthday_prep:    'Birthday coming up',
  };
  return map[triggeredBy] ?? 'Genie noticed';
}

const s = StyleSheet.create({
  root:    { flex: 1, backgroundColor: COLORS.bg },
  scroll:  { flex: 1 },
  content: { padding: SPACING.xl, paddingTop: 64 },
  center:  { flex: 1, backgroundColor: COLORS.bg, justifyContent: 'center', alignItems: 'center' },

  // Header
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: SPACING.xl,
  },
  greetingText: {
    ...FONTS.display,
    fontSize: 26,
    marginBottom: 6,
  },
  headerSub: {
    ...FONTS.label,
    lineHeight: 18,
    maxWidth: 240,
  },
  lamp: { fontSize: 28, marginTop: 2 },

  // Moment cards
  momentCard: {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    padding: SPACING.lg,
    marginBottom: SPACING.md,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  momentCardTop: {
    borderColor: COLORS.accentBorder,
    borderWidth: 1,
  },
  momentPersonRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: SPACING.md,
    gap: SPACING.sm,
  },
  momentAvatar: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: COLORS.accentDim,
    borderWidth: 1,
    borderColor: COLORS.accentBorder,
    justifyContent: 'center',
    alignItems: 'center',
  },
  momentAvatarText: {
    color: COLORS.accent,
    fontWeight: '700',
    fontSize: 15,
  },
  momentPersonInfo: { flex: 1 },
  momentPersonName: { ...FONTS.sub, fontSize: 15 },
  momentTrigger:    { ...FONTS.caption, marginTop: 1, color: COLORS.accent, textTransform: 'uppercase', letterSpacing: 0.8 },
  momentSuggestion: {
    ...FONTS.body,
    lineHeight: 23,
    color: COLORS.textSecondary,
  },
  momentSuggestionTop: {
    color: COLORS.text,
    fontSize: 16,
    lineHeight: 25,
  },

  // Empty
  emptyWrap: {
    alignItems: 'center',
    paddingVertical: SPACING.hero,
    paddingHorizontal: SPACING.xl,
  },
  emptyLamp:     { fontSize: 44, marginBottom: SPACING.lg },
  emptyHeadline: { ...FONTS.sub, textAlign: 'center', marginBottom: SPACING.sm },
  emptyBody:     { ...FONTS.body, color: COLORS.textSecondary, textAlign: 'center', lineHeight: 24 },

  // Health
  sectionRow:    { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: SPACING.sm },
  sectionLabel:  { ...FONTS.caption, textTransform: 'uppercase', letterSpacing: 1.2 },
  streakText:    { ...FONTS.caption, color: COLORS.accent },
  healthRow:     { flexDirection: 'row', gap: SPACING.sm, marginBottom: SPACING.lg },
  healthTile:    {
    flex: 1,
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.md,
    padding: SPACING.md,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  healthTileHighlight: {
    borderColor: COLORS.accentBorder,
    backgroundColor: COLORS.accentDim,
  },
  healthValue:          { ...FONTS.sub, fontSize: 20, marginBottom: 3 },
  healthValueHighlight: { color: COLORS.accent },
  healthUnit:           { ...FONTS.caption },
});
