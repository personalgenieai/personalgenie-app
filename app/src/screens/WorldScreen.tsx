/**
 * WorldScreen — "What Genie noticed" feed.
 * bg_world.png: lamp on dark horizon.
 * Replaces both Home and People tabs.
 */
import React, { useEffect, useState, useCallback } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  ImageBackground, Dimensions, Platform, RefreshControl,
  ActivityIndicator,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { useFocusEffect } from '@react-navigation/native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { getPeople, getMoments } from '../api';

const { width, height } = Dimensions.get('window');
const BG = require('../../assets/bg_world.png');

export default function WorldScreen() {
  const [cards, setCards]       = useState<any[]>([]);
  const [loading, setLoading]   = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [userName, setUserName] = useState('');

  async function load(refresh = false) {
    if (refresh) setRefreshing(true);
    try {
      const [userId, name] = await Promise.all([
        AsyncStorage.getItem('pg_user_id'),
        AsyncStorage.getItem('pg_user_name'),
      ]);
      if (name) setUserName(name.split(' ')[0]);
      if (!userId) return;

      // Load moments
      const moments = await getMoments(userId).catch(() => []);

      // Load people with suggested_moments
      const people = await getPeople(userId).catch(() => []);

      // Build card list: moments first, then suggested_moments from people
      const momentCards = moments.slice(0, 10).map((m: any) => ({
        id: `m_${m.id}`,
        type: 'moment',
        personName: m.person_name ?? m.title ?? 'Genie',
        body: m.content ?? m.description ?? m.summary ?? m.suggestion ?? '',
        timing: m.timing ?? m.date_label ?? 'Recently',
      }));

      const nudgeCards: any[] = [];
      people.forEach((p: any) => {
        const suggestions = p.suggested_moments ?? [];
        suggestions.slice(0, 2).forEach((s: any, i: number) => {
          nudgeCards.push({
            id: `n_${p.id}_${i}`,
            type: 'nudge',
            personName: p.name ?? '',
            body: typeof s === 'string' ? s : (s.description ?? s.title ?? ''),
            timing: s.timing ?? 'This week',
          });
        });
      });

      setCards([...momentCards, ...nudgeCards]);
    } catch (_) {}
    finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useFocusEffect(useCallback(() => { load(); }, []));

  return (
    <ImageBackground source={BG} style={s.bg} resizeMode="cover">
      <LinearGradient
        colors={['rgba(5,4,10,0.92)', 'rgba(5,4,10,0.60)', 'transparent']}
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
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => load(true)} tintColor="#C9A84C" />}
      >
        {/* Header */}
        <View style={s.header}>
          <Text style={s.wordmark}>PERSONAL GENIE</Text>
          <Text style={s.headline}>
            {userName ? `${userName}'s world.` : 'Your world, today.'}
          </Text>
        </View>

        {/* Feed */}
        <View style={s.feed}>
          {loading ? (
            <ActivityIndicator color="#C9A84C" style={{ marginTop: 48 }} />
          ) : cards.length === 0 ? (
            <EmptyWorld />
          ) : (
            cards.map(card => <WorldCard key={card.id} card={card} />)
          )}
        </View>
      </ScrollView>
    </ImageBackground>
  );
}

function WorldCard({ card }: { card: any }) {
  const isNudge = card.type === 'nudge';
  return (
    <View style={[s.card, isNudge && s.cardNudge]}>
      <View style={s.cardTop}>
        <Text style={s.cardPerson}>{card.personName}</Text>
        {card.timing ? (
          <View style={s.badge}>
            <Text style={s.badgeText}>{card.timing}</Text>
          </View>
        ) : null}
      </View>
      <Text style={s.cardBody}>{card.body}</Text>
      <TouchableOpacity>
        <Text style={s.cardAction}>Ask Genie what to say →</Text>
      </TouchableOpacity>
    </View>
  );
}

function EmptyWorld() {
  return (
    <View style={s.empty}>
      <Text style={s.emptyHeadline}>Genie is still learning your world.</Text>
      <Text style={s.emptySub}>Check back soon.</Text>
    </View>
  );
}

const s = StyleSheet.create({
  bg:         { flex: 1, width, height, backgroundColor: '#0A0A0F' },
  gradTop:    { position: 'absolute', top: 0, left: 0, right: 0, height: height * 0.60, zIndex: 1 },
  gradBottom: { position: 'absolute', bottom: 0, left: 0, right: 0, height: height * 0.35, zIndex: 1 },
  scroll:     { flex: 1, zIndex: 3 },
  content:    { paddingBottom: 40 },

  header: {
    paddingTop: Platform.OS === 'ios' ? 64 : 48,
    paddingHorizontal: 24,
    paddingBottom: 24,
    alignItems: 'center',
  },
  wordmark: {
    fontFamily: 'System', fontSize: 11, fontWeight: '600',
    color: '#C9A84C', letterSpacing: 3.5, textTransform: 'uppercase',
    marginBottom: 12,
  },
  headline: {
    fontFamily: 'Georgia', fontStyle: 'italic',
    fontSize: 28, color: '#F5F0E8', textAlign: 'center', lineHeight: 36,
  },

  feed: { paddingHorizontal: 16, gap: 12 },

  card: {
    backgroundColor: 'rgba(12,12,18,0.88)',
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#1E1E2E',
    padding: 20,
    gap: 8,
  },
  cardNudge: {
    borderLeftWidth: 3,
    borderLeftColor: '#C9A84C',
  },
  cardTop:    { flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
  cardPerson: { fontFamily: 'System', fontSize: 13, fontWeight: '600', color: '#C9A84C' },
  badge: {
    backgroundColor: '#C9A84C11',
    borderRadius: 999,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  badgeText:  { fontSize: 11, color: '#C9A84C', fontWeight: '600' },
  cardBody: {
    fontFamily: 'Georgia', fontStyle: 'italic',
    fontSize: 16, color: '#F5F0E8', lineHeight: 26,
  },
  cardAction: { fontSize: 13, color: '#C9A84C' },

  empty: { alignItems: 'center', paddingTop: 64, gap: 8 },
  emptyHeadline: { fontFamily: 'Georgia', fontStyle: 'italic', fontSize: 18, color: '#8A8070', textAlign: 'center' },
  emptySub:      { fontSize: 14, color: '#4A4438', textAlign: 'center' },
});
