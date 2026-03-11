/**
 * App.tsx — simplified root.
 * - If pg_insights stored → InsightsScreen
 * - Else → SplashScreen → SetupChat → Insights
 * No auth required for this MVP flow.
 */
import React, { useEffect, useState } from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { StatusBar } from 'expo-status-bar';
import { View, ActivityIndicator } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import SplashScreen from './screens/SplashScreen';
import SetupChatScreen from './screens/SetupChatScreen';
import InsightsScreen from './screens/InsightsScreen';

const Stack = createNativeStackNavigator();

export default function App() {
  const [ready, setReady]           = useState(false);
  const [hasInsights, setHasInsights] = useState(false);

  useEffect(() => {
    AsyncStorage.getItem('pg_insights').then(val => {
      setHasInsights(!!val);
      setReady(true);
    });
  }, []);

  if (!ready) {
    return (
      <View style={{ flex: 1, backgroundColor: '#0A0A0F', justifyContent: 'center', alignItems: 'center' }}>
        <ActivityIndicator color="#C9A84C" size="large" />
        <StatusBar style="light" />
      </View>
    );
  }

  return (
    <NavigationContainer>
      <StatusBar style="light" />
      <Stack.Navigator
        initialRouteName={hasInsights ? 'Insights' : 'Splash'}
        screenOptions={{ headerShown: false, animation: 'fade' }}
      >
        <Stack.Screen name="Splash"     component={SplashScreen} />
        <Stack.Screen name="SetupChat"  component={SetupChatScreen} />
        <Stack.Screen name="Insights"   component={InsightsScreen} />
      </Stack.Navigator>
    </NavigationContainer>
  );
}
