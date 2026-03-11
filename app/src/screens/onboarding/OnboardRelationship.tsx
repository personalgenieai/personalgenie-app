/**
 * OnboardRelationship — "Who is the most important person in your life?"
 * New screen. bg_relationship.png background.
 */
import React, { useRef, useEffect, useState } from 'react';
import {
  View, Text, TextInput, StyleSheet, TouchableOpacity,
  KeyboardAvoidingView, Platform, ImageBackground, Dimensions,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { NativeStackScreenProps } from '@react-navigation/native-stack';
import { OnboardingStackParams } from '../../navigation/OnboardingNavigator';

const { width, height } = Dimensions.get('window');
const BG = require('../../../assets/bg_relationship.png');

type Props = NativeStackScreenProps<OnboardingStackParams, 'OnboardRelationship'>;

export default function OnboardRelationship({ route, navigation }: Props) {
  const name = route.params?.name ?? '';
  const [inputValue, setInputValue] = useState('');
  const inputRef = useRef<TextInput>(null);

  useEffect(() => {
    setTimeout(() => inputRef.current?.focus(), 500);
  }, []);

  async function handleNext() {
    const p = inputValue.trim();
    if (!p) return;
    await AsyncStorage.setItem('pg_onboard_first_person', p);
    navigation.navigate('OnboardConnectSources', { name, firstPerson: p });
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
        style={{ position: 'absolute', bottom: 0, left: 0, right: 0, height: height * 0.55, zIndex: 1 }}
        pointerEvents="none"
      />
      <KeyboardAvoidingView
        style={s.kav}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <View style={s.content}>
          {/* Top: wordmark */}
          <View style={s.top}>
            <Text style={s.wordmark}>PERSONAL GENIE</Text>
          </View>

          {/* Bottom form */}
          <View style={s.form}>
            <Text style={s.formLabel}>
              {'Who is the most important\nperson in your life?'}
            </Text>
            <Text style={s.sub}>Your Genie starts here.</Text>
            <TextInput
              ref={inputRef}
              style={s.input}
              placeholder="Their name"
              placeholderTextColor="#4A4438"
              value={inputValue}
              onChangeText={setInputValue}
              autoCapitalize="words"
              returnKeyType="done"
              onSubmitEditing={handleNext}
              selectionColor="#C9A84C"
            />
            <TouchableOpacity
              style={[s.btn, !inputValue.trim() && { opacity: 0.35 }]}
              onPress={handleNext}
              disabled={!inputValue.trim()}
              activeOpacity={0.85}
            >
              <Text style={s.btnText}>Continue</Text>
            </TouchableOpacity>
          </View>
        </View>
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
    textAlign: 'center',
    lineHeight: 36,
    marginBottom: 4,
  },
  sub: {
    fontFamily: 'System',
    fontSize: 15,
    color: '#8A8070',
    textAlign: 'center',
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
