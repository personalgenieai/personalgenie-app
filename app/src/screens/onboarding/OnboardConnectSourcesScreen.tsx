/**
 * OnboardConnectSourcesScreen — Connect data sources.
 * bg_ingestion.png background. All OAuth/toggle logic preserved.
 */
import React, { useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, Switch, ScrollView,
  ActivityIndicator, Alert, Linking, ImageBackground, Dimensions, Platform,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { getSpotifyConnectUrl, getBaseUrl } from '../../api';

const { width, height } = Dimensions.get('window');
const BG = require('../../../assets/bg_ingestion.png');

interface Source {
  id:          string;
  label:       string;
  description: string;
  action:      'toggle' | 'oauth';
}

const SOURCES: Source[] = [
  {
    id:          'google',
    label:       'Google',
    description: 'Gmail · Photos · Contacts',
    action:      'oauth',
  },
  {
    id:          'imessage',
    label:       'iMessage',
    description: 'Message patterns, processed locally',
    action:      'toggle',
  },
  {
    id:          'calendar',
    label:       'Apple Calendar',
    description: 'Personal events only',
    action:      'toggle',
  },
  {
    id:          'spotify',
    label:       'Spotify',
    description: 'Listening history and mood',
    action:      'oauth',
  },
  {
    id:          'apple_music',
    label:       'Apple Music',
    description: 'Listening history and mood',
    action:      'toggle',
  },
];

export default function OnboardConnectSourcesScreen({ route, navigation }: any) {
  const { name, firstPerson } = route.params ?? {};
  const [connected, setConnected] = useState<Record<string, boolean>>({});
  const [loading, setLoading]     = useState<string | null>(null);

  async function handleSource(source: Source) {
    if (source.action === 'toggle') {
      setConnected((prev) => ({ ...prev, [source.id]: !prev[source.id] }));
      return;
    }

    if (source.id === 'google') {
      const userId = await AsyncStorage.getItem('pg_user_id');
      if (!userId) return;
      setLoading('google');
      try {
        const base = await getBaseUrl();
        const resp = await fetch(`${base}/auth/google/url?user_id=${userId}`);
        const { auth_url } = await resp.json();
        await Linking.openURL(auth_url);
        setConnected((prev) => ({ ...prev, google: true }));
      } catch (_) {
        Alert.alert('Could not connect Google', 'Try again from Settings.');
      } finally {
        setLoading(null);
      }
    }

    if (source.id === 'spotify') {
      setLoading('spotify');
      try {
        const { auth_url } = await getSpotifyConnectUrl();
        await Linking.openURL(auth_url);
        setConnected((prev) => ({ ...prev, spotify: true }));
      } catch (_) {
        Alert.alert('Could not connect Spotify', 'Try again from Settings.');
      } finally {
        setLoading(null);
      }
    }
  }

  function handleContinue() {
    navigation.navigate('OnboardIngestion', { name, firstPerson, connected });
  }

  const anyConnected = Object.values(connected).some(Boolean);

  return (
    <ImageBackground source={BG} style={{ flex: 1, width, height, backgroundColor: '#0A0A0F' }} resizeMode="cover">
      <LinearGradient
        colors={['rgba(5,4,10,0.75)', 'rgba(5,4,10,0.2)', 'transparent']}
        style={{ position: 'absolute', top: 0, left: 0, right: 0, height: height * 0.35, zIndex: 1 }}
        pointerEvents="none"
      />
      <LinearGradient
        colors={['transparent', 'rgba(5,4,10,0.82)', 'rgba(5,4,10,0.99)']}
        style={{ position: 'absolute', bottom: 0, left: 0, right: 0, height: height * 0.62, zIndex: 1 }}
        pointerEvents="none"
      />

      <View style={s.content}>
        {/* Top title */}
        <View style={s.top}>
          <Text style={s.wordmark}>PERSONAL GENIE</Text>
          <Text style={s.headline}>Connect your world.</Text>
          <Text style={s.sub}>The more Genie sees, the better it knows you.</Text>
        </View>

        {/* Source list */}
        <View style={s.bottom}>
          {SOURCES.map((src) => (
            <SourceRow
              key={src.id}
              source={src}
              connected={!!connected[src.id]}
              loading={loading === src.id}
              onPress={() => handleSource(src)}
            />
          ))}

          <TouchableOpacity
            style={[s.btn, !anyConnected && s.btnSecondary]}
            onPress={handleContinue}
            activeOpacity={0.85}
          >
            <Text style={[s.btnText, !anyConnected && s.btnTextSecondary]}>
              {anyConnected ? 'Continue' : 'Skip for now'}
            </Text>
          </TouchableOpacity>
        </View>
      </View>
    </ImageBackground>
  );
}

function SourceRow({
  source, connected, loading, onPress,
}: {
  source: Source;
  connected: boolean;
  loading: boolean;
  onPress: () => void;
}) {
  return (
    <View style={r.row}>
      <View style={r.info}>
        <Text style={r.label}>{source.label}</Text>
        <Text style={r.desc}>{source.description}</Text>
      </View>
      {source.action === 'toggle' ? (
        <Switch
          value={connected}
          onValueChange={onPress}
          trackColor={{ false: '#1E1E2E', true: '#C9A84C' }}
          thumbColor={connected ? '#F5F0E8' : '#4A4438'}
          ios_backgroundColor="#1E1E2E"
        />
      ) : loading ? (
        <ActivityIndicator color="#C9A84C" size="small" />
      ) : (
        <TouchableOpacity
          style={[r.btn, connected && r.btnConnected]}
          onPress={onPress}
          activeOpacity={0.75}
        >
          <Text style={[r.btnText, connected && r.btnTextConnected]}>
            {connected ? '✓ Done' : 'Connect'}
          </Text>
        </TouchableOpacity>
      )}
    </View>
  );
}

const s = StyleSheet.create({
  content: {
    flex: 1,
    zIndex: 3,
    justifyContent: 'space-between',
    paddingTop: Platform.OS === 'ios' ? 64 : 48,
    paddingBottom: Platform.OS === 'ios' ? 48 : 36,
    paddingHorizontal: 32,
  },
  top: { alignItems: 'center' },
  wordmark: {
    fontFamily: 'System',
    fontSize: 11,
    fontWeight: '600',
    color: '#C9A84C',
    letterSpacing: 3.5,
    textTransform: 'uppercase',
    marginBottom: 12,
  },
  headline: {
    fontFamily: 'Georgia',
    fontStyle: 'italic',
    fontSize: 24,
    color: '#F5F0E8',
    textAlign: 'center',
    marginBottom: 4,
  },
  sub: {
    fontSize: 15,
    color: '#8A8070',
    textAlign: 'center',
    marginBottom: 0,
  },
  bottom: { gap: 8 },
  btn: {
    backgroundColor: '#C9A84C',
    borderRadius: 14,
    paddingVertical: 16,
    alignItems: 'center',
    marginTop: 8,
  },
  btnSecondary: {
    backgroundColor: 'transparent',
    borderWidth: 1,
    borderColor: '#C9A84C44',
  },
  btnText:          { color: '#0A0A0F', fontWeight: '700', fontSize: 16 },
  btnTextSecondary: { color: '#C9A84C', fontWeight: '600', fontSize: 16 },
});

const r = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(12,12,18,0.82)',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#C9A84C44',
    paddingHorizontal: 16,
    paddingVertical: 14,
    gap: 12,
  },
  info:  { flex: 1 },
  label: { fontFamily: 'System', fontSize: 15, fontWeight: '600', color: '#F5F0E8' },
  desc:  { fontFamily: 'System', fontSize: 12, color: '#8A8070', marginTop: 2 },
  btn: {
    borderWidth: 1,
    borderColor: '#C9A84C44',
    borderRadius: 8,
    paddingHorizontal: 14,
    paddingVertical: 6,
  },
  btnConnected:     { backgroundColor: '#C9A84C18', borderColor: '#C9A84C44' },
  btnText:          { color: '#C9A84C', fontSize: 13, fontWeight: '600' },
  btnTextConnected: { color: '#C9A84C' },
});
