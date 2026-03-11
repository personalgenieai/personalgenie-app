/**
 * PeopleScreen — People Graph.
 *
 * Lists people ordered by closeness × recency.
 * Tap → bottom sheet with full profile, memories, and Genie's suggested moments.
 */
import React, { useEffect, useState, useCallback, useRef } from 'react';
import {
  View, Text, ScrollView, StyleSheet, TouchableOpacity,
  RefreshControl, ActivityIndicator, Modal, Pressable, Animated,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { getPeople, getPerson } from '../api';
import type { Person } from '../types';
import { COLORS, FONTS, SPACING, RADIUS, SHADOW } from '../theme';

export default function PeopleScreen() {
  const [userId, setUserId]   = useState<string | null>(null);
  const [people, setPeople]   = useState<Person[]>([]);
  const [selected, setSelected] = useState<Person | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const fadeAnim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    AsyncStorage.getItem('pg_user_id').then((id) => { if (id) setUserId(id); });
  }, []);

  const load = useCallback(async (uid: string) => {
    try {
      const p = await getPeople(uid);
      setPeople(p);
    } catch (_) {}
  }, []);

  useEffect(() => {
    if (!userId) return;
    setLoading(true);
    load(userId).finally(() => {
      setLoading(false);
      Animated.timing(fadeAnim, { toValue: 1, duration: 500, useNativeDriver: true }).start();
    });
  }, [userId, load, fadeAnim]);

  const onRefresh = useCallback(async () => {
    if (!userId) return;
    setRefreshing(true);
    await load(userId);
    setRefreshing(false);
  }, [userId, load]);

  async function openPerson(personId: string) {
    if (!userId) return;
    try {
      const full = await getPerson(userId, personId);
      setSelected(full);
    } catch (_) {}
  }

  if (loading) {
    return (
      <View style={s.center}>
        <ActivityIndicator color={COLORS.accent} size="large" />
      </View>
    );
  }

  return (
    <>
      <Animated.ScrollView
        style={[s.root, { opacity: fadeAnim }]}
        contentContainerStyle={s.content}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor={COLORS.accent}
          />
        }
      >
        <View style={s.header}>
          <Text style={s.heading}>Your world</Text>
          {people.length > 0 && (
            <Text style={s.headingCount}>{people.length}</Text>
          )}
        </View>

        {people.length === 0 ? (
          <EmptyPeople />
        ) : (
          people.map((p, i) => (
            <PersonCard
              key={p.id}
              person={p}
              index={i}
              onPress={() => openPerson(p.id)}
            />
          ))
        )}

        <View style={{ height: SPACING.xxxl }} />
      </Animated.ScrollView>

      <Modal
        visible={!!selected}
        animationType="slide"
        presentationStyle="pageSheet"
        onRequestClose={() => setSelected(null)}
      >
        {selected && (
          <PersonSheet person={selected} onClose={() => setSelected(null)} />
        )}
      </Modal>
    </>
  );
}

function PersonCard({
  person, index, onPress,
}: { person: Person; index: number; onPress: () => void }) {
  const isClose = (person.closeness_score ?? 0) >= 0.7;

  return (
    <TouchableOpacity onPress={onPress} activeOpacity={0.75}>
      <View style={[s.card, isClose && s.cardClose]}>
        <View style={s.cardRow}>
          {/* Avatar */}
          <View style={[s.avatar, isClose && s.avatarClose]}>
            <Text style={[s.avatarText, isClose && s.avatarTextClose]}>
              {person.name[0]?.toUpperCase()}
            </Text>
          </View>

          {/* Info */}
          <View style={s.cardInfo}>
            <Text style={s.personName}>{person.name}</Text>
            {person.relationship_type ? (
              <Text style={s.relType} numberOfLines={1}>{person.relationship_type}</Text>
            ) : null}
          </View>

          {/* Right: closeness + recency */}
          <View style={s.cardRight}>
            <ClosenessBar score={person.closeness_score ?? 0} />
            {person.last_meaningful_exchange && (
              <Text style={s.recency}>
                {daysSinceLabel(person.last_meaningful_exchange)}
              </Text>
            )}
          </View>
        </View>

        {/* Memory preview */}
        {person.memories?.[0]?.description && (
          <Text style={s.memoryPreview} numberOfLines={2}>
            "{person.memories[0].description}"
          </Text>
        )}
      </View>
    </TouchableOpacity>
  );
}

function ClosenessBar({ score }: { score: number }) {
  const total  = 5;
  const filled = Math.round(score * total);
  return (
    <View style={s.pips}>
      {Array.from({ length: total }).map((_, i) => (
        <View
          key={i}
          style={[
            s.pip,
            {
              backgroundColor: i < filled ? COLORS.accent : COLORS.border,
              opacity: i < filled ? (0.5 + (i / total) * 0.5) : 1,
            },
          ]}
        />
      ))}
    </View>
  );
}

