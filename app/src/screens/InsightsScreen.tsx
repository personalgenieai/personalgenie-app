/**
 * InsightsScreen — "It's awakened."
 *
 * Reads pg_insights_batch (array of contacts) and reveals each person's
 * AHA MOMENT + supporting cards sequentially.
 *
 * Falls back to pg_insights (legacy single-contact) if batch not found.
 */
import React, { useEffect, useRef, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Animated,
  ImageBackground, Dimensions, Platform, TouchableOpacity,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import AsyncStorage from '@react-native-async-storage/async-storage';

const { width, height } = Dimensions.get('window');
const BG = require('../../assets/bg_chat.png');

interface Insights {
  key_memory:        string;
  summary:           string;
  message_count:     number | null;
  who_initiates:     string;
  memories:          string[];
  relationship_score: number | null;
  tip:               string;
}

interface InsightItem {
  contact: { name: string; phone: string };
  insights: Insights;
  source: string;
}

function fmtCount(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1).replace('.0', '')}k`;
  return String(n);
}

export default function InsightsScreen({ navigation }: any) {
  const [items, setItems]           = useState<InsightItem[]>([]);
  const [revealIndex, setRevealIndex] = useState(0);

  const headerFade  = useRef(new Animated.Value(0)).current;
  const headerSlide = useRef(new Animated.Value(20)).current;

  useEffect(() => {
    // Load batch or legacy single
    Promise.all([
      AsyncStorage.getItem('pg_insights_batch'),
      AsyncStorage.getItem('pg_insights'),
    ]).then(([batch, single]) => {
      if (batch) {
        const parsed = JSON.parse(batch);
        setItems(parsed.items ?? []);
      } else if (single) {
        const parsed = JSON.parse(single);
        setItems([{ contact: parsed.contact, insights: parsed.insights, source: parsed.source ?? 'legacy' }]);
      }
    });

    Animated.parallel([
      Animated.timing(headerFade,  { toValue: 1, duration: 900, delay: 400, useNativeDriver: true }),
      Animated.timing(headerSlide, { toValue: 0, duration: 800, delay: 400, useNativeDriver: true }),
    ]).start();

    // Reveal one unit at a time — each "unit" is a card across all people
    // Total cards per person: 4 (key_memory, summary, stats, patterns, tip) + divider
    const timer = setInterval(() => {
      setRevealIndex(prev => prev + 1);
    }, 800);
    return () => clearInterval(timer);
  }, []);

  if (items.length === 0) return null;

  // Build flat ordered list of reveal units
  // Each person contributes: divider, key_memory, summary+stats, patterns, tip
  // revealIndex gates each unit
  const totalPersonCards = 5; // cards per person
  const totalUnits = items.length * totalPersonCards + 1; // +1 for footer

  return (
    <ImageBackground source={BG} style={s.bg} resizeMode="cover">
      <LinearGradient
        colors={['rgba(5,4,10,0.92)', 'rgba(5,4,10,0.5)', 'transparent']}
        style={s.gradTop}
        pointerEvents="none"
      />
      <LinearGradient
        colors={['transparent', 'rgba(5,4,10,0.85)', 'rgba(5,4,10,0.98)']}
        style={s.gradBottom}
        pointerEvents="none"
      />

      <ScrollView
        style={s.scroll}
        contentContainerStyle={s.content}
        showsVerticalScrollIndicator={false}
      >
        {/* Header */}
        <View style={s.header}>
          <Text style={s.wordmark}>PERSONAL GENIE</Text>
        </View>

        {/* Awakened headline */}
        <Animated.View style={[s.awakened, { opacity: headerFade, transform: [{ translateY: headerSlide }] }]}>
          <Text style={s.awakenedText}>It's awakened.</Text>
          <Text style={s.awakenedSub}>
            {items.length === 1
              ? `Here's what I noticed about your relationship with ${items[0].contact.name.split(' ')[0]}.`
              : `Here's what I noticed across your ${items.length} closest relationships.`}
          </Text>
        </Animated.View>

        {/* Per-person sections */}
        {items.map((item, personIdx) => {
          const base = personIdx * totalPersonCards; // global reveal index offset
          const { contact, insights } = item;
          const firstName = contact.name.split(' ')[0];

          const whoInitiatesLabel =
            insights.who_initiates === 'user'  ? 'You reach out first more often' :
            insights.who_initiates === 'them'  ? `${firstName} reaches out first more often` :
            'You both initiate equally';

          return (
            <View key={contact.phone} style={s.personSection}>
              {/* Person divider — shown immediately for first person, gated for rest */}
              {(personIdx === 0 || revealIndex >= base) && (
                <PersonDivider
                  name={contact.name}
                  msgCount={insights.message_count}
                  isFirst={personIdx === 0}
                />
              )}

              {/* AHA MOMENT — hero */}
              {revealIndex >= base + 1 && insights.key_memory ? (
                <RevealCard gold hero>
                  <Text style={[s.cardLabel, { color: '#C9A84C' }]}>WHAT I NOTICED</Text>
                  <Text style={s.heroMemory}>{insights.key_memory}</Text>
                </RevealCard>
              ) : null}

              {/* Summary */}
              {revealIndex >= base + 2 && (
                <RevealCard>
                  <Text style={s.cardLabel}>RELATIONSHIP</Text>
                  <Text style={s.cardBody}>{insights.summary}</Text>
                </RevealCard>
              )}

              {/* Stats */}
              {revealIndex >= base + 3 && (
                <RevealCard>
                  <Text style={s.cardLabel}>STATS</Text>
                  <View style={s.statsRow}>
                    {insights.message_count != null && (
                      <View style={s.stat}>
                        <Text style={s.statNumber}>{fmtCount(insights.message_count)}</Text>
                        <Text style={s.statLabel}>messages</Text>
                      </View>
                    )}
                    {insights.relationship_score != null && (
                      <View style={s.stat}>
                        <Text style={s.statNumber}>
                          {insights.relationship_score}
                          <Text style={s.statUnit}>/10</Text>
                        </Text>
                        <Text style={s.statLabel}>closeness</Text>
                      </View>
                    )}
                  </View>
                  <Text style={s.cardBody}>{whoInitiatesLabel}</Text>
                </RevealCard>
              )}

              {/* Patterns / memories */}
              {revealIndex >= base + 4 && insights.memories.length > 0 && (
                <RevealCard>
                  <Text style={s.cardLabel}>PATTERNS</Text>
                  <View style={{ gap: 10 }}>
                    {insights.memories.map((m, i) => (
                      <View key={i} style={s.memoryRow}>
                        <View style={s.memoryDot} />
                        <Text style={s.memoryText}>{m}</Text>
                      </View>
                    ))}
                  </View>
                </RevealCard>
              )}

              {/* Genie's move */}
              {revealIndex >= base + 5 && insights.tip ? (
                <RevealCard gold>
                  <Text style={[s.cardLabel, { color: '#C9A84C' }]}>GENIE'S MOVE</Text>
                  <Text style={[s.cardBody, { fontFamily: 'Georgia', fontStyle: 'italic', fontSize: 16, lineHeight: 26 }]}>
                    {insights.tip}
                  </Text>
                </RevealCard>
              ) : null}
            </View>
          );
        })}

        {/* Footer CTA */}
        {revealIndex >= totalUnits && (
          <Animated.View style={{ marginTop: 8, paddingHorizontal: 16, paddingBottom: 40 }}>
            <TouchableOpacity
              style={s.secondaryBtn}
              onPress={async () => {
                await AsyncStorage.multiRemove(['pg_insights', 'pg_insights_batch']);
                navigation.replace('Splash');
              }}
            >
              <Text style={s.secondaryBtnText}>Explore more relationships</Text>
            </TouchableOpacity>
          </Animated.View>
        )}
      </ScrollView>
    </ImageBackground>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function PersonDivider({ name, msgCount, isFirst }: { name: string; msgCount: number | null; isFirst: boolean }) {
  const fade = useRef(new Animated.Value(isFirst ? 0 : 0)).current;

  useEffect(() => {
    Animated.timing(fade, { toValue: 1, duration: 600, delay: isFirst ? 300 : 0, useNativeDriver: true }).start();
  }, []);

  return (
    <Animated.View style={[s.personDivider, { opacity: fade }]}>
      <View style={s.dividerLine} />
      <View style={s.dividerLabel}>
        <Text style={s.dividerName}>{name}</Text>
        {msgCount != null && (
          <Text style={s.dividerCount}>{fmtCount(msgCount)} messages</Text>
        )}
      </View>
      <View style={s.dividerLine} />
    </Animated.View>
  );
}

