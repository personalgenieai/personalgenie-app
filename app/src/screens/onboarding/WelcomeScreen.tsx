/**
 * WelcomeScreen — Phone number entry.
 * bg_onboard.png background. All requestOTP logic preserved.
 */
import React, { useState, useRef, useEffect } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet,
  Alert, ActivityIndicator, KeyboardAvoidingView, Platform,
  ImageBackground, Animated, Dimensions,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { NativeStackScreenProps } from '@react-navigation/native-stack';
import { OnboardingStackParams } from '../../navigation/OnboardingNavigator';
import { requestOTP } from '../../api';

const { width, height } = Dimensions.get('window');
const BG = require('../../../assets/bg_onboard.png');

type Props = NativeStackScreenProps<OnboardingStackParams, 'Welcome'>;

export default function WelcomeScreen({ navigation }: Props) {
  const [phone, setPhone]     = useState('');
  const [loading, setLoading] = useState(false);
  const fade = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.timing(fade, { toValue: 1, duration: 800, useNativeDriver: true }).start();
  }, [fade]);

  async function handleContinue() {
    const normalized = phone.trim().startsWith('+')
      ? phone.trim()
      : `+1${phone.trim().replace(/\D/g, '')}`;
    if (normalized.replace(/\D/g, '').length < 10) {
      Alert.alert('Enter your phone number', 'Include country code, e.g. +14155551234');
      return;
    }
    setLoading(true);
    try {
      await requestOTP(normalized);
      navigation.navigate('OTP', { phone: normalized });
    } catch (e: any) {
      Alert.alert(
        'Account not found',
        e.message?.includes('No Genie account')
          ? 'Sign up at personalgenie.ai first, then come back here.'
          : e.message ?? 'Something went wrong.',
      );
    } finally {
      setLoading(false);
    }
  }

  const canContinue = phone.replace(/\D/g, '').length >= 10;

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
        keyboardVerticalOffset={0}
      >
        <Animated.View style={[s.content, { opacity: fade }]}>
          {/* Top: wordmark */}
          <View style={s.top}>
            <Text style={s.wordmark}>PERSONAL GENIE</Text>
          </View>

          {/* Bottom form */}
          <View style={s.form}>
            <Text style={s.formLabel}>Enter your phone number</Text>
            <TextInput
              style={s.input}
              placeholder="+1 415 555 1234"
              placeholderTextColor="#4A4438"
              keyboardType="phone-pad"
              value={phone}
              onChangeText={setPhone}
              autoFocus
              returnKeyType="done"
              onSubmitEditing={handleContinue}
            />
            <TouchableOpacity
              style={[s.btn, !canContinue && s.btnDisabled]}
              onPress={handleContinue}
              disabled={loading || !canContinue}
              activeOpacity={0.85}
            >
              {loading
                ? <ActivityIndicator color="#0A0A0F" size="small" />
                : <Text style={s.btnText}>Send code via WhatsApp</Text>
              }
            </TouchableOpacity>
            <Text style={s.hint}>
              No account?{' '}
              <Text style={s.hintLink}>personalgenie.ai</Text>
            </Text>
            {/* DEV ONLY — remove before release */}
            <TouchableOpacity onPress={() => (navigation as any).navigate('OnboardName', { skipAuth: true })}>
              <Text style={s.devSkip}>[DEV] Skip →</Text>
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
  form: { gap: 12 },
  formLabel: {
    fontFamily: 'Georgia',
    fontStyle: 'italic',
    fontSize: 22,
    color: '#F5F0E8',
    marginBottom: 4,
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
  btnDisabled: { opacity: 0.35 },
  btnText: { color: '#0A0A0F', fontWeight: '700', fontSize: 16 },
  hint: {
    fontFamily: 'System',
    fontSize: 13,
    color: '#4A4438',
    textAlign: 'center',
    marginTop: 4,
  },
  hintLink: { color: '#C9A84C' },
  devSkip: {
    color: '#C9A84C',
    fontSize: 13,
    textAlign: 'center',
    marginTop: 8,
  },
});