function EmptyPeople() {
  return (
    <View style={s.emptyWrap}>
      <Text style={s.emptyLamp}>🪔</Text>
      <Text style={s.emptyHeadline}>Building your people graph.</Text>
      <Text style={s.emptyBody}>
        Connect Google or iMessage and Genie will map{'\n'}the people who matter most to you.
      </Text>
    </View>
  );
}

function PersonSheet({ person, onClose }: { person: Person; onClose: () => void }) {
  const daysSince = person.last_meaningful_exchange
    ? Math.floor(
        (Date.now() - new Date(person.last_meaningful_exchange).getTime()) / 86400000
      )
    : null;

  const hasMoments = Array.isArray((person as any).suggested_moments)
    && (person as any).suggested_moments.length > 0;

  return (
    <View style={sh.root}>
      <View style={sh.handle} />

      {/* Top bar */}
      <View style={sh.topBar}>
        <View />
        <Pressable style={sh.doneBtn} onPress={onClose}>
          <Text style={sh.doneBtnText}>Done</Text>
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={sh.scroll}>
        {/* Profile header */}
        <View style={sh.profileHeader}>
          <View style={sh.avatarLg}>
            <Text style={sh.avatarLgText}>{person.name[0]?.toUpperCase()}</Text>
          </View>
          <Text style={sh.name}>{person.name}</Text>
          {person.relationship_type ? (
            <Text style={sh.relType}>{person.relationship_type}</Text>
          ) : null}
          <View style={sh.metaRow}>
            {daysSince !== null && (
              <View style={sh.metaChip}>
                <Text style={sh.metaChipText}>
                  {daysSince === 0 ? 'Talked today' : `Last talked ${daysSince}d ago`}
                </Text>
              </View>
            )}
            <View style={sh.metaChip}>
              <Text style={sh.metaChipText}>
                Closeness {Math.round((person.closeness_score ?? 0) * 10)}/10
              </Text>
            </View>
          </View>
        </View>

        {/* Suggested moments */}
        {hasMoments && (
          <>
            <View style={sh.sectionRow}>
              <Text style={sh.sectionLabel}>WHAT GENIE SUGGESTS</Text>
            </View>
            {(person as any).suggested_moments.map((m: any, i: number) => (
              <View key={i} style={sh.momentCard}>
                <View style={sh.momentTiming}>
                  <Text style={sh.momentTimingText}>{m.timing ?? 'SOON'}</Text>
                </View>
                <Text style={sh.momentTitle}>{m.title}</Text>
                {m.description ? (
                  <Text style={sh.momentDesc}>{m.description}</Text>
                ) : null}
              </View>
            ))}
          </>
        )}

        {/* Memories */}
        {person.memories?.length > 0 && (
          <>
            <View style={sh.sectionRow}>
              <Text style={sh.sectionLabel}>WHAT GENIE KNOWS</Text>
            </View>
            {person.memories.map((m, i) => (
              <View key={i} style={sh.memCard}>
                <View style={sh.memDot} />
                <Text style={sh.memText}>{m.description}</Text>
              </View>
            ))}
          </>
        )}

        <View style={{ height: SPACING.xxxl }} />
      </ScrollView>
    </View>
  );
}

function daysSinceLabel(iso: string): string {
  const d = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
  if (d === 0) return 'today';
  if (d === 1) return '1d ago';
  if (d < 7)   return `${d}d ago`;
  if (d < 30)  return `${Math.floor(d / 7)}w ago`;
  return `${Math.floor(d / 30)}mo ago`;
}

// ── Main screen styles ────────────────────────────────────────────────────────

