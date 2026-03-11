/**
 * FamilyGenie — Notification Service
 *
 * Handles Expo push token registration and foreground notification display.
 * Works in Expo Go and dev builds.
 */
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

/**
 * Request permission and return the Expo push token.
 * Returns null if permission is denied or registration fails.
 */
export async function registerForPushNotifications(): Promise<string | null> {
  try {
    if (Platform.OS === 'android') {
      await Notifications.setNotificationChannelAsync('default', {
        name: 'FamilyGenie',
        importance: Notifications.AndroidImportance.MAX,
        sound: 'default',
      });
    }

    const { status: existing } = await Notifications.getPermissionsAsync();
    let finalStatus = existing;
    if (existing !== 'granted') {
      const { status } = await Notifications.requestPermissionsAsync();
      finalStatus = status;
    }
    if (finalStatus !== 'granted') return null;

    const tokenData = await Notifications.getExpoPushTokenAsync();
    return tokenData.data;
  } catch (err) {
    console.warn('Push registration error:', err);
    return null;
  }
}

/**
 * Configure how notifications are handled while the app is foregrounded.
 * Call once at app startup, before any notifications arrive.
 */
export function setupNotificationHandler(): void {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowAlert: true,
      shouldPlaySound: true,
      shouldSetBadge: false,
    }),
  });
}
