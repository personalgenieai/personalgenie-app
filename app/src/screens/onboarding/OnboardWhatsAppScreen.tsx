/**
 * Screen 7 — WhatsApp + Bluetooth speakers.
 * Explains WhatsApp as primary home. Shows QR / deep-link to start chat.
 */
import React from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, Linking,
} from 'react-native';
import { COLORS, FONTS, CARD } from '../../theme';

const GENIE_WA_NUMBER = '+14155238886'; // replace with actual Twilio number

export default function OnboardWhatsAppScreen({ route, navigation }: any) {
  const params = route.params ?? {};

  async function openWhatsApp() {
    const url = `https://wa.me/${GENIE_WA_NUMBER.replace('+', '')}?text=Hi`;
    await Linking.openURL(url).catch(() => {});
  }

  return (
    <View style={s.root}>
      <View style={s.inner}>
        <Text style={s.lamp}>💬</Text>
        <Text style={s.heading}>WhatsApp is{'\n'}Genie's home</Text>
        <Text style={s.body}>
          Most of what Genie does happens in WhatsApp. Moments, insights, quick questions —
          all there. The app is where you review your world.
        </Text>

        <View style={[CARD, s.waCard]}>
          <TouchableOpacity onPress={openWhatsApp} activeOpacity={0.8}>
            <Text style={s.waLabel}>Open WhatsApp with Genie</Text>
            <Text style={s.waHint}>Say hi. Genie is already waiting.</Text>
            <Text style={s.waArrow}>→</Text>
          </TouchableOpacity>
        </View>

        <View style={[CARD, s.btCard]}>
          <Text style={s.btLabel}>Bluetooth speakers</Text>
          <Text style={s.btBody}>
            Name a speaker and Genie can play music, read moments aloud,
            and set the mood. Add from Settings anytime.
          </Text>
        </View>
      </View>

      <TouchableOpacity
        style={s.btn}
        onPress={() => navigation.navigate('OnboardReady', params)}
      >
        <Text style={s.btnText}>Continue</Text>
      </TouchableOpacity>
    </View>
  );
}

const s = StyleSheet.create({
  root:      { flex: 1, backgroundColor: COLORS.bg, padding: 24 },
  inner:     { flex: 1, justifyContent: 'center' },
  lamp:      { fontSize: 48, marginBottom: 16 },
  heading:   { ...FONTS.heading, fontSize: 28, lineHeight: 40, marginBottom: 14 },
  body:      { ...FONTS.body, color: COLORS.muted, lineHeight: 24, marginBottom: 24 },
  waCard:    { borderLeftWidth: 3, borderLeftColor: COLORS.accent, marginBottom: 12 },
  waLabel:   { ...FONTS.sub },
  waHint:    { ...FONTS.label, marginTop: 4, marginBottom: 8 },
  waArrow:   { color: COLORS.accent, fontSize: 18 },
  btCard:    { marginBottom: 8 },
  btLabel:   { ...FONTS.sub, marginBottom: 6 },
  btBody:    { ...FONTS.body, color: COLORS.muted, lineHeight: 22 },
  btn:       {
    backgroundColor: COLORS.accent, borderRadius: 14,
    padding: 18, alignItems: 'center',
  },
  btnText:   { color: COLORS.bg, fontWeight: '700', fontSize: 16 },
});
