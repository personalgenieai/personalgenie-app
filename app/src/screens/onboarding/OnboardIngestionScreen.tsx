/**
 * OnboardIngestionScreen — Live learnings feed.
 * bg_ingestion.png background. All WebSocket/ingestion logic preserved.
 */
import React, { useEffect, useRef, useState, useCallback } from 'react';
import {
  View, Text, StyleSheet, Animated, FlatList, Easing,
  ImageBackground, Dimensions, Platform,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { createIngestionSession, linkIngestionSession, getBaseUrl } from '../../api';

const { width, height } = Dimensions.get('window');
const BG = require('../../../assets/bg_ingestion.png');

interface ProgressEvent {
  source?:       string;
  stage?:        string;
  progress:      number;
  message?:      string;
  insight?:      string;
  people_found?: number;
}

interface LearnCard {
  id:      string;
  name:    string;
  insight: string;
}

const TIMEOUT_MS = 90_000;

export default function OnboardIngestionScreen({ route, navigation }: any) {
  const { name, firstPerson } = route.params ?? {};

  const [statusLine, setStatusLine]   = useState("I'm getting to know your world…");
  const [sourceLabel, setSourceLabel] = useState<string | null>(null);
  const [cards, setCards]             = useState<LearnCard[]>([]);
  const [peopleFound, setPeopleFound] = useState(0);
  const [isDone, setIsDone]           = useState(false);

  const progressAnim  = useRef(new Animated.Value(0)).current;
  const statusFade    = useRef(new Animated.Value(1)).current;
  const listRef       = useRef<FlatList>(null);

  const wsRef       = useRef<WebSocket | null>(null);
  const timeoutRef  = useRef<ReturnType<typeof setTimeout> | null>(null);
  const doneRef     = useRef(false);
  const cardIdRef   = useRef(0);

  const animateProgress = useCallback((toValue: number) => {
    Animated.timing(progressAnim, {
      toValue: Math.min(toValue, 100) / 100,
      duration: 700,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: false,
    }).start();
  }, [progressAnim]);

  const flashStatus = useCallback((text: string) => {
    Animated.sequence([
      Animated.timing(statusFade, { toValue: 0, duration: 150, useNativeDriver: true }),
      Animated.timing(statusFade, { toValue: 1, duration: 250, useNativeDriver: true }),
    ]).start();
    setStatusLine(text);
  }, [statusFade]);

  const addCard = useCallback((cardName: string, insight: string) => {
    const id = String(++cardIdRef.current);
    setCards(prev => [...prev, { id, name: cardName, insight }]);
    setTimeout(() => listRef.current?.scrollToEnd({ animated: true }), 80);
  }, []);

  const advance = useCallback(() => {
    if (doneRef.current) return;
    doneRef.current = true;
    setIsDone(true);
    flashStatus('Your picture is coming together.');
    animateProgress(100);

    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    wsRef.current?.close();

    setTimeout(() => {
      navigation.navigate('OnboardWhatsApp', { name, firstPerson, notifPref: 'default' });
    }, 2000);
  }, [navigation, name, firstPerson, flashStatus, animateProgress]);

  useEffect(() => {
    let cancelled = false;

    async function start() {
      timeoutRef.current = setTimeout(() => {
        if (!doneRef.current) advance();
      }, TIMEOUT_MS);

      let sessionId: string;
      try {
        const res = await createIngestionSession();
        sessionId = res.session_id;
      } catch (_) {
        advance();
        return;
      }
      if (cancelled) return;

      try {
        const userId = await AsyncStorage.getItem('pg_user_id');
        if (userId) await linkIngestionSession(userId, sessionId);
      } catch (_) {
        // Non-fatal
      }
      if (cancelled) return;

      let baseUrl: string;
      try {
        baseUrl = await getBaseUrl();
      } catch (_) {
        advance();
        return;
      }
      if (cancelled) return;

      const wsUrl = baseUrl.replace(/^https/, 'wss').replace(/^http/, 'ws');
      const ws = new WebSocket(`${wsUrl}/ws/ingestion/${sessionId}`);
      wsRef.current = ws;

      ws.onmessage = (event) => {
        if (doneRef.current) return;
        try {
          const data: ProgressEvent = JSON.parse(event.data);
          if (data.progress !== undefined) animateProgress(data.progress);
          if (data.message)               flashStatus(data.message);
          if (data.source)                setSourceLabel(formatSource(data.source));
          if (data.people_found != null && data.people_found > 0)
            setPeopleFound(data.people_found);
          if (data.insight && data.message) addCard(data.message, data.insight);
          if (data.progress >= 100) advance();
        } catch (_) {}
      };

      ws.onerror = () => { if (!doneRef.current) advance(); };
      ws.onclose = () => {
        if (!doneRef.current) {
          setTimeout(() => { if (!doneRef.current) advance(); }, 2000);
        }
      };
    }

    start();
    return () => {
      cancelled = true;
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
      wsRef.current?.close();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const barWidth = progressAnim.interpolate({
    inputRange:  [0, 1],
    outputRange: ['0%', '100%'],
  });

  return (
    <ImageBackground source={BG} style={{ flex: 1, width, height, backgroundColor: '#0A0A0F' }} resizeMode="cover">
      <LinearGradient
        colors={['rgba(5,4,10,0.65)', 'rgba(5,4,10,0.15)', 'transparent']}
        style={{ position: 'absolute', top: 0, left: 0, right: 0, height: height * 0.45, zIndex: 1 }}
        pointerEvents="none"
      />
      <LinearGradient
        colors={['transparent', 'rgba(5,4,10,0.88)', 'rgba(5,4,10,0.99)']}
        style={{ position: 'absolute', bottom: 0, left: 0, right: 0, height: height * 0.60, zIndex: 1 }}
        pointerEvents="none"
      />

      <View style={s.content}>
        {/* Top section */}
        <View style={s.top}>
          <Text style={s.wordmark}>PERSONAL GENIE</Text>
          <Animated.Text style={[s.status, { opacity: statusFade }]} numberOfLines={2}>
            {statusLine}
          </Animated.Text>

          {/* Progress bar */}
          <View style={s.barTrack}>
            <Animated.View style={[s.barFill, { width: barWidth }]} />
          </View>

          {/* Source chip + people count */}
          <View style={s.metaRow}>
            {sourceLabel && !isDone && (
              <View style={s.chip}>
                <View style={s.chipDot} />
                <Text style={s.chipText}>{sourceLabel}</Text>
              </View>
            )}
            {peopleFound > 0 && (
              <Text style={s.peopleCount}>
                {peopleFound} {peopleFound === 1 ? 'person' : 'people'}
              </Text>
            )}
          </View>
        </View>

        {/* Live learnings feed */}
        <FlatList
          ref={listRef}
          data={cards}
          keyExtractor={(c) => c.id}
          style={s.feed}
          contentContainerStyle={s.feedContent}
          renderItem={({ item, index }) => (
            <LearningCard card={item} index={index} />
          )}
          ListEmptyComponent={<EmptyFeed />}
          showsVerticalScrollIndicator={false}
        />
      </View>
    </ImageBackground>
  );
}

function LearningCard({ card, index }: { card: LearnCard; index: number }) {
  const slideAnim = useRef(new Animated.Value(24)).current;
  const fadeAnim  = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.parallel([
      Animated.spring(slideAnim, {
        toValue: 0,
        useNativeDriver: true,
        tension: 60,
        friction: 10,
      }),
      Animated.timing(fadeAnim, { toValue: 1, duration: 300, useNativeDriver: true }),
    ]).start();
  }, [slideAnim, fadeAnim]);

  return (
    <Animated.View
      style={[
        s.card,
        { opacity: fadeAnim, transform: [{ translateY: slideAnim }] },
      ]}
    >
      <View style={s.cardDot} />
      <View style={s.cardBody}>
        <Text style={s.cardName} numberOfLines={1}>{card.name}</Text>
        <Text style={s.cardInsight}>{card.insight}</Text>
      </View>
    </Animated.View>
  );
}

function EmptyFeed() {
  const dot1 = useRef(new Animated.Value(0.3)).current;
  const dot2 = useRef(new Animated.Value(0.3)).current;
  const dot3 = useRef(new Animated.Value(0.3)).current;

  useEffect(() => {
    ([[dot1, 0], [dot2, 200], [dot3, 400]] as [Animated.Value, number][]).forEach(([anim, delay]) => {
      Animated.loop(
        Animated.sequence([
          Animated.delay(delay),
          Animated.timing(anim, { toValue: 1,   duration: 500, useNativeDriver: true }),
          Animated.timing(anim, { toValue: 0.3, duration: 500, useNativeDriver: true }),
        ])
      ).start();
    });
  }, [dot1, dot2, dot3]);

  return (
    <View style={s.emptyFeed}>
      <Text style={s.emptyFeedText}>Learnings will appear here</Text>
      <View style={s.emptyDots}>
        {[dot1, dot2, dot3].map((d, i) => (
          <Animated.View key={i} style={[s.emptyDot, { opacity: d }]} />
        ))}
      </View>
    </View>
  );
}

function formatSource(source: string): string {
  const map: Record<string, string> = {
    google:    'Reading Google',
    gmail:     'Reading Gmail',
    contacts:  'Reading Contacts',
    photos:    'Reading Photos',
    imessage:  'Reading iMessage',
    calendar:  'Reading Calendar',
    analyzing: 'Analyzing relationships',
  };
  return map[source.toLowerCase()] ?? `Reading ${source}`;
}

const s = StyleSheet.create({
  content: {
    flex: 1,
    zIndex: 3,
    paddingTop: Platform.OS === 'ios' ? 64 : 48,
    paddingBottom: Platform.OS === 'ios' ? 36 : 24,
    paddingHorizontal: 32,
  },

  top: { alignItems: 'center', marginBottom: 16 },
  wordmark: {
    fontFamily: 'System',
    fontSize: 11,
    fontWeight: '600',
    color: '#C9A84C',
    letterSpacing: 3.5,
    textTransform: 'uppercase',
    marginBottom: 24,
  },
  status: {
    fontFamily: 'Georgia',
    fontStyle: 'italic',
    fontSize: 18,
    color: '#F5F0E8',
    textAlign: 'center',
    lineHeight: 26,
    marginBottom: 16,
    minHeight: 52,
    paddingHorizontal: 12,
  },

  barTrack: {
    width: '100%',
    height: 3,
    backgroundColor: '#1E1E2E',
    borderRadius: 2,
    overflow: 'hidden',
    marginBottom: 12,
  },
  barFill: {
    height: '100%',
    backgroundColor: '#C9A84C',
    borderRadius: 2,
  },

  metaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    minHeight: 28,
  },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: '#1E1E2E',
    paddingHorizontal: 12,
    paddingVertical: 4,
    backgroundColor: 'rgba(12,12,18,0.72)',
  },
  chipDot:     { width: 5, height: 5, borderRadius: 2.5, backgroundColor: '#C9A84C' },
  chipText:    { fontFamily: 'System', fontSize: 12, color: '#8A8070' },
  peopleCount: { fontFamily: 'System', fontSize: 12, color: '#C9A84C' },

  feed:        { flex: 1 },
  feedContent: { paddingBottom: 48, gap: 8 },

  card: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 12,
    backgroundColor: 'rgba(12,12,18,0.82)',
    borderRadius: 14,
    padding: 16,
    borderWidth: 1,
    borderColor: '#1E1E2E',
    borderLeftWidth: 2,
    borderLeftColor: '#C9A84C44',
  },
  cardDot: {
    width: 7,
    height: 7,
    borderRadius: 3.5,
    backgroundColor: '#C9A84C',
    marginTop: 5,
    flexShrink: 0,
  },
  cardBody:    { flex: 1 },
  cardName: {
    fontFamily: 'System',
    fontSize: 13,
    fontWeight: '600',
    color: '#C9A84C',
    textTransform: 'uppercase',
    marginBottom: 4,
  },
  cardInsight: {
    fontFamily: 'System',
    fontSize: 14,
    color: '#8A8070',
    lineHeight: 22,
  },

  emptyFeed: {
    alignItems: 'center',
    paddingTop: 24,
    gap: 12,
  },
  emptyFeedText: { fontFamily: 'System', fontSize: 13, color: '#4A4438' },
  emptyDots:     { flexDirection: 'row', gap: 4 },
  emptyDot: {
    width: 5,
    height: 5,
    borderRadius: 2.5,
    backgroundColor: '#4A4438',
  },
});
