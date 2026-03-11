/**
 * IntroScreen — Full-screen lamp background. Wordmark top, content bottom.
 * No gold border frame.
 */
import React, { useEffect, useRef } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity,
  Animated, ImageBackground, Dimensions, Platform,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';

const { width, height } = Dimensions.get('window');
const BG = require('../../../assets/bg_splash.png');

export default function IntroScreen({ navigation }: any) {
  const fade = useRef(new Animated.Value(0)).current;
  const rise = useRef(new Animated.Value(30)).current;

  useEffect(() => {
    Animated.sequence([
      Animated.delay(300),
      Animated.parallel([
        Animated.timing(fade, { toValue: 1, duration: 900, useNativeDriver: true }),
        Animated.timing(rise, { toValue: 0, duration: 900, useNativeDriver: true }),
      ]),
    ]).start();
  }, [fade, rise]);

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
      <Animated.View style={[s.content, { opacity: fade, transform: [{ translateY: rise }] }]}>
        {/* Top: wordmark */}
        <View style={s.top}>
          <Text style={s.wordmark}>PERSONAL GENIE</Text>
        </View>

        {/* Bottom: headline + sub + CTA */}
        <View style={s.bottom}>
          <Text style={s.headline}>Your Genie is here.</Text>
          <Text style={s.sub}>
            A personal intelligence that knows who matters — and helps you show up for them.
          </Text>
          <TouchableOpacity
            style={s.btn}
            onPress={() => navigation.navigate('Welcome')}
            activeOpacity={0.85}
          >
            <Text style={s.btnText}>Begin</Text>
          </TouchableOpacity>
          <Text style={s.legal}>By continuing you agree to our terms of service</Text>
        </View>
      </Animated.View>
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
  bottom: { gap: 0 },
  headline: {
    fontFamily: 'Georgia',
    fontStyle: 'italic',
    fontSize: 32,
    color: '#F5F0E8',
    textAlign: 'center',
    lineHeight: 42,
    marginBottom: 16,
  },
  sub: {
    fontFamily: 'System',
    fontWeight: '400',
    fontSize: 15,
    color: '#8A8070',
    textAlign: 'center',
    lineHeight: 26,
    marginBottom: 40,
  },
  btn: {
    backgroundColor: '#C9A84C',
    borderRadius: 14,
    paddingVertical: 16,
    alignItems: 'center',
    marginBottom: 12,
  },
  btnText: {
    color: '#0A0A0F',
    fontWeight: '700',
    fontSize: 16,
  },
  legal: {
    fontFamily: 'System',
    fontWeight: '400',
    fontSize: 12,
    color: '#4A4438',
    textAlign: 'center',
  },
});
