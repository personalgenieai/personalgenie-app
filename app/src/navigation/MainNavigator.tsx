import React from 'react';
import { View, StyleSheet } from 'react-native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import ChatScreen from '../screens/ChatScreen';
import WorldScreen from '../screens/WorldScreen';
import YouScreen from '../screens/YouScreen';

export type MainTabParams = {
  Chat:  undefined;
  World: undefined;
  You:   undefined;
};

const Tab = createBottomTabNavigator<MainTabParams>();

function TabIcon({ focused, shape }: { focused: boolean; shape: 'chat' | 'world' | 'you' }) {
  const color = focused ? '#C9A84C' : '#4A4438';
  if (shape === 'chat') {
    return (
      <View style={{ width: 22, height: 22, alignItems: 'center', justifyContent: 'center' }}>
        <View style={{ width: 14, height: 8, borderRadius: 4, borderWidth: 1.5, borderColor: color }} />
        <View style={{ width: 2, height: 4, backgroundColor: color }} />
        <View style={{ width: 10, height: 2, backgroundColor: color, borderRadius: 1 }} />
      </View>
    );
  }
  if (shape === 'world') {
    return (
      <View style={{ width: 22, height: 22, alignItems: 'center', justifyContent: 'center' }}>
        <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: color, marginBottom: 3 }} />
        <View style={{ width: 18, height: 1.5, backgroundColor: color, borderRadius: 1 }} />
      </View>
    );
  }
  // you: circle outline
  return (
    <View style={{ width: 22, height: 22, alignItems: 'center', justifyContent: 'center' }}>
      <View style={{ width: 16, height: 16, borderRadius: 8, borderWidth: 1.5, borderColor: color }} />
    </View>
  );
}

export default function MainNavigator() {
  return (
    <Tab.Navigator
      screenOptions={{
        headerShown: false,
        tabBarStyle: {
          backgroundColor: 'rgba(10,10,15,0.96)',
          borderTopWidth: 1,
          borderTopColor: '#1E1E2E',
          height: 72,
          paddingBottom: 16,
          paddingTop: 8,
        },
        tabBarActiveTintColor:   '#C9A84C',
        tabBarInactiveTintColor: '#4A4438',
        tabBarLabelStyle: {
          fontSize: 10,
          fontWeight: '600',
          letterSpacing: 0.5,
        },
      }}
    >
      <Tab.Screen
        name="Chat"
        component={ChatScreen}
        options={{
          tabBarLabel: 'Chat',
          tabBarIcon: ({ focused }) => <TabIcon focused={focused} shape="chat" />,
        }}
      />
      <Tab.Screen
        name="World"
        component={WorldScreen}
        options={{
          tabBarLabel: 'World',
          tabBarIcon: ({ focused }) => <TabIcon focused={focused} shape="world" />,
        }}
      />
      <Tab.Screen
        name="You"
        component={YouScreen}
        options={{
          tabBarLabel: 'You',
          tabBarIcon: ({ focused }) => <TabIcon focused={focused} shape="you" />,
        }}
      />
    </Tab.Navigator>
  );
}
