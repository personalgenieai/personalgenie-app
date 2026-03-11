/**
 * SplashScreen — "Welcome to Personal Genie"
 * Full screen bg_splash.png. Tap anywhere to enter.
 */
import React, { useEffect, useRef } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity,
  ImageBackground, Dimensions, Animated,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';

const { width, height } = Dimensions.get('window');
const BG = require('../../assets/bg_splash.png');

export default function SplashScreen({ navigation }: any) {
  const fade = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.timing(fade, { toValue: 1, duration: 1200, delay: 400, useNativeDriver: true }).start();
  }, []);

  return (
    <TouchableOpacity activeOpacity={1} style={{ flex: 1 }} onPress={() => navigation.navigate('SetupChat')}>
      <ImageBackground source={BG} style={s.bg} resizeMode="cover">
        <LinearGradient
          colors={['rgba(5,4,10,0.5)', 'rgba(5,4,10,0.1)', 'transparent']}
          style={s.gradTop}
          pointerEvents="none"
        />
        <LinearGradient
          colors={['transparent', 'rgba(5,4,10,0.7)', 'rgba(5,4,10,0.95)']}
          style={s.gradBottom}
          pointerEvents="none"
        />
        <Animated.View style={[s.content, { opacity: fade }]}>
          <Text style={s.wordmark}>PERSONAL GENIE</Text>
          <Text style={s.headline}>Welcome.</Text>
          <Text style={s.sub}>Tap anywhere to begin.</Text>
        </Animated.View>
      </ImageBackground>
    </TouchableOpacity>
  );
}

const s = StyleSheet.create({
  bg: { flex: 1, width, height, backgroundColor: '#0A0A0F' },
  gradTop: { position: 'absolute', top: 0, left: 0, right: 0, height: height * 0.35 },
  gradBottom: { position: 'absolute', bottom: 0, left: 0, right: 0, height: height * 0.50 },
  content: {
    flex: 1, justifyContent: 'flex-end',
    alignItems: 'center',
    paddingBottom: 80, paddingHorizontal: 32,
    gap: 10,
  },
  wordmark: {
    fontFamily: 'System', fontSize: 11, fontWeight: '600',
    color: '#C9A84C', letterSpacing: 3.5, textTransform: 'uppercase',
    marginBottom: 8,
  },
  headline: {
    fontFamily: 'Georgia', fontStyle: 'italic',
    fontSize: 38, color: '#F5F0E8', textAlign: 'center',
  },
  sub: { fontSize: 14, color: '#8A8070', textAlign: 'center' },
});