const s = StyleSheet.create({
  root:    { flex: 1, backgroundColor: COLORS.bg },
  content: { padding: SPACING.xl, paddingTop: 64 },
  center:  { flex: 1, backgroundColor: COLORS.bg, justifyContent: 'center', alignItems: 'center' },

  header:       { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, marginBottom: SPACING.xl },
  heading:      { ...FONTS.display, fontSize: 26 },
  headingCount: {
    ...FONTS.caption,
    color: COLORS.textTertiary,
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.pill,
    paddingHorizontal: SPACING.sm,
    paddingVertical: 3,
    borderWidth: 1,
    borderColor: COLORS.border,
    overflow: 'hidden',
  },

  // Card
  card: {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    padding: SPACING.lg,
    marginBottom: SPACING.sm,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  cardClose: {
    borderColor: COLORS.accentBorder,
  },
  cardRow:  { flexDirection: 'row', alignItems: 'center', gap: SPACING.md },
  cardInfo: { flex: 1 },
  cardRight:{ alignItems: 'flex-end', gap: 4 },

  // Avatar
  avatar: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: COLORS.surfaceElevated,
    borderWidth: 1,
    borderColor: COLORS.border,
    justifyContent: 'center',
    alignItems: 'center',
  },
  avatarClose: {
    backgroundColor: COLORS.accentDim,
    borderColor: COLORS.accentBorder,
  },
  avatarText:      { color: COLORS.textSecondary, fontWeight: '700', fontSize: 17 },
  avatarTextClose: { color: COLORS.accent },

  // Info
  personName: { ...FONTS.sub, fontSize: 15 },
  relType:    { ...FONTS.label, marginTop: 2 },
  recency:    { ...FONTS.caption },

  // Closeness
  pips: { flexDirection: 'row', gap: 3 },
  pip:  { width: 5, height: 5, borderRadius: 2.5 },

  // Memory preview
  memoryPreview: {
    ...FONTS.label,
    fontStyle: 'italic',
    lineHeight: 18,
    marginTop: SPACING.sm,
    color: COLORS.textTertiary,
  },

  // Empty
  emptyWrap:     { alignItems: 'center', paddingVertical: SPACING.hero, paddingHorizontal: SPACING.xl },
  emptyLamp:     { fontSize: 44, marginBottom: SPACING.lg },
  emptyHeadline: { ...FONTS.sub, textAlign: 'center', marginBottom: SPACING.sm },
  emptyBody:     { ...FONTS.body, color: COLORS.textSecondary, textAlign: 'center', lineHeight: 24 },
});

// ── Sheet styles ──────────────────────────────────────────────────────────────

const sh = StyleSheet.create({
  root:   { flex: 1, backgroundColor: COLORS.bg, paddingTop: 12 },
  handle: {
    width: 36, height: 4, backgroundColor: COLORS.border,
    borderRadius: 2, alignSelf: 'center', marginBottom: 8,
  },
  topBar: {
    flexDirection: 'row', justifyContent: 'space-between',
    alignItems: 'center', paddingHorizontal: SPACING.xl, paddingBottom: 8,
  },
  doneBtn:     { paddingVertical: 8, paddingLeft: 16 },
  doneBtnText: { color: COLORS.accent, fontSize: 16, fontWeight: '500' },

  scroll: { paddingHorizontal: SPACING.xl, paddingBottom: SPACING.xxxl },

  // Profile header
  profileHeader: { alignItems: 'center', paddingVertical: SPACING.xl, marginBottom: SPACING.md },
  avatarLg: {
    width: 80, height: 80, borderRadius: 40,
    backgroundColor: COLORS.accentDim,
    borderWidth: 1.5, borderColor: COLORS.accentBorder,
    justifyContent: 'center', alignItems: 'center',
    marginBottom: SPACING.md,
  },
  avatarLgText: { color: COLORS.accent, fontWeight: '700', fontSize: 32 },
  name:    { ...FONTS.heading, textAlign: 'center', marginBottom: 6 },
  relType: { ...FONTS.label, textAlign: 'center', textTransform: 'capitalize', marginBottom: SPACING.md },
  metaRow: { flexDirection: 'row', gap: SPACING.sm, flexWrap: 'wrap', justifyContent: 'center' },
  metaChip: {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.pill,
    paddingHorizontal: SPACING.md,
    paddingVertical: 5,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  metaChipText: { ...FONTS.caption, color: COLORS.textSecondary },

  // Section
  sectionRow:  { flexDirection: 'row', alignItems: 'center', marginBottom: SPACING.md, marginTop: SPACING.lg },
  sectionLabel:{ ...FONTS.caption, textTransform: 'uppercase', letterSpacing: 1.2 },

  // Suggested moments
  momentCard: {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    padding: SPACING.lg,
    marginBottom: SPACING.sm,
    borderWidth: 1,
    borderColor: COLORS.accentBorder,
  },
  momentTiming: {
    alignSelf: 'flex-start',
    backgroundColor: COLORS.accentDim,
    borderRadius: RADIUS.pill,
    paddingHorizontal: SPACING.sm,
    paddingVertical: 3,
    marginBottom: SPACING.sm,
  },
  momentTimingText: { ...FONTS.caption, color: COLORS.accent, textTransform: 'uppercase', letterSpacing: 0.8 },
  momentTitle:      { ...FONTS.sub, fontSize: 15, marginBottom: 6 },
  momentDesc:       { ...FONTS.body, color: COLORS.textSecondary, lineHeight: 22 },

  // Memories
  memCard: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: SPACING.sm,
    paddingVertical: SPACING.sm,
    borderBottomWidth: 1,
    borderBottomColor: COLORS.border,
  },
  memDot: {
    width: 5, height: 5, borderRadius: 2.5,
    backgroundColor: COLORS.accentBorder,
    marginTop: 8, flexShrink: 0,
  },
  memText: { ...FONTS.body, color: COLORS.textSecondary, flex: 1, lineHeight: 22 },
});
