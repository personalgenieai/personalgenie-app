/**
 * InsightsScreen — "It's awakened."
 * Reveals relationship insights as animated chat cards.
 * bg_chat.png background.
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
  summary: string;
  message_count: number | null;
  who_initiates: string;
  memories: string[];
  relationship_score: number | null;
  tip: string;
}

interface StoredData {
  contact: { name: string; phone: string };
  insights: Insights;
  processedAt: string;
}

export default function InsightsScreen({ navigation }: any) {
  const [data, setData] = useState<StoredData | null>(null);
  const [revealIndex, setRevealIndex] = useState(0);

  const headerFade = useRef(new Animated.Value(0)).current;
  const headerSlide = useRef(new Animated.Value(20)).current;

  useEffect(() => {
    AsyncStorage.getItem('pg_insights').then(raw => {
      if (raw) setData(JSON.parse(raw));
    });

    Animated.parallel([
      Animated.timing(headerFade, { toValue: 1, duration: 900, delay: 400, useNativeDriver: true }),
      Animated.timing(headerSlide, { toValue: 0, duration: 800, delay: 400, useNativeDriver: true }),
    ]).start();

    // Reveal cards one by one
    const timer = setInterval(() => {
      setRevealIndex(prev => prev + 1);
    }, 700);
    return () => clearInterval(timer);
  }, []);

  if (!data) return null;

  const { contact, insights } = data;
  const firstName = contact.name.split(' ')[0];

  const whoInitiatesLabel =
    insights.who_initiates === 'user'  ? 'You reach out first more often' :
    insights.who_initiates === 'them'  ? `${firstName} reaches out first more often` :
    'You both initiate equally';

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
          <Text style={s.awakenedSub}>Here's what I know about your relationship with {firstName}.</Text>
        </Animated.View>

        {/* Cards — each fades in sequentially */}
        <View style={s.cards}>

          {/* Summary */}
          {revealIndex >= 1 && (
            <RevealCard delay={0}>
              <Text style={s.cardLabel}>RELATIONSHIP</Text>
              <Text style={s.cardBody}>{insights.summary}</Text>
            </RevealCard>
          )}

          {/* Stats */}
          {revealIndex >= 2 && (
            <RevealCard delay={0}>
              <Text style={s.cardLabel}>STATS</Text>
              <View style={s.statsRow}>
                {insights.message_count != null && (
                  <View style={s.stat}>
                    <Text style={s.statNumber}>{insights.message_count}</Text>
                    <Text style={s.statLabel}>messages</Text>
                  </View>
                )}
                {insights.relationship_score != null && (
                  <View style={s.stat}>
                    <Text style={s.statNumber}>{insights.relationship_score}<Text style={s.statUnit}>/10</Text></Text>
                    <Text style={s.statLabel}>closeness</Text>
                  </View>
                )}
              </View>
              <Text style={s.cardBody}>{whoInitiatesLabel}</Text>
            </RevealCard>
          )}

          {/* Memories */}
          {revealIndex >= 3 && insights.memories.length > 0 && (
            <RevealCard delay={0}>
              <Text style={s.cardLabel}>MEMORIES</Text>
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

          {/* Tip */}
          {revealIndex >= 4 && (
            <RevealCard delay={0} gold>
              <Text style={[s.cardLabel, { color: '#C9A84C' }]}>GENIE'S TIP</Text>
              <Text style={[s.cardBody, { color: '#F5F0E8', fontFamily: 'Georgia', fontStyle: 'italic', fontSize: 16, lineHeight: 26 }]}>
                {insights.tip}
              </Text>
            </RevealCard>
          )}

          {/* Start over */}
          {revealIndex >= 5 && (
            <Animated.View style={{ marginTop: 8 }}>
              <TouchableOpacity
                style={s.secondaryBtn}
                onPress={async () => {
                  await AsyncStorage.removeItem('pg_insights');
                  navigation.replace('Splash');
                }}
              >
                <Text style={s.secondaryBtnText}>Explore another relationship</Text>
              </TouchableOpacity>
            </Animated.View>
          )}
        </View>
      </ScrollView>
    </ImageBackground>
  );
}

function RevealCard({ children, delay = 0, gold = false }: { children: React.ReactNode; delay?: number; gold?: boolean }) {
  const fade  = useRef(new Animated.Value(0)).current;
  const slide = useRef(new Animated.Value(16)).current;

  useEffect(() => {
    Animated.parallel([
      Animated.timing(fade,  { toValue: 1, duration: 500, delay, useNativeDriver: true }),
      Animated.timing(slide, { toValue: 0, duration: 450, delay, useNativeDriver: true }),
    ]).start();
  }, []);

  return (
    <Animated.View style={[s.card, gold && s.cardGold, { opacity: fade, transform: [{ translateY: slide }] }]}>
      {children}
    </Animated.View>
  );
}

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

  awakened:    { alignItems: 'center', paddingHorizontal: 32, marginBottom: 36 },
  awakenedText: {
    fontFamily: 'Georgia', fontStyle: 'italic',
    fontSize: 34, color: '#F5F0E8', textAlign: 'center', marginBottom: 10,
  },
  awakenedSub: { fontSize: 15, color: '#8A8070', textAlign: 'center', lineHeight: 23 },

  cards: { paddingHorizontal: 16, gap: 12 },

  card: {
    backgroundColor: 'rgba(12,12,18,0.88)',
    borderRadius: 16, borderWidth: 1, borderColor: '#1E1E2E',
    padding: 20, gap: 12,
  },
  cardGold: { borderColor: '#C9A84C44', borderLeftWidth: 3, borderLeftColor: '#C9A84C' },

  cardLabel: {
    fontSize: 11, fontWeight: '600', color: '#4A4438',
    letterSpacing: 1.5, textTransform: 'uppercase',
  },
  cardBody: { fontSize: 15, color: '#F5F0E8', lineHeight: 24 },

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
