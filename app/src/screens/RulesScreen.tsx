/**
 * RulesScreen — Genie Rule Engine.
 *
 * Natural language → trigger/action pairs.
 * FAB to create. Long-press / ✕ to delete.
 */
import React, { useEffect, useState, useCallback } from 'react';
import {
  View, Text, ScrollView, StyleSheet, TouchableOpacity,
  Modal, TextInput, ActivityIndicator, Alert, RefreshControl,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { getRules, createRule, deleteRule } from '../api';
import type { GenieRule } from '../types';
import { COLORS, FONTS, SPACING, RADIUS, SHADOW } from '../theme';

export default function RulesScreen() {
  const [userId, setUserId]   = useState<string | null>(null);
  const [rules, setRules]     = useState<GenieRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [showCreate, setShowCreate] = useState(false);

  useEffect(() => {
    AsyncStorage.getItem('pg_user_id').then((id) => { if (id) setUserId(id); });
  }, []);

  const load = useCallback(async (uid: string) => {
    try { const r = await getRules(uid); setRules(r); } catch (_) {}
  }, []);

  useEffect(() => {
    if (!userId) return;
    setLoading(true);
    load(userId).finally(() => setLoading(false));
  }, [userId, load]);

  const onRefresh = useCallback(async () => {
    if (!userId) return;
    setRefreshing(true);
    await load(userId);
    setRefreshing(false);
  }, [userId, load]);

  async function handleDelete(ruleId: string, description: string) {
    Alert.alert('Remove rule', `"${description}"`, [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Remove',
        style: 'destructive',
        onPress: async () => {
          if (!userId) return;
          try {
            await deleteRule(userId, ruleId);
            setRules((prev) => prev.filter((r) => r.id !== ruleId));
          } catch (_) {}
        },
      },
    ]);
  }

  if (loading) {
    return (
      <View style={s.center}>
        <ActivityIndicator color={COLORS.accent} size="large" />
      </View>
    );
  }

  return (
    <>
      <ScrollView
        style={s.root}
        contentContainerStyle={s.content}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={COLORS.accent} />
        }
      >
        <Text style={s.heading}>Rules</Text>
        <Text style={s.subtitle}>
          Tell Genie what to watch for. Plain English.
        </Text>

        {rules.length === 0 ? (
          <EmptyRules onAdd={() => setShowCreate(true)} />
        ) : (
          rules.map((rule) => (
            <RuleCard
              key={rule.id}
              rule={rule}
              onDelete={() => handleDelete(rule.id, rule.plain_english)}
            />
          ))
        )}

        <View style={{ height: 100 }} />
      </ScrollView>

      {/* FAB */}
      {rules.length > 0 && (
        <TouchableOpacity style={[s.fab, SHADOW.gold]} onPress={() => setShowCreate(true)}>
          <Text style={s.fabText}>+</Text>
        </TouchableOpacity>
      )}

      {userId && (
        <CreateRuleModal
          visible={showCreate}
          userId={userId}
          onClose={() => setShowCreate(false)}
          onCreated={(rule) => {
            setRules((prev) => [rule, ...prev]);
            setShowCreate(false);
          }}
        />
      )}
    </>
  );
}

function RuleCard({ rule, onDelete }: { rule: GenieRule; onDelete: () => void }) {
  const trigger = rule.trigger_type?.replace(/_/g, ' ') ?? 'trigger';
  const action  = rule.action_type?.replace(/_/g, ' ') ?? 'action';

  return (
    <View style={s.ruleCard}>
      {/* Header row */}
      <View style={s.ruleHeader}>
        <View style={s.chips}>
          <View style={s.chip}>
            <Text style={s.chipText}>{trigger}</Text>
          </View>
          <Text style={s.arrow}>→</Text>
          <View style={[s.chip, s.actionChip]}>
            <Text style={[s.chipText, s.actionChipText]}>{action}</Text>
          </View>
        </View>
        <TouchableOpacity
          onPress={onDelete}
          hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}
        >
          <View style={s.deleteCircle}>
            <Text style={s.deleteText}>✕</Text>
          </View>
        </TouchableOpacity>
      </View>

      {/* Description */}
      <Text style={s.ruleText}>{rule.plain_english}</Text>

      {/* Paused badge */}
      {!rule.is_active && (
        <View style={s.pausedBadge}>
          <Text style={s.pausedText}>Paused</Text>
        </View>
      )}
    </View>
  );
}

