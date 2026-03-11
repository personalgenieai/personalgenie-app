/**
 * SetupChatScreen — Guided chat flow.
 *
 * If Mac is connected:
 *   → batch-count all contacts → auto-pick top 3 → analyze all 3 → InsightsScreen
 *   No manual selection needed.
 *
 * If no Mac:
 *   → show top contacts → user picks one → paste chat or skip
 */
import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, FlatList,
  Animated, ImageBackground, Dimensions, Platform,
  ActivityIndicator, Alert, TextInput,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import * as Contacts from 'expo-contacts';
import * as Clipboard from 'expo-clipboard';
import { Linking } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { getBaseUrl } from '../api';

const { width, height } = Dimensions.get('window');
const BG = require('../../assets/bg_chat.png');

// ── Types ─────────────────────────────────────────────────────────────────────

type Phase =
  | 'greeting'
  | 'checking_connections'
  | 'awaiting_mac'
  | 'mac_connecting'
  | 'awaiting_atv'
  | 'awaiting_google'
  | 'requesting_contacts'
  | 'counting_contacts'      // batch-counting via Mac
  | 'auto_analyzing'         // auto-analyzing top 3 (Mac connected)
  | 'selecting_contact'      // manual pick (no Mac)
  | 'awaiting_paste'
  | 'processing'
  | 'done';

interface ChatMessage {
  id:         string;
  role:       'genie' | 'user';
  type:       'text' | 'contacts_list' | 'paste_button' | 'action_button' | 'mac_setup' | 'top3_preview';
  text?:      string;
  action?:    string;
  label?:     string;
  skipLabel?: string;
  macCommand?: string;
  top3?: Top3Item[];
}

interface ContactItem {
  id:              string;
  name:            string;
  phone:           string;
  normalizedPhone: string;
  msgCount?:       number;
}

interface Top3Item {
  name:     string;
  phone:    string;
  count:    number;
}

interface Connections {
  mac:    boolean | null;
  atv:    boolean | null;
  google: boolean | null;
}

let msgId = 0;
const newId = () => String(++msgId);

// ── Helpers ───────────────────────────────────────────────────────────────────

function normalizePhone(raw: string): string {
  const digits = raw.replace(/\D/g, '');
  if (!digits) return '';
  if (digits.length === 10) return `+1${digits}`;
  if (digits.length === 11 && digits.startsWith('1')) return `+${digits}`;
  return `+${digits}`;
}

function scoreContact(c: Contacts.Contact): number {
  let score = 0;
  if (c.imageAvailable)                                                    score += 3;
  if (c.birthday)                                                          score += 2;
  if (c.emails && c.emails.length > 0)                                    score += 2;
  if ((c as any).note)                                                     score += 2;
  if ((c as any).relationships && (c as any).relationships.length > 0)    score += 3;
  if (c.company)                                                           score += 1;
  if (c.phoneNumbers && c.phoneNumbers.length > 1)                        score += 1;
  if (c.addresses && c.addresses.length > 0)                              score += 3;
  if (c.addresses && c.addresses.some(
    (a: any) => a.label?.toLowerCase() === 'home'))                       score += 3;
  if (c.addresses && c.addresses.length > 1)                              score += 1;
  return score;
}

