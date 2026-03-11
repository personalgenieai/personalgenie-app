/**
 * BillingScreen — choose or manage your Personal Genie plan.
 */
import React, { useEffect, useState } from 'react';
import {
  View,
  Text,
  ScrollView,
  StyleSheet,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
  Linking,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { getSubscription, createCheckoutSession } from '../api';
import { COLORS, FONTS, CARD } from '../theme';
import type { Subscription } from '../types';

interface PlanDef {
  id: string;
  name: string;
  price: string;
  tagline: string;
  features: string[];
  recommended?: boolean;
}

const PLANS: PlanDef[] = [
  {
    id: 'free',
    name: 'Free',
    price: '$0',
    tagline: 'Get started',
    features: [
      '3 relationships',
      'Basic moments',
      'WhatsApp only',
    ],
  },
  {
    id: 'individual',
    name: 'Individual',
    price: '$9.99',
    tagline: 'per month',
    features: [
      'Unlimited relationships',
      'Full health tracking',
      'iOS app',
      'Rules engine',
    ],
    recommended: true,
  },
  {
    id: 'family',
    name: 'Family',
    price: '$14.99',
    tagline: 'per month',
    features: [
      'Everything in Individual',
      'Up to 4 family members',
      'Shared moments',
    ],
  },
  {
    id: 'pro',
    name: 'Pro',
    price: '$24.99',
    tagline: 'per month',
    features: [
      'Everything in Family',
      'Early access features',
      'Genie AI beta features',
    ],
  },
];

export default function BillingScreen({ navigation }: any) {
  const [subscription, setSubscription] = useState<Subscription | null>(null);
  const [loading, setLoading] = useState(true);
  const [selecting, setSelecting] = useState<string | null>(null);
  const [userId, setUserId] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      const uid = await AsyncStorage.getItem('pg_user_id');
      setUserId(uid);
      if (uid) {
        try {
          const sub = await getSubscription(uid);
          setSubscription(sub);
        } catch (_) {
          // Default to free if call fails
          setSubscription({ plan: 'free', status: 'active', current_period_end: null, cancel_at_period_end: false });
        }
      }
      setLoading(false);
    }
    load();
  }, []);

  async function handleSelect(planId: string) {
    if (!userId) return;
    if (planId === subscription?.plan) return; // already on this plan

    if (planId === 'free') {
      Alert.alert('Downgrade to Free', 'To cancel your subscription, use the billing portal or contact support.');
      return;
    }

    setSelecting(planId);
    try {
      const { checkout_url } = await createCheckoutSession(userId, planId);
      await Linking.openURL(checkout_url);
    } catch (e: any) {
      Alert.alert('Could not start checkout', e?.message ?? 'Please try again.');
    } finally {
      setSelecting(null);
    }
  }

  if (loading) {
    return (
      <View style={s.loader}>
        <ActivityIndicator color={COLORS.accent} size="large" />
      </View>
    );
  }

  const currentPlan = subscription?.plan ?? 'free';

  return (
    <ScrollView style={s.root} contentContainerStyle={s.content}>
      {/* Header */}
      <TouchableOpacity style={s.backBtn} onPress={() => navigation.goBack()}>
        <Text style={s.backText}>‹ Back</Text>
      </TouchableOpacity>

      <Text style={s.heading}>Choose your plan</Text>
      <Text style={s.subtitle}>Genie grows with you.</Text>

      {/* Plan cards */}
      {PLANS.map((plan) => {
        const isCurrent = plan.id === currentPlan;
        const isSelecting = selecting === plan.id;

        return (
          <View
            key={plan.id}
            style={[
              s.planCard,
              isCurrent && s.planCardActive,
              plan.recommended && !isCurrent && s.planCardRecommended,
            ]}
          >
            {/* Recommended badge */}
            {plan.recommended && (
              <View style={s.recommendedBadge}>
                <Text style={s.recommendedText}>RECOMMENDED</Text>
              </View>
            )}

            {/* Plan header */}
            <View style={s.planHeader}>
              <View>
                <Text style={s.planName}>{plan.name}</Text>
                <Text style={[FONTS.label, { marginTop: 2 }]}>{plan.tagline}</Text>
              </View>
              <Text style={[s.planPrice, isCurrent && { color: COLORS.accent }]}>
                {plan.price}
              </Text>
            </View>

            {/* Features */}
            <View style={s.featureList}>
              {plan.features.map((f, i) => (
                <View key={i} style={s.featureRow}>
                  <Text style={s.featureDot}>·</Text>
                  <Text style={[FONTS.label, s.featureText]}>{f}</Text>
                </View>
              ))}
            </View>

            {/* CTA */}
            {isCurrent ? (
              <View style={s.currentRow}>
                <Text style={s.checkmark}>✓</Text>
                <Text style={s.currentText}>Current plan</Text>
              </View>
            ) : (
              <TouchableOpacity
                style={[s.selectBtn, isSelecting && s.selectBtnDisabled]}
                onPress={() => handleSelect(plan.id)}
                disabled={!!selecting}
                activeOpacity={0.8}
              >
                {isSelecting ? (
                  <ActivityIndicator color={COLORS.bg} size="small" />
                ) : (
                  <Text style={s.selectBtnText}>Select</Text>
                )}
              </TouchableOpacity>
            )}
          </View>
        );
      })}

      {/* Footer note */}
      <Text style={s.trialNote}>All plans include a 7-day free trial.</Text>
    </ScrollView>
  );
}