function EmptyRules({ onAdd }: { onAdd: () => void }) {
  return (
    <View style={s.emptyWrap}>
      <Text style={s.emptyGlyph}>⚡</Text>
      <Text style={s.emptyHeadline}>No rules yet.</Text>
      <Text style={s.emptyBody}>
        Tell Genie what to notice and how to respond.{'\n'}No forms. No code.
      </Text>
      <TouchableOpacity style={s.emptyBtn} onPress={onAdd}>
        <Text style={s.emptyBtnText}>Create your first rule</Text>
      </TouchableOpacity>
    </View>
  );
}

function CreateRuleModal({
  visible, userId, onClose, onCreated,
}: {
  visible: boolean;
  userId: string;
  onClose: () => void;
  onCreated: (rule: GenieRule) => void;
}) {
  const [text, setText]       = useState('');
  const [loading, setLoading] = useState(false);
  const [preview, setPreview] = useState<GenieRule | null>(null);

  async function handleParse() {
    if (!text.trim() || loading) return;
    setLoading(true);
    try {
      const result = await createRule(userId, text.trim());
      setPreview(result);
    } catch (e: any) {
      Alert.alert('Could not parse rule', e.message ?? 'Try rephrasing it.');
    } finally {
      setLoading(false);
    }
  }

  function handleConfirm() {
    if (preview) onCreated(preview);
    setText('');
    setPreview(null);
  }

  function handleClose() {
    setText('');
    setPreview(null);
    onClose();
  }

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={handleClose}
    >
      <View style={m.root}>
        <View style={m.handle} />
        <View style={m.topBar}>
          <Text style={m.title}>New rule</Text>
          <TouchableOpacity onPress={handleClose}>
            <Text style={m.cancel}>Cancel</Text>
          </TouchableOpacity>
        </View>

        <Text style={m.hint}>
          Describe what you want Genie to do. In your own words.
        </Text>

        {!preview ? (
          <>
            <TextInput
              style={m.input}
              placeholder={`e.g. "If I haven't talked to Mom in a week, remind me on Sunday evening"`}
              placeholderTextColor={COLORS.textTertiary}
              value={text}
              onChangeText={setText}
              multiline
              autoFocus
              editable={!loading}
            />
            <TouchableOpacity
              style={[m.btn, (!text.trim() || loading) && m.btnDisabled]}
              onPress={handleParse}
              disabled={!text.trim() || loading}
            >
              {loading
                ? <ActivityIndicator color={COLORS.bg} size="small" />
                : <Text style={m.btnText}>Parse rule</Text>}
            </TouchableOpacity>
          </>
        ) : (
          <View style={m.previewCard}>
            <Text style={m.previewLabel}>Genie understood this as:</Text>
            <Text style={m.previewText}>{preview.plain_english}</Text>
            <View style={m.previewChips}>
              <View style={s.chip}>
                <Text style={s.chipText}>{preview.trigger_type?.replace(/_/g, ' ')}</Text>
              </View>
              <Text style={s.arrow}>→</Text>
              <View style={[s.chip, s.actionChip]}>
                <Text style={[s.chipText, s.actionChipText]}>{preview.action_type?.replace(/_/g, ' ')}</Text>
              </View>
            </View>
            <TouchableOpacity style={m.btn} onPress={handleConfirm}>
              <Text style={m.btnText}>Activate rule</Text>
            </TouchableOpacity>
            <TouchableOpacity style={m.rewriteBtn} onPress={() => setPreview(null)}>
              <Text style={m.rewriteText}>Rewrite</Text>
            </TouchableOpacity>
          </View>
        )}
      </View>
    </Modal>
  );
}

