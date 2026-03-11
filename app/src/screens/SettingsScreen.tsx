/**
 * SettingsScreen — full settings panel.
 * Sections: Profile · Connections · Plan · Data & Privacy · Sign out
 */
import React, { useEffect, useState, useCallback } from 'react';
import {
  View, Text, ScrollView, StyleSheet, TouchableOpacity,
  Alert, Linking, Platform, ActivityIndicator,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  clearSession, getMe, getSpotifyStatus, getSpotifyConnectUrl,
  getOutboundPermissions, getBillingPortalUrl, getGoogleConnectUrl,
} from '../api';
import { COLORS, FONTS, SPACING, RADIUS } from '../theme';
import type { User } from '../types';

const TWILIO_WA_NUMBER = '14155238886';

// ── Connection Row ─────────────────────────────────────────────────────────────

interface ConnectionRowProps {
  icon: string;
  label: string;
  connected: boolean | null;
  statusLabel?: string;
  onPress: () => void;
}

function ConnectionRow({ icon, label, connected, statusLabel, onPress }: ConnectionRowProps) {
  const status =
    connected === null
      ? '…'
      : statusLabel ?? (connected ? 'Connected' : 'Set up');

  const dotColor =
    connected === null ? COLORS.textTertiary :
    connected          ? COLORS.success      : COLORS.border;

  return (
    <TouchableOpacity style={s.connRow} onPress={onPress} activeOpacity={0.7}>
      <Text style={s.connIcon}>{icon}</Text>
      <Text style={s.connLabel}>{label}</Text>
      <View style={s.connRight}>
        <View style={[s.dot, { backgroundColor: dotColor }]} />
        <Text style={[s.connStatus, connected && s.connStatusActive]}>
          {connected === null ? <ActivityIndicator size="small" color={COLORS.textTertiary} /> : status}
        </Text>
      </View>
      <Text style={s.chevron}>›</Text>
    </TouchableOpacity>
  );
}

function SectionLabel({ title }: { title: string }) {
  return <Text style={s.sectionLabel}>{title}</Text>;
}

function Divider() {
  return <View style={s.divider} />;
}

// ── Main ────────────────────────────────────────────────────────────────────────