function RevealCard({ children, gold = false, hero = false }: {
  children: React.ReactNode; gold?: boolean; hero?: boolean;
}) {
  const fade  = useRef(new Animated.Value(0)).current;
  const slide = useRef(new Animated.Value(20)).current;

  useEffect(() => {
    Animated.parallel([
      Animated.timing(fade,  { toValue: 1, duration: hero ? 700 : 500, useNativeDriver: true }),
      Animated.timing(slide, { toValue: 0, duration: hero ? 600 : 450, useNativeDriver: true }),
    ]).start();
  }, []);

  return (
    <Animated.View style={[
      s.card,
      gold && s.cardGold,
      hero && s.cardHero,
      { opacity: fade, transform: [{ translateY: slide }] },
    ]}>
      {children}
    </Animated.View>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────

const s = StyleSheet.create({
  bg:         { flex: 1, width, height, backgroundColor: '#0A0A0F' },
  gradTop:    { position: 'absolute', top: 0, left: 0, right: 0, height: height * 0.40, zIndex: 1 },
  gradBottom: { position: 'absolute', bottom: 0, left: 0, right: 0, height: height * 0.25, zIndex: 1 },
  scroll:     { flex: 1, zIndex: 3 },
  content:    { paddingBottom: 60 },

  header: {
    paddingTop: Platform.OS === 'ios' ? 64 : 48,
    alignItems: 'center', marginBottom: 32,
  },
  wordmark: {
    fontFamily: 'System', fontSize: 11, fontWeight: '600',
    color: '#C9A84C', letterSpacing: 3.5, textTransform: 'uppercase',
  },

  awakened:    { alignItems: 'center', paddingHorizontal: 32, marginBottom: 20 },
  awakenedText: {
    fontFamily: 'Georgia', fontStyle: 'italic',
    fontSize: 34, color: '#F5F0E8', textAlign: 'center', marginBottom: 10,
  },
  awakenedSub: { fontSize: 15, color: '#8A8070', textAlign: 'center', lineHeight: 23 },

  personSection: { marginBottom: 8 },

  personDivider: {
    flexDirection: 'row', alignItems: 'center',
    paddingHorizontal: 16, marginVertical: 20, gap: 12,
  },
  dividerLine:  { flex: 1, height: 1, backgroundColor: '#1E1E2E' },
  dividerLabel: { alignItems: 'center', gap: 2 },
  dividerName:  { fontSize: 14, fontWeight: '700', color: '#F5F0E8', letterSpacing: 0.3 },
  dividerCount: { fontSize: 11, color: '#4A4438' },

  cards: { paddingHorizontal: 16, gap: 12 },

  card: {
    backgroundColor: 'rgba(12,12,18,0.88)',
    borderRadius: 16, borderWidth: 1, borderColor: '#1E1E2E',
    padding: 20, gap: 12, marginHorizontal: 16, marginBottom: 10,
  },
  cardGold: { borderColor: '#C9A84C44', borderLeftWidth: 3, borderLeftColor: '#C9A84C' },
  cardHero: {
    borderColor: '#C9A84C55',
    borderWidth: 1,
    borderLeftWidth: 3,
    borderLeftColor: '#C9A84C',
    backgroundColor: 'rgba(18,14,8,0.95)',
    paddingVertical: 24,
  },

  cardLabel: {
    fontSize: 11, fontWeight: '600', color: '#4A4438',
    letterSpacing: 1.5, textTransform: 'uppercase',
  },
  cardBody: { fontSize: 15, color: '#F5F0E8', lineHeight: 24 },

  heroMemory: {
    fontFamily: 'Georgia',
    fontStyle: 'italic',
    fontSize: 18,
    color: '#F5F0E8',
    lineHeight: 30,
    marginTop: 4,
  },

  statsRow: { flexDirection: 'row', gap: 32 },
  stat:     { gap: 2 },
  statNumber: { fontFamily: 'Georgia', fontSize: 36, color: '#C9A84C', fontStyle: 'italic' },
  statUnit:   { fontSize: 16, color: '#8A8070' },
  statLabel:  { fontSize: 12, color: '#8A8070', textTransform: 'uppercase', letterSpacing: 0.8 },

  memoryRow: { flexDirection: 'row', gap: 12, alignItems: 'flex-start' },
  memoryDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: '#C9A84C', marginTop: 8, flexShrink: 0 },
  memoryText: { flex: 1, fontSize: 14, color: '#8A8070', lineHeight: 22 },

  secondaryBtn: {
    borderWidth: 1, borderColor: '#2A2740', borderRadius: 14,
    paddingVertical: 14, alignItems: 'center',
  },
  secondaryBtnText: { color: '#8A8070', fontSize: 15, fontWeight: '600' },
});
