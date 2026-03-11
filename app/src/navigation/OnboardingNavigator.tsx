import React from 'react';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import WelcomeScreen from '../screens/onboarding/WelcomeScreen';
import OTPScreen from '../screens/onboarding/OTPScreen';
import IntroScreen from '../screens/onboarding/IntroScreen';
import OnboardNameScreen from '../screens/onboarding/OnboardNameScreen';
import OnboardRelationship from '../screens/onboarding/OnboardRelationship';
import OnboardFirstRelationshipScreen from '../screens/onboarding/OnboardFirstRelationshipScreen';
import OnboardConnectSourcesScreen from '../screens/onboarding/OnboardConnectSourcesScreen';
import OnboardIngestionScreen from '../screens/onboarding/OnboardIngestionScreen';
import OnboardWhatsAppScreen from '../screens/onboarding/OnboardWhatsAppScreen';
import OnboardReadyScreen from '../screens/onboarding/OnboardReadyScreen';

export type OnboardingStackParams = {
  Welcome: undefined;
  OTP: { phone: string };
  Intro: undefined;
  OnboardName: undefined;
  OnboardRelationship: { name: string; firstPerson?: string };
  OnboardFirstRelationship: { name: string };
  OnboardConnectSources: { name: string; firstPerson: string };
  OnboardIngestion: { name: string; firstPerson: string; connected: Record<string, boolean> };
  OnboardWhatsApp: { name: string; firstPerson: string; notifPref: string };
  OnboardReady: { name: string };
};

const Stack = createNativeStackNavigator<OnboardingStackParams>();

export default function OnboardingNavigator() {
  return (
    <Stack.Navigator screenOptions={{ headerShown: false, animation: 'fade' }}>
      <Stack.Screen name="Welcome" component={WelcomeScreen} />
      <Stack.Screen name="OTP" component={OTPScreen} />
      <Stack.Screen name="Intro" component={IntroScreen} />
      <Stack.Screen name="OnboardName" component={OnboardNameScreen} />
      <Stack.Screen name="OnboardRelationship" component={OnboardRelationship} />
      <Stack.Screen name="OnboardFirstRelationship" component={OnboardFirstRelationshipScreen} />
      <Stack.Screen name="OnboardConnectSources" component={OnboardConnectSourcesScreen} />
      <Stack.Screen name="OnboardIngestion" component={OnboardIngestionScreen} />
      <Stack.Screen name="OnboardWhatsApp" component={OnboardWhatsAppScreen} />
      <Stack.Screen name="OnboardReady" component={OnboardReadyScreen} />
    </Stack.Navigator>
  );
}
