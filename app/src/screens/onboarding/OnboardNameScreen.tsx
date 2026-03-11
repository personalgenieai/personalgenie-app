/**
 * OnboardNameScreen — Name entry.
 * bg_onboard.png background. Navigation logic preserved.
 */
import React, { useRef, useEffect, useState } from 'react';
import {
  View, Text, TextInput, StyleSheet, TouchableOpacity,
  KeyboardAvoidingView, Platform, ImageBackground, Dimensions, Animated,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import AsyncStorage from '@react-native-async-storage/async-storage';

const { width, height } = Dimensions.get('window');
const BG = require('../../../assets/bg_onboard.png');

export default function OnboardNameScreen({ navigation }: any) {
  const [name, setName] = useState('');
  const fade = useRef(new Animated.Value(0)).current;
  const inputRef = useRef<TextInput>(null);

  useEffect(() => {
    Animated.timing(fade, { toValue: 1, duration: 600, useNativeDriver: true }).start();
    setTimeout(() => inputRef.current?.focus(), 700);
  }, []);

  async function handleNext() {
    const n = name.trim();
    if (!n) return;
    await AsyncStorage.setItem('pg_onboard_name', n);
    navigation.navigate('OnboardRelationship', { name: n });
  }

  return (
    <ImageBackground source={BG} style={{ flex: 1, width, height, backgroundColor: '#0A0A0F' }} resizeMode="cover">
      <LinearGradient
        colors={['rgba(5,4,10,0.85)', 'rgba(5,4,10,0.3)', 'transparent']}
        style={{ position: 'absolute', top: 0, left: 0, right: 0, height: height * 0.38, zIndex: 1 }}
        pointerEvents="none"
      />
      <LinearGradient
        colors={['transparent', 'rgba(5,4,10,0.85)', 'rgba(5,4,10,0.99)']}
        style={{ position: 'absolute', bottom: 0, left: 0, right: 0, height: height * 0.45, zIndex: 1 }}
        pointerEvents="none"
      />
      <KeyboardAvoidingView
        style={s.kav}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <Animated.View style={[s.content, { opacity: fade }]}>
          {/* Top: wordmark */}
          <View style={s.top}>
            <Text style={s.wordmark}>PERSONAL GENIE</Text>
          </View>

          {/* Bottom form */}
          <View style={s.form}>
            <Text style={s.formLabel}>What should I call you?</Text>
            <TextInput
              ref={inputRef}
              style={s.input}
              placeholder="Your name"
              placeholderTextColor="#4A4438"
              value={name}
              onChangeText={setName}
              autoCapitalize="words"
              returnKeyType="done"
              onSubmitEditing={handleNext}
              selectionColor="#C9A84C"
            />
            <TouchableOpacity
              style={[s.btn, !name.trim() && { opacity: 0.35 }]}
              onPress={handleNext}
              disabled={!name.trim()}
              activeOpacity={0.85}
            >
              <Text style={s.btnText}>Continue</Text>
            </TouchableOpacity>
          </View>
        </Animated.View>
      </KeyboardAvoidingView>
    </ImageBackground>
  );
}

const s = StyleSheet.create({
  kav: { flex: 1 },
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
  },
  form: { gap: 16 },
  formLabel: {
    fontFamily: 'Georgia',
    fontStyle: 'italic',
    fontSize: 26,
    color: '#F5F0E8',
    marginBottom: 8,
  },
  input: {
    backgroundColor: 'rgba(12,12,18,0.85)',
    borderWidth: 1,
    borderColor: '#2A2740',
    borderRadius: 12,
    paddingHorizontal: 18,
    paddingVertical: 16,
    fontSize: 18,
    color: '#F5F0E8',
  },
  btn: {
    backgroundColor: '#C9A84C',
    borderRadius: 14,
    paddingVertical: 16,
    alignItems: 'center',
  },
  btnText: { color: '#0A0A0F', fontWeight: '700', fontSize: 16 },
});