const s = StyleSheet.create({
  root:    { flex: 1, backgroundColor: COLORS.bg },
  content: { padding: SPACING.xl, paddingTop: 64 },
  center:  { flex: 1, backgroundColor: COLORS.bg, justifyContent: 'center', alignItems: 'center' },

  heading:  { ...FONTS.display, fontSize: 26, marginBottom: SPACING.xs },
  subtitle: { ...FONTS.body, color: COLORS.textSecondary, marginBottom: SPACING.xl, lineHeight: 22 },

  // Rule card
  ruleCard: {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    padding: SPACING.lg,
    marginBottom: SPACING.sm,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  ruleHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: SPACING.sm,
  },
  chips:  { flexDirection: 'row', alignItems: 'center', gap: SPACING.xs, flexWrap: 'wrap', flex: 1 },
  chip:   {
    backgroundColor: COLORS.accentDim,
    borderRadius: RADIUS.sm,
    paddingHorizontal: SPACING.sm,
    paddingVertical: 4,
    borderWidth: 1,
    borderColor: COLORS.accentBorder,
  },
  actionChip:     { backgroundColor: COLORS.surfaceElevated, borderColor: COLORS.border },
  chipText:       { ...FONTS.caption, color: COLORS.accent, textTransform: 'uppercase', letterSpacing: 0.5 },
  actionChipText: { color: COLORS.textSecondary },
  arrow:          { ...FONTS.label, color: COLORS.textTertiary },
  deleteCircle:   {
    width: 24, height: 24, borderRadius: 12,
    backgroundColor: COLORS.surfaceElevated,
    borderWidth: 1, borderColor: COLORS.border,
    justifyContent: 'center', alignItems: 'center',
  },
  deleteText: { color: COLORS.textSecondary, fontSize: 11 },
  ruleText:   { ...FONTS.body, lineHeight: 22 },
  pausedBadge:{
    marginTop: SPACING.sm, alignSelf: 'flex-start',
    backgroundColor: COLORS.surfaceElevated,
    borderRadius: RADIUS.pill,
    paddingHorizontal: SPACING.sm, paddingVertical: 3,
  },
  pausedText: { ...FONTS.caption, color: COLORS.textTertiary },

  // Empty
  emptyWrap:     { alignItems: 'center', paddingVertical: SPACING.hero, paddingHorizontal: SPACING.xl },
  emptyGlyph:    { fontSize: 40, marginBottom: SPACING.lg },
  emptyHeadline: { ...FONTS.sub, textAlign: 'center', marginBottom: SPACING.sm },
  emptyBody:     { ...FONTS.body, color: COLORS.textSecondary, textAlign: 'center', lineHeight: 24, marginBottom: SPACING.xl },
  emptyBtn:      {
    borderWidth: 1, borderColor: COLORS.accentBorder,
    borderRadius: RADIUS.md, paddingHorizontal: SPACING.xl, paddingVertical: SPACING.md,
  },
  emptyBtnText: { color: COLORS.accent, fontWeight: '600', fontSize: 15 },

  // FAB
  fab: {
    position: 'absolute', bottom: 36, right: SPACING.xl,
    width: 52, height: 52, borderRadius: 26,
    backgroundColor: COLORS.accent,
    justifyContent: 'center', alignItems: 'center',
  },
  fabText: { color: COLORS.bg, fontSize: 26, fontWeight: '300', lineHeight: 30 },
});

const m = StyleSheet.create({
  root:    { flex: 1, backgroundColor: COLORS.bg, paddingTop: 12, paddingHorizontal: SPACING.xl },
  handle:  { width: 36, height: 4, backgroundColor: COLORS.border, borderRadius: 2, alignSelf: 'center', marginBottom: 12 },
  topBar:  { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: SPACING.lg },
  title:   { ...FONTS.heading },
  cancel:  { color: COLORS.textSecondary, fontSize: 16 },
  hint:    { ...FONTS.body, color: COLORS.textSecondary, marginBottom: SPACING.lg, lineHeight: 22 },
  input:   {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.md,
    padding: SPACING.lg,
    fontSize: 15,
    color: COLORS.text,
    minHeight: 110,
    borderWidth: 1,
    borderColor: COLORS.border,
    textAlignVertical: 'top',
    lineHeight: 22,
    marginBottom: SPACING.lg,
  },
  btn:         {
    backgroundColor: COLORS.accent,
    borderRadius: RADIUS.md,
    padding: SPACING.lg,
    alignItems: 'center',
    marginBottom: SPACING.sm,
  },
  btnDisabled: { opacity: 0.35 },
  btnText:     { color: COLORS.bg, fontWeight: '700', fontSize: 15 },
  previewCard: {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    padding: SPACING.xl,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  previewLabel:  { ...FONTS.caption, textTransform: 'uppercase', letterSpacing: 1, marginBottom: SPACING.sm },
  previewText:   { ...FONTS.sub, marginBottom: SPACING.lg, lineHeight: 25 },
  previewChips:  { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, marginBottom: SPACING.xl },
  rewriteBtn:    { alignItems: 'center', paddingVertical: SPACING.md },
  rewriteText:   { color: COLORS.textSecondary, fontSize: 14 },
});
