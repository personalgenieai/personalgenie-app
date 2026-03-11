/**
 * RootNavigator — wraps MainTabNavigator with a stack so modal screens
 * (Billing, PersonDetail deep links, etc.) can slide over the tabs.
 */
import React from 'react';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import MainNavigator from './MainNavigator';
import BillingScreen from '../screens/BillingScreen';
import { COLORS } from '../theme';

export type RootStackParams = {
  Tabs:    undefined;
  Billing: undefined;
};

const Stack = createNativeStackNavigator<RootStackParams>();

export default function RootNavigator() {
  return (
    <Stack.Navigator
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: COLORS.bg },
      }}
    >
      <Stack.Screen name="Tabs"    component={MainNavigator} />
      <Stack.Screen
        name="Billing"
        component={BillingScreen}
        options={{ presentation: 'modal', animation: 'slide_from_bottom' }}
      />
    </Stack.Navigator>
  );
}
