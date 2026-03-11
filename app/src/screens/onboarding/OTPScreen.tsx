/**
 * OTPScreen — Code verification.
 * bg_onboard.png background. All verifyOTP/saveSession logic preserved.
 */
import React, { useState } from 'react';
import {
  View, Text, TextInput, TouchableOpacity,
  StyleSheet, Alert, ActivityIndicator, KeyboardAvoidingView,
  Platform, ImageBackground, Dimensions,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { NativeStackScreenProps } from '@react-navigation/native-stack';
import { OnboardingStackParams } from '../../navigation/OnboardingNavigator';
import { verifyOTP, saveSession } from '../../api';

const { width, height } = Dimensions.get('window');
const BG = require('../../../assets/bg_onboard.png');

type Props = NativeStackScreenProps<OnboardingStackParams, 'OTP'>;

export default function OTPScreen({ route, navigation }: Props) {
  const { phone } = route.params;
  const [code, setCode] = useState('');
  const [loading, setLoading] = useState(false);

  async function handleVerify() {
    if (code.trim().length !== 6) {
      Alert.alert('Enter the 6-digit code sent to WhatsApp');
      return;
    }
    setLoading(true);
    try {
      const res = await verifyOTP(phone, code.trim());
      await saveSession(res.user_id, res.name, res.token);
      // New user → send through onboarding
      // Returning user (name already set) → App.tsx will route to MainNavigator
      if (!res.name) {
        navigation.navigate('Intro');
      }
      // If name exists, App.tsx polling detects token and switches to MainNavigator
    } catch (e: any) {
      Alert.alert('Incorrect code', e.message ?? 'Try again or request a new one.');
    } finally {
      setLoading(false);
    }
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
        <View style={s.content}>
          {/* Top: wordmark */}
          <View style={s.top}>
            <Text style={s.wordmark}>PERSONAL GENIE</Text>
          </View>

          {/* Bottom form */}
          <View style={s.form}>
            <Text style={s.formLabel}>Enter the code we sent you.</Text>
            <Text style={s.phoneSub}>{phone}</Text>
            <TextInput
              style={s.input}
              placeholder="000000"
              placeholderTextColor="#4A4438"
              keyboardType="number-pad"
              maxLength={6}
              value={code}
              onChangeText={setCode}
              autoFocus
              returnKeyType="done"
              onSubmitEditing={handleVerify}
            />
            <TouchableOpacity
              style={[s.btn, loading && { opacity: 0.6 }]}
              onPress={handleVerify}
              disabled={loading}
              activeOpacity={0.85}
            >
              {loading
                ? <ActivityIndicator color="#0A0A0F" size="small" />
                : <Text style={s.btnText}>Verify</Text>
              }
            </TouchableOpacity>
            <TouchableOpacity onPress={() => navigation.goBack()}>
              <Text style={s.resend}>Resend code</Text>
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
  form: { gap: 12 },
  formLabel: {
    fontFamily: 'Georgia',
    fontStyle: 'italic',
    fontSize: 22,
    color: '#F5F0E8',
    marginBottom: 4,
  },
  phoneSub: {
    fontSize: 14,
    color: '#8A8070',
    marginBottom: 12,
  },
  input: {
    backgroundColor: 'rgba(12,12,18,0.85)',
    borderWidth: 1,
    borderColor: '#2A2740',
    borderRadius: 12,
    paddingHorizontal: 18,
    paddingVertical: 16,
    fontSize: 28,
    color: '#F5F0E8',
    letterSpacing: 12,
    textAlign: 'center',
  },
  btn: {
    backgroundColor: '#C9A84C',
    borderRadius: 14,
    paddingVertical: 16,
    alignItems: 'center',
  },
  btnText: { color: '#0A0A0F', fontWeight: '700', fontSize: 16 },
  resend: {
    color: '#C9A84C',
    fontSize: 14,
    textAlign: 'center',
    marginTop: 4,
  },
});