export default function SettingsScreen({ navigation }: any) {
  const [user, setUser] = useState<User | null>(null);
  const [spotifyStatus, setSpotifyStatus] = useState<{ connected: boolean; display_name?: string } | null>(null);
  const [accessCount, setAccessCount] = useState<number | null>(null);
  const [googleConnected, setGoogleConnected]     = useState<boolean | null>(null);
  const [imessageConnected, setImessageConnected] = useState<boolean | null>(null);
  const [appleMusicConnected, setAppleMusicConnected] = useState<boolean | null>(null);
  const [calendarConnected, setCalendarConnected] = useState<boolean | null>(null);
  const [plaidConnected, setPlaidConnected]       = useState<boolean | null>(null);
  const [privacyExpanded, setPrivacyExpanded]     = useState(false);

  const loadData = useCallback(async () => {
    try {
      const me = await getMe();
      setUser(me);
    } catch (_) {
      const n = await AsyncStorage.getItem('pg_user_name');
      if (n) setUser({ user_id: '', name: n, phone: '', whatsapp_consented: false });
    }

    try {
      const sp = await getSpotifyStatus();
      setSpotifyStatus(sp);
    } catch (_) {
      setSpotifyStatus({ connected: false });
    }

    try {
      const { grants } = await getOutboundPermissions();
      setAccessCount(grants.length);
    } catch (_) {
      setAccessCount(0);
    }

    const [google, imessage, appleMusic, calendar, plaid] = await Promise.all([
      AsyncStorage.getItem('pg_google_connected'),
      AsyncStorage.getItem('pg_imessage_connected'),
      AsyncStorage.getItem('pg_apple_music_connected'),
      AsyncStorage.getItem('pg_calendar_connected'),
      AsyncStorage.getItem('pg_plaid_connected'),
    ]);
    setGoogleConnected(google === 'true');
    setImessageConnected(imessage === 'true');
    setAppleMusicConnected(appleMusic === 'true');
    setCalendarConnected(calendar === 'true');
    setPlaidConnected(plaid === 'true');
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  // ── Handlers ──────────────────────────────────────────────────────────────────

  async function handleWhatsApp() {
    await Linking.openURL(`https://wa.me/${TWILIO_WA_NUMBER}`);
  }

  async function handleGoogle() {
    try {
      const { auth_url } = await getGoogleConnectUrl();
      await Linking.openURL(auth_url);
      await AsyncStorage.setItem('pg_google_connected', 'true');
      setGoogleConnected(true);
    } catch (_) {
      Alert.alert('Could not connect Google', 'Try again in a moment.');
    }
  }

  function handleIMessage() {
    Alert.alert(
      'iMessage — Mac companion required',
      'iMessage sync requires the Personal Genie Mac companion app. Install it on your Mac, then sign in with the same phone number.',
      [{ text: 'Got it' }],
    );
  }

  async function handleSpotify() {
    try {
      const { auth_url } = await getSpotifyConnectUrl();
      await Linking.openURL(auth_url);
    } catch (_) {
      Alert.alert('Could not connect Spotify', 'Try again in a moment.');
    }
  }

  function handleAppleMusic() {
    Alert.alert(
      'Apple Music',
      'Apple Music integration is coming soon. Genie will read your listening history for mood and context.',
      [{ text: 'OK' }],
    );
  }

  function handleCalendar() {
    Alert.alert(
      'Apple Calendar',
      'Grant calendar access in Settings. Genie reads event titles and times only — no notes or attendees.',
      [
        { text: 'Open Settings', onPress: () => Linking.openURL('app-settings:') },
        { text: 'Dismiss', style: 'cancel' },
      ],
    );
  }

  function handlePlaid() {
    Alert.alert(
      'Financial data via Plaid',
      'Genie uses Plaid to read transaction categories — never account numbers or balances.',
      [
        { text: 'Connect', onPress: () => Alert.alert('Plaid Link', 'Coming soon.') },
        { text: 'Cancel', style: 'cancel' },
      ],
    );
  }

  function handleSpeakers() {
    Alert.alert(
      'Bluetooth Speakers',
      'Send Genie a message:\n\n"Register speaker [Name]"\n\nGenie will associate it with your home.',
      [{ text: 'Got it' }],
    );
  }

  function handleAppleTV() {
    Alert.alert(
      'Apple TV',
      'Genie can control your Apple TV. Open the Mac companion app and follow the Apple TV pairing steps.',
      [{ text: 'Got it' }],
    );
  }

  async function handleManageSubscription(planName: string) {
    if (planName !== 'free') {
      try {
        const userId = await AsyncStorage.getItem('pg_user_id');
        if (!userId) return;
        const { portal_url } = await getBillingPortalUrl(userId);
        await Linking.openURL(portal_url);
      } catch (_) {
        Alert.alert('Error', 'Could not open billing portal.');
      }
    } else {
      navigation.navigate('Billing');
    }
  }

  async function handleSignOut() {
    Alert.alert(
      'Sign out',
      "You'll need to verify your phone number again to sign back in.",
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Sign out', style: 'destructive', onPress: async () => await clearSession() },
      ],
    );
  }

  const displayName = user?.name ?? '';
  const displayPhone = user?.phone ?? '';
  const whatsappConsented = user?.whatsapp_consented ?? false;
  const planName: string = 'individual'; // TODO: load from subscription API

  const planLabel: Record<string, string> = {
    free:       'Free',
    individual: 'Individual  ·  $9.99 / mo',
    family:     'Family  ·  $14.99 / mo',
    pro:        'Pro  ·  $24.99 / mo',
  };

  return (
    <ScrollView style={s.root} contentContainerStyle={s.content}>
      <Text style={s.heading}>Settings</Text>

      {/* ── Profile ── */}
      <View style={s.profileCard}>
        <View style={s.profileAvatar}>
          <Text style={s.profileAvatarText}>{displayName[0]?.toUpperCase() ?? '?'}</Text>
        </View>
        <View style={s.profileInfo}>
          <Text style={s.profileName}>{displayName || 'Your account'}</Text>
          {displayPhone ? <Text style={s.profilePhone}>{displayPhone}</Text> : null}
          <View style={s.planBadge}>
            <Text style={s.planBadgeText}>{planName === 'free' ? 'Free plan' : 'Personal Genie'}</Text>
          </View>
        </View>
      </View>

      {/* ── Connections ── */}
      <SectionLabel title="Connections" />
      <View style={s.card}>
        <ConnectionRow icon="💬" label="WhatsApp"       connected={whatsappConsented} statusLabel={whatsappConsented ? 'Connected' : 'Open'} onPress={handleWhatsApp} />
        <Divider />
        <ConnectionRow icon="◉"  label="Google"         connected={googleConnected}  onPress={handleGoogle} />
        {Platform.OS === 'ios' && <>
          <Divider />
          <ConnectionRow icon="✉" label="iMessage"      connected={imessageConnected} onPress={handleIMessage} />
        </>}
        <Divider />
        <ConnectionRow icon="♪"  label="Spotify"        connected={spotifyStatus?.connected ?? null} statusLabel={spotifyStatus?.connected ? (spotifyStatus?.display_name ?? 'Connected') : undefined} onPress={handleSpotify} />
        <Divider />
        <ConnectionRow icon="♫"  label="Apple Music"    connected={appleMusicConnected} onPress={handleAppleMusic} />
        <Divider />
        <ConnectionRow icon="◻"  label="Apple Calendar" connected={calendarConnected}   onPress={handleCalendar} />
        <Divider />
        <ConnectionRow icon="◈"  label="Financial"      connected={plaidConnected}      statusLabel={plaidConnected ? 'Connected' : 'Via Plaid'} onPress={handlePlaid} />
        <Divider />
        <ConnectionRow icon="◎"  label="Speakers"       connected={null} statusLabel="Tap to set up" onPress={handleSpeakers} />
        <Divider />
        <ConnectionRow icon="▣"  label="Apple TV"       connected={null} statusLabel="Tap to set up" onPress={handleAppleTV} />
      </View>

      {/* ── Plan ── */}
      <SectionLabel title="Plan" />
      <View style={s.card}>
        <View style={s.planRow}>
          <View>
            <Text style={s.planName}>
              {planName === 'individual' ? 'Personal Genie' : planName === 'family' ? 'Family' : planName === 'pro' ? 'Pro' : 'Free'}
            </Text>
            <Text style={s.planPrice}>
              {planName === 'individual' ? '$9.99 / month' : planName === 'family' ? '$14.99 / month' : planName === 'pro' ? '$24.99 / month' : 'Free'}
            </Text>
          </View>
          <TouchableOpacity style={s.planBtn} onPress={() => handleManageSubscription(planName)}>
            <Text style={s.planBtnText}>{planName === 'free' ? 'Upgrade' : 'Manage'}</Text>
          </TouchableOpacity>
        </View>
      </View>

      {/* ── Trusted People ── */}
      <SectionLabel title="Trusted People" />
      <TouchableOpacity
        style={[s.card, s.trustedRow]}
        onPress={() => Alert.alert('Trusted People', 'Permission management coming soon.')}
        activeOpacity={0.7}
      >
        <View style={{ flex: 1 }}>
          <Text style={s.trustedTitle}>Shared access</Text>
          <Text style={s.trustedSub}>People who can see your Genie signals</Text>
        </View>
        {accessCount !== null && accessCount > 0 && (
          <View style={s.countBadge}>
            <Text style={s.countBadgeText}>{accessCount}</Text>
          </View>
        )}
        <Text style={s.chevron}>›</Text>
      </TouchableOpacity>

      {/* ── Data & Privacy ── */}
      <SectionLabel title="Data & Privacy" />
      <View style={s.card}>
        <TouchableOpacity
          style={s.privacyHeader}
          onPress={() => setPrivacyExpanded((v) => !v)}
          activeOpacity={0.7}
        >
          <Text style={s.privacyTitle}>What Genie knows</Text>
          <Text style={s.privacyToggle}>{privacyExpanded ? '▲' : '▼'}</Text>
        </TouchableOpacity>
        {privacyExpanded ? (
          <Text style={s.privacyBody}>
            Genie builds a private model of your relationships and routines from the sources you
            connect: WhatsApp, Google, iMessage, calendar, and health activity.{'\n\n'}
            All processing happens on Personal Genie's encrypted servers. Your raw messages are
            never stored — only structured patterns and summaries.{'\n\n'}
            To delete everything, text{' '}
            <Text style={{ color: COLORS.accent, fontWeight: '600' }}>STOP</Text>
            {' '}to Genie on WhatsApp. All data wiped within 24 hours.
          </Text>
        ) : (
          <Text style={s.privacyHint}>
            Text{' '}
            <Text style={{ color: COLORS.accent, fontWeight: '600' }}>STOP</Text>
            {' '}on WhatsApp to delete all your data.
          </Text>
        )}
      </View>

      {/* ── Sign out ── */}
      <TouchableOpacity style={s.signOut} onPress={handleSignOut}>
        <Text style={s.signOutText}>Sign out</Text>
      </TouchableOpacity>

      <View style={{ height: SPACING.xxxl }} />
    </ScrollView>
  );
}

const s = StyleSheet.create({
  root:    { flex: 1, backgroundColor: COLORS.bg },
  content: { padding: SPACING.xl, paddingTop: 64, paddingBottom: SPACING.xxxl },

  heading: {
    ...FONTS.display,
    fontSize: 26,
    marginBottom: SPACING.xl,
  },

  // Profile
  profileCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.lg,
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    padding: SPACING.lg,
    marginBottom: SPACING.xl,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  profileAvatar: {
    width: 56, height: 56, borderRadius: 28,
    backgroundColor: COLORS.accentDim,
    borderWidth: 1.5, borderColor: COLORS.accentBorder,
    justifyContent: 'center', alignItems: 'center',
  },
  profileAvatarText: { color: COLORS.accent, fontWeight: '700', fontSize: 22 },
  profileInfo:  { flex: 1 },
  profileName:  { ...FONTS.sub },
  profilePhone: { ...FONTS.label, marginTop: 3 },
  planBadge: {
    marginTop: SPACING.sm, alignSelf: 'flex-start',
    backgroundColor: COLORS.accentDim,
    borderRadius: RADIUS.pill,
    paddingHorizontal: SPACING.sm, paddingVertical: 3,
    borderWidth: 1, borderColor: COLORS.accentBorder,
  },
  planBadgeText: { ...FONTS.caption, color: COLORS.accent },

  // Section
  sectionLabel: {
    ...FONTS.caption,
    textTransform: 'uppercase',
    letterSpacing: 1.2,
    marginBottom: SPACING.sm,
    marginTop: SPACING.lg,
  },

  // Card
  card: {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    paddingHorizontal: SPACING.lg,
    borderWidth: 1,
    borderColor: COLORS.border,
  },

  // Connection row
  connRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: SPACING.md,
    gap: SPACING.md,
  },
  connIcon:         { fontSize: 16, width: 24, textAlign: 'center', color: COLORS.textSecondary },
  connLabel:        { ...FONTS.body, flex: 1 },
  connRight:        { flexDirection: 'row', alignItems: 'center', gap: SPACING.xs },
  dot:              { width: 6, height: 6, borderRadius: 3 },
  connStatus:       { ...FONTS.label, color: COLORS.textTertiary },
  connStatusActive: { color: COLORS.success },
  chevron:          { color: COLORS.textTertiary, fontSize: 18 },
  divider:          { height: 1, backgroundColor: COLORS.border },

  // Plan
  planRow:    {
    flexDirection: 'row', alignItems: 'center',
    justifyContent: 'space-between', paddingVertical: SPACING.lg,
  },
  planName:   { ...FONTS.sub },
  planPrice:  { ...FONTS.label, marginTop: 3 },
  planBtn:    {
    borderWidth: 1, borderColor: COLORS.accentBorder,
    borderRadius: RADIUS.sm,
    paddingHorizontal: SPACING.lg, paddingVertical: SPACING.sm,
  },
  planBtnText: { color: COLORS.accent, fontWeight: '600', fontSize: 14 },

  // Trusted people
  trustedRow:  { flexDirection: 'row', alignItems: 'center', padding: SPACING.lg },
  trustedTitle:{ ...FONTS.body },
  trustedSub:  { ...FONTS.label, marginTop: 2 },
  countBadge:  {
    backgroundColor: COLORS.accentDim, borderRadius: RADIUS.pill,
    paddingHorizontal: SPACING.sm, paddingVertical: 3,
    marginRight: SPACING.sm,
  },
  countBadgeText: { ...FONTS.caption, color: COLORS.accent, fontWeight: '600' },

  // Privacy
  privacyHeader: {
    flexDirection: 'row', justifyContent: 'space-between',
    alignItems: 'center', paddingVertical: SPACING.lg,
  },
  privacyTitle:  { ...FONTS.body },
  privacyToggle: { color: COLORS.textTertiary, fontSize: 12 },
  privacyBody:   { ...FONTS.label, lineHeight: 20, paddingBottom: SPACING.lg },
  privacyHint:   { ...FONTS.label, lineHeight: 18, paddingBottom: SPACING.lg },

  // Sign out
  signOut: {
    marginTop: SPACING.xl,
    paddingVertical: SPACING.lg,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.error + '66',
    alignItems: 'center',
  },
  signOutText: { color: COLORS.error, fontWeight: '600', fontSize: 15 },
});