// ── Styles ─────────────────────────────────────────────────────────────────────

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: COLORS.bg },
  content: { padding: 20, paddingTop: 56, paddingBottom: 48 },
  loader: { flex: 1, backgroundColor: COLORS.bg, justifyContent: 'center', alignItems: 'center' },

  backBtn: { marginBottom: 20 },
  backText: { color: COLORS.accent, fontSize: 16 },

  heading: { ...FONTS.heading, marginBottom: 6 },
  subtitle: { ...FONTS.body, color: COLORS.muted, marginBottom: 28 },

  // Plan card
  planCard: {
    ...CARD,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  planCardActive: {
    borderColor: COLORS.accent,
    backgroundColor: COLORS.surface,
  },
  planCardRecommended: {
    borderColor: COLORS.accent + '66',
  },

  // Recommended badge
  recommendedBadge: {
    alignSelf: 'flex-start',
    backgroundColor: COLORS.accent,
    borderRadius: 6,
    paddingHorizontal: 8,
    paddingVertical: 3,
    marginBottom: 10,
  },
  recommendedText: { color: COLORS.bg, fontSize: 10, fontWeight: '700', letterSpacing: 0.8 },

  // Plan header
  planHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    marginBottom: 12,
  },
  planName: { ...FONTS.sub },
  planPrice: { fontSize: 22, fontWeight: '700', color: COLORS.text },

  // Features
  featureList: { marginBottom: 16 },
  featureRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 8, marginBottom: 4 },
  featureDot: { color: COLORS.accent, fontSize: 16, lineHeight: 18 },
  featureText: { flex: 1, lineHeight: 18 },

  // Current plan indicator
  currentRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  checkmark: { color: COLORS.accent, fontSize: 16, fontWeight: '700' },
  currentText: { color: COLORS.accent, fontSize: 14, fontWeight: '600' },

  // Select button
  selectBtn: {
    backgroundColor: COLORS.accent,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: 'center',
  },
  selectBtnDisabled: { opacity: 0.6 },
  selectBtnText: { color: COLORS.bg, fontWeight: '700', fontSize: 15 },

  // Footer
  trialNote: {
    ...FONTS.label,
    textAlign: 'center',
    marginTop: 16,
    lineHeight: 18,
  },
});
