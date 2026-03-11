/**
 * Screen 6 — Notification preference.
 * Three choices: Mornings / Evenings / When it matters.
 * Single select, gold highlight on chosen.
 */
import React, { useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity,
} from 'react-native';
import { COLORS, FONTS, CARD } from '../../theme';

const OPTIONS = [
  { id: 'mornings',        label: 'Mornings',        sub: 'Genie checks in before your day starts.' },
  { id: 'evenings',        label: 'Evenings',        sub: 'A quiet moment at the end of the day.' },
  { id: 'when_it_matters', label: 'When it matters', sub: "Only when Genie has something worth saying." },
];

export default function OnboardNotifScreen({ route, navigation }: any) {
  const params = route.params ?? {};
  const [selected, setSelected] = useState('when_it_matters');

  function handleContinue() {
    navigation.navigate('OnboardWhatsApp', { ...params, notifPref: selected });
  }

  return (
    <View style={s.root}>
      <View style={s.inner}>
        <Text style={s.heading}>When should{'\n'}Genie reach out?</Text>

        {OPTIONS.map((opt) => {
          const active = selected === opt.id;
          return (
            <TouchableOpacity
              key={opt.id}
              style={[CARD, s.option, active && s.optionActive]}
              onPress={() => setSelected(opt.id)}
              activeOpacity={0.75}
            >
              <View style={s.optRow}>
                <View style={[s.radio, active && s.radioActive]} />
                <View style={{ flex: 1 }}>
                  <Text style={[s.optLabel, active && { color: COLORS.accent }]}>{opt.label}</Text>
                  <Text style={s.optSub}>{opt.sub}</Text>
                </View>
              </View>
            </TouchableOpacity>
          );
        })}
      </View>

      <TouchableOpacity style={s.btn} onPress={handleContinue}>
        <Text style={s.btnText}>Continue</Text>
      </TouchableOpacity>
    </View>
  );
}

const s = StyleSheet.create({
  root:        { flex: 1, backgroundColor: COLORS.bg, padding: 24 },
  inner:       { flex: 1, justifyContent: 'center' },
  heading:     { ...FONTS.heading, fontSize: 28, lineHeight: 40, marginBottom: 28 },
  option:      { marginBottom: 10 },
  optionActive:{ borderWidth: 1.5, borderColor: COLORS.accent },
  optRow:      { flexDirection: 'row', alignItems: 'flex-start', gap: 14 },
  radio:       {
    width: 20, height: 20, borderRadius: 10,
    borderWidth: 1.5, borderColor: COLORS.muted,
    marginTop: 2,
  },
  radioActive: { borderColor: COLORS.accent, backgroundColor: COLORS.accent },
  optLabel:    { ...FONTS.sub, fontSize: 16, marginBottom: 3 },
  optSub:      { ...FONTS.label, lineHeight: 18 },
  btn:         {
    backgroundColor: COLORS.accent, borderRadius: 14,
    padding: 18, alignItems: 'center',
  },
  btnText:     { color: COLORS.bg, fontWeight: '700', fontSize: 16 },
});
