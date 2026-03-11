/**
 * OnboardReadyScreen — "Your Genie is ready."
 * bg_ready.png background. handleEnter logic preserved.
 */
import React, { useEffect, useRef } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, Animated,
  ImageBackground, Dimensions, Platform,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import AsyncStorage from '@react-native-async-storage/async-storage';

const { width, height } = Dimensions.get('window');
const BG = require('../../../assets/bg_ready.png');

export default function OnboardReadyScreen({ route }: any) {
  const fade = useRef(new Animated.Value(0)).current;
  const rise = useRef(new Animated.Value(24)).current;

  useEffect(() => {
    Animated.sequence([
      Animated.delay(400),
      Animated.parallel([
        Animated.timing(fade, { toValue: 1, duration: 900, useNativeDriver: true }),
        Animated.timing(rise, { toValue: 0, duration: 900, useNativeDriver: true }),
      ]),
    ]).start();
  }, [fade, rise]);

  async function handleEnter() {
    await AsyncStorage.setItem('pg_onboarding_complete', 'true');
    // App.tsx token polling detects auth and switches to MainNavigator
  }

  return (
    <ImageBackground source={BG} style={{ flex: 1, width, height, backgroundColor: '#0A0A0F' }} resizeMode="cover">
      <LinearGradient
        colors={['rgba(5,4,10,0.82)', 'rgba(5,4,10,0.3)', 'transparent']}
        style={{ position: 'absolute', top: 0, left: 0, right: 0, height: height * 0.35, zIndex: 1 }}
        pointerEvents="none"
      />
      <LinearGradient
        colors={['transparent', 'rgba(5,4,10,0.85)', 'rgba(5,4,10,0.98)']}
        style={{ position: 'absolute', bottom: 0, left: 0, right: 0, height: height * 0.40, zIndex: 1 }}
        pointerEvents="none"
      />

      <View style={s.content}>
        {/* Top: wordmark */}
        <View style={s.top}>
          <Text style={s.wordmark}>PERSONAL GENIE</Text>
        </View>

        {/* Center: headline + body */}
        <Animated.View
          style={[s.center, { opacity: fade, transform: [{ translateY: rise }] }]}
        >
          <Text style={s.headline}>Your Genie is ready.</Text>
          <Text style={s.body}>
            I'm paying attention.{'\n'}
            When I have something worth saying, I'll say it.
          </Text>
        </Animated.View>

        {/* Bottom: Enter button */}
        <TouchableOpacity style={s.btn} onPress={handleEnter} activeOpacity={0.85}>
          <Text style={s.btnText}>Enter</Text>
        </TouchableOpacity>
      </View>
    </ImageBackground>
  );
}

const s = StyleSheet.create({
  content: {
    flex: 1,
    zIndex: 3,
    justifyContent: 'space-between',
    paddingTop: Platform.OS === 'ios' ? 64 : 48,
    paddingBottom: Platform.OS === 'ios' ? 52 : 36,
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
  center: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  headline: {
    fontFamily: 'Georgia',
    fontStyle: 'italic',
    fontSize: 32,
    color: '#F5F0E8',
    textAlign: 'center',
    lineHeight: 42,
    marginBottom: 16,
  },
  body: {
    fontFamily: 'System',
    fontWeight: '400',
    fontSize: 15,
    color: '#8A8070',
    textAlign: 'center',
    lineHeight: 27,
  },
  btn: {
    backgroundColor: '#C9A84C',
    borderRadius: 14,
    paddingVertical: 16,
    alignItems: 'center',
  },
  btnText: { color: '#0A0A0F', fontWeight: '700', fontSize: 16 },
});