function fmtCount(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1).replace('.0', '')}k`;
  return String(n);
}

async function discoverATV(baseUrl: string): Promise<boolean> {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 3000);
    const res = await fetch(`${baseUrl}/atv/discover`, { signal: controller.signal });
    clearTimeout(timer);
    if (!res.ok) return false;
    const data = await res.json();
    return Array.isArray(data.devices) && data.devices.length > 0;
  } catch {
    return false;
  }
}

// ── Main component ────────────────────────────────────────────────────────────

export default function SetupChatScreen({ navigation }: any) {
  const [phase, setPhase]                     = useState<Phase>('greeting');
  const [messages, setMessages]               = useState<ChatMessage[]>([]);
  const [allContacts, setAllContacts]         = useState<ContactItem[]>([]);
  const [topContacts, setTopContacts]         = useState<ContactItem[]>([]);
  const [searchQuery, setSearchQuery]         = useState('');
  const [selectedContact, setSelectedContact] = useState<ContactItem | null>(null);
  const [pasting, setPasting]                 = useState(false);
  const [macUrl, setMacUrl]                   = useState<string | null>(null);
  const [macCheckLoading, setMacCheckLoading] = useState(false);
  const [readingStatus, setReadingStatus]     = useState('');
  const [connections, setConnections]         = useState<Connections>({
    mac: null, atv: null, google: null,
  });
  const connectionQueueRef = useRef<Phase[]>([]);
  const listRef            = useRef<FlatList>(null);

  // ── Message helpers ────────────────────────────────────────────────────────

  const pushMessage = useCallback((msg: Omit<ChatMessage, 'id'>) => {
    return new Promise<void>(resolve => {
      setTimeout(() => {
        setMessages(prev => [...prev, { id: newId(), ...msg }]);
        setTimeout(() => { listRef.current?.scrollToEnd({ animated: true }); resolve(); }, 80);
      }, 600);
    });
  }, []);

  const genie = useCallback((text: string) =>
    pushMessage({ role: 'genie', type: 'text', text }), [pushMessage]);

  const user = useCallback((text: string) => {
    setMessages(prev => [...prev, { id: newId(), role: 'user', type: 'text', text }]);
    setTimeout(() => listRef.current?.scrollToEnd({ animated: true }), 80);
  }, []);

  // ── Boot ──────────────────────────────────────────────────────────────────

  useEffect(() => {
    async function boot() {
      await genie("Hello. I'm your Personal Genie.");
      await genie("I help you understand and nurture your most important relationships.");
      await genie("Let me see what I can connect to…");
      setPhase('checking_connections');
      await checkConnections();
    }
    boot();
  }, []);

  // ── Connection detection ───────────────────────────────────────────────────

  async function checkConnections() {
    const baseUrl = await getBaseUrl();
    const atvFound = await discoverATV(baseUrl);

    const queue: Phase[] = [];
    queue.push('awaiting_mac');
    if (atvFound) queue.push('awaiting_atv');
    queue.push('awaiting_google');

    connectionQueueRef.current = queue;
    await advanceConnectionQueue();
  }

  async function advanceConnectionQueue() {
    const queue = connectionQueueRef.current;
    if (queue.length === 0) {
      await requestContacts();
      return;
    }
    const next = queue.shift()!;
    connectionQueueRef.current = queue;
    setPhase(next);

    if (next === 'awaiting_mac') {
      await genie("Do you have a Mac? If so, I can read your actual iMessage history — thousands of messages — and give you a much deeper analysis.");
      setMessages(prev => [...prev, {
        id: newId(), role: 'genie', type: 'action_button',
        action: 'mac', label: 'Yes, connect my Mac', skipLabel: 'No Mac / skip',
      }]);
    } else if (next === 'awaiting_atv') {
      await genie("I found an Apple TV on your network. Want me to connect?");
      setMessages(prev => [...prev, {
        id: newId(), role: 'genie', type: 'action_button',
        action: 'atv', label: 'Connect Apple TV', skipLabel: 'Skip for now',
      }]);
    } else if (next === 'awaiting_google') {
      await genie("Want me to connect Google so I can read your Gmail and contacts?");
      setMessages(prev => [...prev, {
        id: newId(), role: 'genie', type: 'action_button',
        action: 'google', label: 'Connect Google', skipLabel: 'Skip for now',
      }]);
    }
  }

  // ── Mac companion flow ─────────────────────────────────────────────────────

  async function handleMacAccepted() {
    user('Yes, connect my Mac');
    setConnections(prev => ({ ...prev, mac: true }));
    setPhase('mac_connecting');

    const companionDir = '~/PersonalGenieApp/mac-companion';
    const cmd = `cd ${companionDir} && bash start.sh`;

    await genie("Perfect. I need a small companion app running on your Mac to read iMessages.\n\nOpen Terminal on your Mac and run this:");
    setMessages(prev => [...prev, {
      id: newId(), role: 'genie', type: 'mac_setup',
      macCommand: cmd,
    }]);
    await new Promise(r => setTimeout(r, 1200));
    await genie("Once it's running, tap the button below.");
    setMessages(prev => [...prev, {
      id: newId(), role: 'genie', type: 'action_button',
      action: 'check_mac', label: 'Companion is running ✓', skipLabel: 'Skip for now',
    }]);
  }

  async function handleCheckMac() {
    setMacCheckLoading(true);
    try {
      const baseUrl = await getBaseUrl();

      // Step 1: get the Mac's local URL from backend
      const statusRes = await fetch(`${baseUrl}/mac/status`, { signal: AbortSignal.timeout(8000) });
      if (!statusRes.ok) throw new Error('Backend unreachable');
      const statusData = await statusRes.json();
      if (!statusData.url) throw new Error('Mac not registered');

      const url = statusData.url;

      // Step 2: ping the Mac directly (iOS and Mac are on same WiFi)
      const pingRes = await fetch(`${url}/health`, { signal: AbortSignal.timeout(5000) });
      if (!pingRes.ok) throw new Error('Mac companion not responding');

      setMacUrl(url);
      setConnections(prev => ({ ...prev, mac: true }));
      user('Companion is running ✓');
      await genie("Mac connected. I can see your messages.");
      await advanceConnectionQueue();
    } catch (e: any) {
      await genie(
        "I couldn't reach the companion. Make sure:\n\n" +
        "1. Your Mac and iPhone are on the same WiFi\n" +
        "2. The companion is running in Terminal (bash start.sh)\n\n" +
        "Then tap the button again."
      );
    } finally {
      setMacCheckLoading(false);
    }
  }

  async function handleConnectionAction(action: string, accepted: boolean) {
    if (action === 'mac') {
      if (accepted) {
        await handleMacAccepted();
        return;
      }
      user('No Mac / skip');
      setConnections(prev => ({ ...prev, mac: false }));
      await genie("No problem. You can still share a chat manually.");
    } else if (action === 'check_mac') {
      if (accepted) {
        await handleCheckMac();
        return;
      }
      user('Skip for now');
      setConnections(prev => ({ ...prev, mac: false }));
      await genie("Got it. You can share messages manually.");
    } else if (action === 'atv') {
      user(accepted ? 'Connect Apple TV' : 'Skip for now');
      setConnections(prev => ({ ...prev, atv: accepted }));
      if (accepted) {
        try {
          const baseUrl = await getBaseUrl();
          await fetch(`${baseUrl}/atv/connect`, { method: 'POST' });
          await genie("Apple TV connected.");
        } catch {
          await genie("Couldn't connect right now. Moving on.");
        }
      } else {
        await genie("Got it.");
      }
    } else if (action === 'google') {
      user(accepted ? 'Connect Google' : 'Skip for now');
      setConnections(prev => ({ ...prev, google: accepted }));
      if (accepted) {
        try {
          const baseUrl = await getBaseUrl();
          let userId = await AsyncStorage.getItem('pg_user_id');
          if (!userId) {
            userId = await AsyncStorage.getItem('pg_device_id');
            if (!userId) {
              userId = `device_${Math.random().toString(36).slice(2)}_${Date.now()}`;
              await AsyncStorage.setItem('pg_device_id', userId);
            }
          }
          const res = await fetch(`${baseUrl}/auth/google/url?user_id=${encodeURIComponent(userId)}`);
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          const { auth_url } = await res.json();
          await Linking.openURL(auth_url);
          await genie("Opening Google sign-in… come back here when done.");
        } catch {
          await genie("Couldn't open Google sign-in. You can connect later in settings.");
        }
      } else {
        await genie("Okay, we'll keep it simple.");
      }
    }
    await advanceConnectionQueue();
  }

  // ── Contacts ──────────────────────────────────────────────────────────────

  async function requestContacts() {
    setPhase('requesting_contacts');
    await genie("Now I need access to your contacts. May I?");
    setMessages(prev => [...prev, {
      id: newId(), role: 'genie', type: 'action_button',
      action: 'contacts', label: 'Allow Contacts Access', skipLabel: undefined,
    }]);
  }

  async function handleAllowContacts() {
    const { status } = await Contacts.requestPermissionsAsync();
    if (status !== 'granted') {
      Alert.alert('Contacts access needed', 'Please allow contacts in Settings to continue.');
      return;
    }
    user('Allow Contacts Access');

    const { data } = await Contacts.getContactsAsync({
      fields: [
        Contacts.Fields.Name,
        Contacts.Fields.PhoneNumbers,
        Contacts.Fields.Emails,
        Contacts.Fields.Birthday,
        Contacts.Fields.Image,
        Contacts.Fields.Addresses,
        Contacts.Fields.Company,
        Contacts.Fields.Relationships,
      ],
      sort: Contacts.SortTypes.UserDefault,
    });

    // Score by profile completeness
    const withPhone = data.filter(c => c.name && c.phoneNumbers && c.phoneNumbers.length > 0);
    const scored = withPhone
      .map(c => ({ c, score: scoreContact(c) }))
      .sort((a, b) => b.score - a.score);

    // Deduplicate: normalize phone → keep best-named entry
    const seenPhones = new Map<string, ContactItem>();
    for (const { c } of scored) {
      for (const ph of c.phoneNumbers ?? []) {
        const raw = ph.number ?? '';
        const normalized = normalizePhone(raw);
        if (!normalized) continue;
        const candidate: ContactItem = {
          id: c.id ?? newId(),
          name: c.name!,
          phone: raw,
          normalizedPhone: normalized,
        };
        const existing = seenPhones.get(normalized);
        if (!existing || candidate.name.length > existing.name.length) {
          seenPhones.set(normalized, candidate);
        }
      }
    }
    const deduped = Array.from(seenPhones.values());

    if (macUrl) {
      // ── Mac path: batch-count → auto-analyze top 3 ──────────────────────
      setPhase('counting_contacts');
      await genie("Counting your messages with everyone…");

      const candidates = deduped.slice(0, 80);
      const phones = candidates.map(c => c.normalizedPhone);
      let messageCounts: Record<string, number> = {};

      try {
        const res = await fetch(`${macUrl}/batch-count`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ phones }),
          signal: AbortSignal.timeout(40_000),
        });
        if (res.ok) {
          const d = await res.json();
          messageCounts = d.counts ?? {};
        }
      } catch { /* fall back to profile score */ }

      // Attach counts, sort descending, pick top 3 with actual messages
      const withCounts = candidates.map(c => ({
        ...c,
        msgCount: messageCounts[c.normalizedPhone] ?? 0,
      }));
      withCounts.sort((a, b) => (b.msgCount ?? 0) - (a.msgCount ?? 0));
      setAllContacts(withCounts);

      const top3 = withCounts.filter(c => (c.msgCount ?? 0) > 0).slice(0, 3);

      if (top3.length > 0) {
        // Show who we found and auto-analyze without asking
        setMessages(prev => [...prev, {
          id: newId(), role: 'genie', type: 'top3_preview',
          top3: top3.map(c => ({ name: c.name, phone: c.phone, count: c.msgCount ?? 0 })),
        }]);
        await new Promise(r => setTimeout(r, 1000));
        await genie("I'll read through all of them now.");
        await autoAnalyzeTop3(top3);
      } else {
        // No message data — fall back to manual pick
        await genie("I couldn't find any message history. Let's do this manually — who do you want to start with?");
        setTopContacts(deduped.slice(0, 10));
        setPhase('selecting_contact');
        setMessages(prev => [...prev, { id: newId(), role: 'genie', type: 'contacts_list' }]);
      }
    } else {
      // ── No Mac: manual pick ──────────────────────────────────────────────
      setAllContacts(deduped);
      setTopContacts(deduped.slice(0, 10));
      setPhase('selecting_contact');
      await genie("Who would you like me to understand better?");
      setMessages(prev => [...prev, { id: newId(), role: 'genie', type: 'contacts_list' }]);
    }
  }

  // ── Auto-analyze top 3 (Mac path) ─────────────────────────────────────────

  async function autoAnalyzeTop3(top3: ContactItem[]) {
    setPhase('auto_analyzing');
    const batchInsights: any[] = [];

    for (let i = 0; i < top3.length; i++) {
      const contact = top3[i];
      const firstName = contact.name.split(' ')[0];
      const count = contact.msgCount ?? 0;
      const countLabel = fmtCount(count);

      setReadingStatus(`Reading ${countLabel} messages with ${firstName}…`);

      if (i === 0) {
        await genie(`Starting with ${firstName} — ${countLabel} messages. Reading now…`);
      } else {
        await genie(`Now reading ${firstName}'s messages — ${countLabel} total.`);
      }

      try {
        const res = await fetch(`${macUrl}/analyze`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            contact_name: contact.name,
            contact_phone: contact.phone,
          }),
          signal: AbortSignal.timeout(180_000),
        });

        if (res.ok) {
          const insights = await res.json();
          batchInsights.push({ contact, insights, source: 'mac' });
          if (i < top3.length - 1) {
            await genie(`Done with ${firstName}.`);
          }
        } else {
          const err = await res.json().catch(() => ({}));
          batchInsights.push({
            contact,
            insights: {
              key_memory: '',
              summary: `${contact.name}: ${err.detail ?? 'Analysis unavailable.'}`,
              message_count: count,
              who_initiates: 'unknown',
              memories: [],
              relationship_score: null,
              tip: '',
            },
            source: 'mac_error',
          });
        }
      } catch (e: any) {
        batchInsights.push({
          contact,
          insights: {
            key_memory: '',
            summary: `Analysis timed out for ${contact.name}.`,
            message_count: count,
            who_initiates: 'unknown',
            memories: [],
            relationship_score: null,
            tip: '',
          },
          source: 'mac_error',
        });
      }
    }

    setReadingStatus('');
    await genie("I've read through your closest relationships. Here's what I found.");

    await AsyncStorage.setItem('pg_insights_batch', JSON.stringify({
      items: batchInsights,
      connections,
      processedAt: new Date().toISOString(),
    }));

    setPhase('done');
    navigation.replace('Insights');
  }

  // ── Manual contact selection (no Mac) ─────────────────────────────────────

  async function handleSelectContact(contact: ContactItem) {
    if (phase !== 'selecting_contact') return;
    setSelectedContact(contact);
    setPhase('awaiting_paste');
    setSearchQuery('');
    user(contact.name);

    const firstName = contact.name.split(' ')[0];
    await genie(`${firstName}. Good choice.`);
    await genie(
      `Open Messages on your iPhone, find the chat with ${firstName}, ` +
      `long-press a message → More → select as many as you can → tap the copy icon.\n\n` +
      `Then come back and paste below.`
    );
    setMessages(prev => [...prev, { id: newId(), role: 'genie', type: 'paste_button' }]);
  }

  // ── Paste ──────────────────────────────────────────────────────────────────

  async function handlePaste() {
    setPasting(true);
    try {
      const text = await Clipboard.getStringAsync();
      if (!text || text.trim().length < 20) {
        Alert.alert('Nothing to paste', "Copy messages from Messages first, then come back.");
        setPasting(false);
        return;
      }
      user('Conversation copied ✓');
      setPhase('processing');
      await genie("Got it. Give me a moment…");
      await processConversation(text);
    } catch {
      Alert.alert('Error', 'Could not read clipboard. Please try again.');
      setPasting(false);
    }
  }

  async function processConversation(conversationText: string) {
    try {
      const userId = await AsyncStorage.getItem('pg_user_id');
      const { analyzeRelationship } = await import('../api');
      const result = await analyzeRelationship({
        userId:           userId ?? 'anonymous',
        contactName:      selectedContact!.name,
        contactPhone:     selectedContact!.phone,
        conversationText,
      });
      const batchItem = {
        contact: selectedContact,
        insights: result,
        source: 'paste',
      };
      await AsyncStorage.setItem('pg_insights_batch', JSON.stringify({
        items: [batchItem],
        connections,
        processedAt: new Date().toISOString(),
      }));
    } catch {
      const batchItem = {
        contact: selectedContact,
        insights: {
          key_memory: '',
          summary: `Your relationship with ${selectedContact?.name}.`,
          message_count: null,
          who_initiates: 'unknown',
          memories: [],
          relationship_score: null,
          tip: 'Keep showing up consistently.',
        },
        source: 'paste_fallback',
      };
      await AsyncStorage.setItem('pg_insights_batch', JSON.stringify({
        items: [batchItem],
        connections,
        processedAt: new Date().toISOString(),
      }));
    }
    setPhase('done');
    navigation.replace('Insights');
  }

  // ── Filtered contacts ──────────────────────────────────────────────────────

  const displayedContacts = searchQuery.trim().length > 0
    ? allContacts
        .filter(c =>
          c.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
          c.phone.includes(searchQuery)
        )
        .slice(0, 15)
    : topContacts;

  // ── Render ─────────────────────────────────────────────────────────────────

  function renderMessage({ item }: { item: ChatMessage }) {
    if (item.type === 'mac_setup') {
      return (
        <View style={s.macSetupBox}>
          <Text style={s.macSetupLabel}>Run in Terminal on your Mac:</Text>
          <View style={s.macCodeBox}>
            <Text style={s.macCode} selectable>{item.macCommand}</Text>
          </View>
        </View>
      );
    }

    if (item.type === 'top3_preview' && item.top3) {
      return (
        <View style={s.top3Box}>
          <Text style={s.top3Label}>YOUR CLOSEST RELATIONSHIPS</Text>
          {item.top3.map((t, i) => (
            <View key={i} style={s.top3Row}>
              <View style={s.top3Dot} />
              <Text style={s.top3Name}>{t.name}</Text>
              <Text style={s.top3Count}>{fmtCount(t.count)} messages</Text>
            </View>
          ))}
        </View>
      );
    }

    if (item.type === 'action_button' && item.action) {
      const isMacCheck = item.action === 'check_mac';
      return (
        <View style={s.actionRow}>
          <TouchableOpacity
            style={[s.actionBtn, isMacCheck && macCheckLoading && { opacity: 0.7 }]}
            disabled={isMacCheck && macCheckLoading}
            onPress={() => {
              if (item.action === 'contacts') handleAllowContacts();
              else handleConnectionAction(item.action!, true);
            }}
          >
            {isMacCheck && macCheckLoading
              ? <ActivityIndicator color="#0A0A0F" size="small" />
              : <Text style={s.actionBtnText}>{item.label}</Text>
            }
          </TouchableOpacity>
          {item.skipLabel && (
            <TouchableOpacity
              style={s.skipBtn}
              onPress={() => handleConnectionAction(item.action!, false)}
            >
              <Text style={s.skipBtnText}>{item.skipLabel}</Text>
            </TouchableOpacity>
          )}
        </View>
      );
    }

    if (item.type === 'contacts_list') {
      return (
        <View style={s.contactsContainer}>
          <TextInput
            style={s.searchInput}
            value={searchQuery}
            onChangeText={setSearchQuery}
            placeholder="Search any contact…"
            placeholderTextColor="#4A4438"
            returnKeyType="search"
            clearButtonMode="while-editing"
          />
          <View style={s.contactsList}>
            {displayedContacts.length === 0 ? (
              <View style={s.noResults}>
                <Text style={s.noResultsText}>No contacts found</Text>
              </View>
            ) : (
              displayedContacts.map(c => (
                <TouchableOpacity
                  key={c.id}
                  style={s.contactRow}
                  onPress={() => handleSelectContact(c)}
                  activeOpacity={0.7}
                >
                  <View style={s.contactDot} />
                  <View style={{ flex: 1 }}>
                    <Text style={s.contactName}>{c.name}</Text>
                    <Text style={s.contactPhone}>{c.phone}</Text>
                  </View>
                  {c.msgCount != null && c.msgCount > 0 && (
                    <Text style={s.contactMsgCount}>{fmtCount(c.msgCount)}</Text>
                  )}
                </TouchableOpacity>
              ))
            )}
          </View>
          {!searchQuery && allContacts.length > 10 && (
            <Text style={s.searchHint}>
              Showing top {topContacts.length} · Search to find anyone
            </Text>
          )}
        </View>
      );
    }

    if (item.type === 'paste_button') {
      return (
        <View style={s.actionRow}>
          <TouchableOpacity
            style={[s.actionBtn, pasting && { opacity: 0.7 }]}
            onPress={handlePaste}
            disabled={pasting || phase !== 'awaiting_paste'}
          >
            {pasting
              ? <ActivityIndicator color="#0A0A0F" size="small" />
              : <Text style={s.actionBtnText}>Paste Conversation</Text>
            }
          </TouchableOpacity>
        </View>
      );
    }

    // Processing / reading indicator on last genie message
    if (
      item.role === 'genie' &&
      (phase === 'processing' || phase === 'auto_analyzing') &&
      item.id === messages[messages.length - 1]?.id
    ) {
      return (
        <View style={s.bubbleRowGenie}>
          <View style={[s.bubble, s.bubbleGenie]}>
            <ThinkingDots />
            {readingStatus ? (
              <Text style={[s.bubbleText, s.bubbleTextGenie, { marginTop: 6, opacity: 0.65, fontSize: 13 }]}>
                {readingStatus}
              </Text>
            ) : null}
          </View>
        </View>
      );
    }

    return <MessageBubble message={item} />;
  }

  return (
    <ImageBackground source={BG} style={s.bg} resizeMode="cover">
      <LinearGradient
        colors={['rgba(5,4,10,0.90)', 'rgba(5,4,10,0.4)', 'transparent']}
        style={s.gradTop}
        pointerEvents="none"
      />
      <LinearGradient
        colors={['transparent', 'rgba(5,4,10,0.92)', 'rgba(5,4,10,0.99)']}
        style={s.gradBottom}
        pointerEvents="none"
      />
      <View style={s.header}>
        <Text style={s.wordmark}>PERSONAL GENIE</Text>
      </View>
      <FlatList
        ref={listRef}
        data={messages}
        keyExtractor={m => m.id}
        renderItem={renderMessage}
        style={s.list}
        contentContainerStyle={s.listContent}
        showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
        extraData={{ phase, searchQuery, pasting, macCheckLoading, readingStatus, displayedContacts }}
      />
    </ImageBackground>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function MessageBubble({ message }: { message: ChatMessage }) {
  const isGenie = message.role === 'genie';
  const fade    = useRef(new Animated.Value(0)).current;
  const slide   = useRef(new Animated.Value(10)).current;

  useEffect(() => {
    Animated.parallel([
      Animated.spring(slide, { toValue: 0, useNativeDriver: true, tension: 60, friction: 10 }),
      Animated.timing(fade,  { toValue: 1, duration: 250, useNativeDriver: true }),
    ]).start();
  }, []);

  return (
    <Animated.View style={[
      isGenie ? s.bubbleRowGenie : s.bubbleRowUser,
      { opacity: fade, transform: [{ translateY: slide }] },
    ]}>
      <View style={[s.bubble, isGenie ? s.bubbleGenie : s.bubbleUser]}>
        <Text style={[s.bubbleText, isGenie ? s.bubbleTextGenie : s.bubbleTextUser]}>
          {message.text}
        </Text>
      </View>
    </Animated.View>
  );
}

function ThinkingDots() {
  const d0 = useRef(new Animated.Value(0.2)).current;
  const d1 = useRef(new Animated.Value(0.2)).current;
  const d2 = useRef(new Animated.Value(0.2)).current;

  useEffect(() => {
    [d0, d1, d2].forEach((d, i) => {
      Animated.loop(Animated.sequence([
        Animated.delay(i * 160),
        Animated.timing(d, { toValue: 1,   duration: 400, useNativeDriver: true }),
        Animated.timing(d, { toValue: 0.2, duration: 400, useNativeDriver: true }),
      ])).start();
    });
  }, []);

  return (
    <View style={{ flexDirection: 'row', gap: 5, paddingVertical: 4, paddingHorizontal: 4 }}>
      {[d0, d1, d2].map((d, i) => (
        <Animated.View key={i} style={{
          width: 6, height: 6, borderRadius: 3,
          backgroundColor: '#C9A84C', opacity: d,
        }} />
      ))}
    </View>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────

const s = StyleSheet.create({
  bg:         { flex: 1, width, height, backgroundColor: '#0A0A0F' },
  gradTop:    { position: 'absolute', top: 0, left: 0, right: 0, height: height * 0.40, zIndex: 1 },
  gradBottom: { position: 'absolute', bottom: 0, left: 0, right: 0, height: height * 0.30, zIndex: 1 },

  header: {
    paddingTop: Platform.OS === 'ios' ? 64 : 48,
    alignItems: 'center', paddingBottom: 8, zIndex: 3,
  },
  wordmark: {
    fontFamily: 'System', fontSize: 11, fontWeight: '600',
    color: '#C9A84C', letterSpacing: 3.5, textTransform: 'uppercase',
  },

  list:        { flex: 1, zIndex: 3 },
  listContent: { paddingHorizontal: 16, paddingTop: 16, paddingBottom: 48, gap: 10 },

  bubbleRowGenie: { alignItems: 'flex-start' },
  bubbleRowUser:  { alignItems: 'flex-end' },
  bubble: { maxWidth: '85%', borderRadius: 18, paddingHorizontal: 16, paddingVertical: 12 },
  bubbleGenie: {
    backgroundColor: 'rgba(12,12,18,0.88)',
    borderBottomLeftRadius: 4,
    borderWidth: 1, borderColor: '#C9A84C22',
  },
  bubbleUser:      { backgroundColor: '#C9A84C', borderBottomRightRadius: 4 },
  bubbleText:      { fontSize: 15, lineHeight: 23 },
  bubbleTextGenie: { color: '#F5F0E8' },
  bubbleTextUser:  { color: '#0A0A0F', fontWeight: '600' },

  actionRow: { alignItems: 'flex-start', gap: 8 },
  actionBtn: {
    backgroundColor: '#C9A84C', borderRadius: 14,
    paddingVertical: 14, paddingHorizontal: 28,
    minWidth: 180, alignItems: 'center',
  },
  actionBtnText: { color: '#0A0A0F', fontWeight: '700', fontSize: 15 },
  skipBtn: {
    borderWidth: 1, borderColor: '#2A2740', borderRadius: 14,
    paddingVertical: 10, paddingHorizontal: 20,
  },
  skipBtnText: { color: '#8A8070', fontSize: 14, fontWeight: '600' },

  macSetupBox: {
    backgroundColor: 'rgba(12,12,18,0.92)',
    borderRadius: 14, borderWidth: 1, borderColor: '#2A2740',
    padding: 16, gap: 10, maxWidth: '90%',
  },
  macSetupLabel: { color: '#8A8070', fontSize: 13, fontWeight: '600' },
  macCodeBox: {
    backgroundColor: '#0A0A0F', borderRadius: 8,
    padding: 12, borderWidth: 1, borderColor: '#1E1E2E',
  },
  macCode: {
    color: '#C9A84C', fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
    fontSize: 13, lineHeight: 20,
  },

  top3Box: {
    backgroundColor: 'rgba(12,12,18,0.92)',
    borderRadius: 16, borderWidth: 1, borderColor: '#C9A84C33',
    borderLeftWidth: 3, borderLeftColor: '#C9A84C',
    padding: 16, gap: 12, maxWidth: '90%',
  },
  top3Label: {
    fontSize: 10, fontWeight: '700', color: '#C9A84C',
    letterSpacing: 1.8, textTransform: 'uppercase',
  },
  top3Row:   { flexDirection: 'row', alignItems: 'center', gap: 10 },
  top3Dot:   { width: 6, height: 6, borderRadius: 3, backgroundColor: '#C9A84C' },
  top3Name:  { flex: 1, fontSize: 15, fontWeight: '600', color: '#F5F0E8' },
  top3Count: { fontSize: 13, color: '#8A8070' },

  contactsContainer: { width: '100%', gap: 8 },
  searchInput: {
    backgroundColor: 'rgba(12,12,18,0.85)',
    borderWidth: 1, borderColor: '#2A2740', borderRadius: 12,
    paddingHorizontal: 16, paddingVertical: 12,
    fontSize: 15, color: '#F5F0E8',
  },
  contactsList: {
    backgroundColor: 'rgba(12,12,18,0.90)',
    borderRadius: 16, borderWidth: 1, borderColor: '#1E1E2E',
    overflow: 'hidden',
  },
  contactRow: {
    flexDirection: 'row', alignItems: 'center',
    paddingHorizontal: 16, paddingVertical: 14,
    borderBottomWidth: 1, borderBottomColor: '#1E1E2E',
    gap: 12,
  },
  contactDot:     { width: 8, height: 8, borderRadius: 4, backgroundColor: '#C9A84C' },
  contactName:    { fontSize: 15, fontWeight: '600', color: '#F5F0E8' },
  contactPhone:   { fontSize: 12, color: '#8A8070', marginTop: 1 },
  contactMsgCount:{ fontSize: 12, color: '#C9A84C', fontWeight: '600' },
  noResults:      { padding: 20, alignItems: 'center' },
  noResultsText:  { fontSize: 14, color: '#4A4438' },
  searchHint: {
    fontSize: 12, color: '#4A4438', textAlign: 'center', paddingBottom: 4,
  },
});
