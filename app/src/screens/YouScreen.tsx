/**
 * YouScreen — Profile + minimal settings.
 * bg_splash.png as atmospheric background (heavy gradients, lamp faint).
 */
import React, { useEffect, useState, useCallback } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, Switch,
  ImageBackground, Dimensions, Platform, ScrollView, Alert,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { useFocusEffect } from '@react-navigation/native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { clearSession, getSpotifyStatus, getSubscription } from '../api';

const { width, height } = Dimensions.get('window');
const BG = require('../../assets/bg_splash.png');

export default function YouScreen() {
  const [name, setName]           = useState('');
  const [phone, setPhone]         = useState('');
  const [plan, setPlan]           = useState('free');
  const [spotifyConnected, setSpotifyConnected] = useState(false);
  const [notifs, setNotifs]       = useState(true);

  useFocusEffect(useCallback(() => {
    async function load() {
      const [n, p, uid] = await Promise.all([
        AsyncStorage.getItem('pg_user_name'),
        AsyncStorage.getItem('pg_user_phone'),
        AsyncStorage.getItem('pg_user_id'),
      ]);
      if (n) setName(n);
      if (p) setPhone(p);
      if (uid) {
        getSpotifyStatus().then(s => setSpotifyConnected(s.connected)).catch(() => {});
        getSubscription(uid).then(s => setPlan(s.plan)).catch(() => {});
      }
    }
    load();
  }, []));

  async function handleSignOut() {
    Alert.alert('Sign out', 'Are you sure?', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Sign out', style: 'destructive',
        onPress: async () => {
          await clearSession();
          // App.tsx polling will detect no token and show onboarding
        },
      },
    ]);
  }

  const firstName = name.split(' ')[0];

  return (
    <ImageBackground source={BG} style={s.bg} resizeMode="cover">
      <LinearGradient
        colors={['rgba(5,4,10,0.94)', 'rgba(5,4,10,0.5)', 'transparent']}
        style={s.gradTop}
        pointerEvents="none"
      />
      <LinearGradient
        colors={['transparent', 'rgba(5,4,10,0.88)', 'rgba(5,4,10,0.98)']}
        style={s.gradBottom}
        pointerEvents="none"
      />

      <ScrollView style={s.scroll} contentContainerStyle={s.content} showsVerticalScrollIndicator={false}>
        {/* Wordmark */}
        <View style={s.header}>
          <Text style={s.wordmark}>PERSONAL GENIE</Text>
        </View>

        {/* User identity */}
        <View style={s.identity}>
          <Text style={s.identityName}>{firstName || 'Your Name'}</Text>
          {phone ? <Text style={s.identityPhone}>{phone}</Text> : null}
          <View style={s.goldDot} />
        </View>

        {/* Connected sources */}
        <SectionCard title="Connected Sources">
          <SourceRow label="Spotify" connected={spotifyConnected} />
          <SourceRow label="Google" connected={false} />
          <SourceRow label="iMessage" connected={false} />
          <SourceRow label="Apple Calendar" connected={false} />
        </SectionCard>

        {/* Teach Genie */}
        <SectionCard title="Teach Genie">
          <TouchableOpacity style={s.row}>
            <Text style={s.rowLabel}>My rules &amp; preferences</Text>
            <Text style={s.rowArrow}>›</Text>
          </TouchableOpacity>
        </SectionCard>

        {/* Notifications */}
        <SectionCard title="Notifications">
          <View style={s.row}>
            <Text style={s.rowLabel}>Daily briefing</Text>
            <Switch
              value={notifs}
              onValueChange={setNotifs}
              trackColor={{ false: '#1E1E2E', true: '#C9A84C' }}
              thumbColor={notifs ? '#F5F0E8' : '#4A4438'}
              ios_backgroundColor="#1E1E2E"
            />
          </View>
        </SectionCard>

        {/* Plan */}
        <SectionCard title="Plan">
          <View style={s.row}>
            <Text style={s.rowLabel}>{plan === 'free' ? 'Free' : plan}</Text>
            <TouchableOpacity>
              <Text style={s.rowAction}>Manage →</Text>
            </TouchableOpacity>
          </View>
        </SectionCard>

        {/* Sign out */}
        <TouchableOpacity style={s.signOutBtn} onPress={handleSignOut}>
          <Text style={s.signOutText}>Sign out</Text>
        </TouchableOpacity>
      </ScrollView>
    </ImageBackground>
  );
}

function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={s.sectionCard}>
      <Text style={s.sectionTitle}>{title}</Text>
      {children}
    </View>
  );
}

function SourceRow({ label, connected }: { label: string; connected: boolean }) {
  return (
    <View style={s.row}>
      <View style={[s.sourceDot, connected && s.sourceDotActive]} />
      <Text style={s.rowLabel}>{label}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  bg:         { flex: 1, width, height, backgroundColor: '#0A0A0F' },
  gradTop:    { position: 'absolute', top: 0, left: 0, right: 0, height: height * 0.42, zIndex: 1 },
  gradBottom: { position: 'absolute', bottom: 0, left: 0, right: 0, height: height * 0.40, zIndex: 1 },
  scroll:     { flex: 1, zIndex: 3 },
  content:    { paddingBottom: 48 },

  header: {
    paddingTop: Platform.OS === 'ios' ? 64 : 48,
    alignItems: 'center',
    marginBottom: 8,
  },
  wordmark: {
    fontFamily: 'System', fontSize: 11, fontWeight: '600',
    color: '#C9A84C', letterSpacing: 3.5, textTransform: 'uppercase',
  },

  identity:     { alignItems: 'center', paddingVertical: 32, gap: 6 },
  identityName: { fontFamily: 'Georgia', fontStyle: 'italic', fontSize: 28, color: '#F5F0E8' },
  identityPhone:{ fontSize: 14, color: '#8A8070' },
  goldDot:      { width: 5, height: 5, borderRadius: 2.5, backgroundColor: '#C9A84C', marginTop: 4 },

  sectionCard: {
    marginHorizontal: 16,
    marginBottom: 12,
    backgroundColor: 'rgba(12,12,18,0.82)',
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#1E1E2E',
    paddingHorizontal: 20,
    paddingVertical: 8,
  },
  sectionTitle: {
    fontSize: 11, fontWeight: '600', color: '#4A4438',
    letterSpacing: 1.2, textTransform: 'uppercase',
    paddingTop: 12, paddingBottom: 8,
    borderBottomWidth: 1, borderBottomColor: '#1E1E2E',
    marginBottom: 4,
  },
  row: {
    flexDirection: 'row', alignItems: 'center',
    paddingVertical: 14,
    borderBottomWidth: 1, borderBottomColor: '#1E1E2E',
    gap: 10,
  },
  rowLabel:  { flex: 1, fontSize: 15, color: '#F5F0E8', fontWeight: '500' },
  rowArrow:  { fontSize: 20, color: '#4A4438' },
  rowAction: { fontSize: 13, color: '#C9A84C', fontWeight: '600' },
  sourceDot: {
    width: 8, height: 8, borderRadius: 4,
    borderWidth: 1.5, borderColor: '#4A4438',
  },
  sourceDotActive: { backgroundColor: '#C9A84C', borderColor: '#C9A84C' },

  signOutBtn: {
    marginHorizontal: 16,
    marginTop: 8,
    backgroundColor: 'transparent',
    borderWidth: 1, borderColor: '#2A2740',
    borderRadius: 14, paddingVertical: 16,
    alignItems: 'center',
  },
  signOutText: { color: '#8A8070', fontSize: 16, fontWeight: '600' },
});
