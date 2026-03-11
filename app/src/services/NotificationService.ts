/**
 * services/NotificationService.ts — Push notification registration.
 *
 * Called once on app start (after auth is confirmed).
 * Requests iOS permission, gets the APNs token, and registers it with the backend.
 * Handles foreground notifications via a simple in-app banner system.
 */
import { Platform, Alert } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { registerPushToken } from '../api';

const STORAGE_PUSH_REGISTERED = 'pg_push_registered_token';

/**
 * Request push notification permission and register the device token.
 * Safe to call multiple times — skips if the same token is already registered.
 */
export async function registerForPushNotifications(): Promise<void> {
  if (Platform.OS !== 'ios') return;

  try {
    // Dynamically import to avoid requiring native modules in non-native envs
    const { default: PushNotificationIOS } = await import(
      '@react-native-community/push-notification-ios'
    );

    // Request permission
    const permissions = await PushNotificationIOS.requestPermissions({
      alert: true,
      badge: true,
      sound: true,
    });

    if (!permissions.alert) {
      // User denied — silently skip, don't nag
      return;
    }

    // Get device token
    PushNotificationIOS.addEventListener('register', async (token: string) => {
      try {
        const alreadyRegistered = await AsyncStorage.getItem(STORAGE_PUSH_REGISTERED);
        if (alreadyRegistered === token) return; // Nothing changed

        const userId = await AsyncStorage.getItem('pg_user_id');
        if (!userId) return;

        await registerPushToken(userId, token);
        await AsyncStorage.setItem(STORAGE_PUSH_REGISTERED, token);
      } catch (err) {
        // Registration failure is non-fatal — app works without push
        console.warn('[Push] Token registration failed:', err);
      }
    });

    PushNotificationIOS.addEventListener('registrationError', (err: any) => {
      console.warn('[Push] Registration error:', err);
    });

    // Trigger the registration flow
    PushNotificationIOS.requestPermissions();

  } catch (err) {
    // Module not available (e.g., running in Expo Go) — silently skip
    console.log('[Push] PushNotificationIOS not available:', err);
  }
}

/**
 * Clear the badge count when app becomes active.
 */
export async function clearBadge(): Promise<void> {
  if (Platform.OS !== 'ios') return;
  try {
    const { default: PushNotificationIOS } = await import(
      '@react-native-community/push-notification-ios'
    );
    PushNotificationIOS.setApplicationIconBadgeNumber(0);
  } catch (_) {}
}

/**
 * Handle a foreground notification (show in-app banner).
 * Called from the AppDelegate or notification listener.
 */
export function handleForegroundNotification(notification: {
  title: string;
  body: string;
  data?: Record<string, any>;
}): void {
  // Simple alert-based in-app notification for MVP
  // In Phase 2 replace with custom in-app toast component
  Alert.alert(
    notification.title ?? 'Genie',
    notification.body,
    [{ text: 'OK', style: 'default' }],
    { cancelable: true },
  );
}
