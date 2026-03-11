/**
 * Screen 3 — First relationship.
 * Who matters most? Free text, warm framing.
 */
import React, { useRef, useEffect, useState } from 'react';
import {
  View, Text, TextInput, StyleSheet, TouchableOpacity,
  KeyboardAvoidingView, Platform, Animated,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { COLORS, FONTS } from '../../theme';

export default function OnboardFirstRelationshipScreen({ route, navigation }: any) {
  const name  = route.params?.name ?? '';
  const [person, setPerson] = useState('');
  const fade = useRef(new Animated.Value(0)).current;
  const inputRef = useRef<TextInput>(null);

  useEffect(() => {
    Animated.timing(fade, { toValue: 1, duration: 600, useNativeDriver: true }).start();
    setTimeout(() => inputRef.current?.focus(), 600);
  }, []);

  async function handleNext() {
    const p = person.trim();
    if (!p) return;
    await AsyncStorage.setItem('pg_onboard_first_person', p);
    navigation.navigate('OnboardConnectSources', { name, firstPerson: p });
  }

  return (
    <KeyboardAvoidingView
      style={s.root}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <Animated.View style={[s.inner, { opacity: fade }]}>
        <Text style={s.prompt}>
          {name ? `${name}, who's the one person` : "Who's the one person"}
          {'\n'}you most want{'\n'}to stay closer to?
        </Text>
        <Text style={s.hint}>
          A friend, family, someone you've been meaning to call.
        </Text>
        <TextInput
          ref={inputRef}
          style={s.input}
          placeholder="Their name"
          placeholderTextColor={COLORS.muted}
          value={person}
          onChangeText={setPerson}
          autoCapitalize="words"
          returnKeyType="done"
          onSubmitEditing={handleNext}
          selectionColor={COLORS.accent}
        />
        <TouchableOpacity
          style={[s.btn, !person.trim() && { opacity: 0.35 }]}
          onPress={handleNext}
          disabled={!person.trim()}
        >
          <Text style={s.btnText}>Continue</Text>
        </TouchableOpacity>
      </Animated.View>
    </KeyboardAvoidingView>
  );
}

const s = StyleSheet.create({
  root:   { flex: 1, backgroundColor: COLORS.bg },
  inner:  { flex: 1, justifyContent: 'center', padding: 32 },
  prompt: { ...FONTS.heading, fontSize: 28, lineHeight: 40, marginBottom: 10 },
  hint:   { ...FONTS.body, color: COLORS.muted, marginBottom: 28, lineHeight: 22 },
  input:  {
    borderBottomWidth: 1.5, borderBottomColor: COLORS.accent,
    fontSize: 22, color: COLORS.text, paddingVertical: 12,
    marginBottom: 40, fontWeight: '300',
  },
  btn:    {
    backgroundColor: COLORS.accent, borderRadius: 14,
    padding: 18, alignItems: 'center',
  },
  btnText:{ color: COLORS.bg, fontWeight: '700', fontSize: 16 },
});
