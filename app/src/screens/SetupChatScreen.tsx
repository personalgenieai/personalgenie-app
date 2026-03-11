/**
 * SetupChatScreen — Guided chat flow.
 * Phase state machine: greeting → contacts → selecting → pasting → processing → done
 * bg_chat.png background (ghostly hand).
 */
import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, FlatList,
  Animated, ImageBackground, Dimensions, Platform,
  ActivityIndicator, Alert,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import * as Contacts from 'expo-contacts';
import * as Clipboard from 'expo-clipboard';
import AsyncStorage from '@react-native-async-storage/async-storage';

const { width, height } = Dimensions.get('window');
const BG = require('../../assets/bg_chat.png');

type Phase =
  | 'greeting'
  | 'requesting_contacts'
  | 'selecting_contact'
  | 'contact_selected'
  | 'awaiting_paste'
  | 'processing'
  | 'done';

interface ChatMessage {
  id: string;
  role: 'genie' | 'user';
  type: 'text' | 'contacts_list' | 'paste_button';
  text?: string;
  contacts?: ContactItem[];
}

interface ContactItem {
  id: string;
  name: string;
  phone: string;
}

let msgIdCounter = 0;
const newId = () => String(++msgIdCounter);

export default function SetupChatScreen({ navigation }: any) {
  const [phase, setPhase]               = useState<Phase>('greeting');
  const [messages, setMessages]         = useState<ChatMessage[]>([]);
  const [selectedContact, setSelectedContact] = useState<ContactItem | null>(null);
  const [pasting, setPasting]           = useState(false);
  const listRef = useRef<FlatList>(null);

  const addGenieMessage = useCallback((text: string, type: ChatMessage['type'] = 'text', extra?: Partial<ChatMessage>) => {
    return new Promise<void>(resolve => {
      setTimeout(() => {
        setMessages(prev => [...prev, { id: newId(), role: 'genie', type, text, ...extra }]);
        setTimeout(() => {
          listRef.current?.scrollToEnd({ animated: true });
          resolve();
        }, 100);
      }, 600);
    });
  }, []);

  const addUserMessage = useCallback((text: string) => {
    setMessages(prev => [...prev, { id: newId(), role: 'user', type: 'text', text }]);
    setTimeout(() => listRef.current?.scrollToEnd({ animated: true }), 100);
  }, []);

  // ── Boot sequence ──────────────────────────────────────────────────────────
  useEffect(() => {
    async function boot() {
      await addGenieMessage("Hello. I'm your Personal Genie.");
      await addGenieMessage("I help you understand and nurture your most important relationships.");
      await addGenieMessage("To get started, I need access to your contacts. May I?");
      setMessages(prev => [...prev, {
        id: newId(), role: 'genie', type: 'text',
        text: '__contacts_permission__',
      }]);
      setPhase('requesting_contacts');
    }
    boot();
  }, []);

  // ── Request contacts permission ────────────────────────────────────────────
  async function handleRequestContacts() {
    const { status } = await Contacts.requestPermissionsAsync();
    if (status !== 'granted') {
      Alert.alert('Contacts access needed', 'Please allow contacts access in Settings to continue.');
      return;
    }
    addUserMessage('Allow contacts');
    setPhase('selecting_contact');

    // Load contacts
    const { data } = await Contacts.getContactsAsync({
      fields: [
        Contacts.Fields.Name,
        Contacts.Fields.PhoneNumbers,
        Contacts.Fields.Birthday,
        Contacts.Fields.Emails,
      ],
      sort: Contacts.SortTypes.UserDefault,
    });

    // Filter to contacts with names + phone numbers, take top 20
    const filtered: ContactItem[] = data
      .filter((c) => c.name && c.phoneNumbers && c.phoneNumbers.length > 0)
      .slice(0, 20)
      .map((c) => ({
        id: c.id ?? newId(),
        name: c.name!,
        phone: c.phoneNumbers![0].number ?? '',
      }));

    await addGenieMessage("Got it. Who would you like me to understand better?");
    setMessages(prev => [...prev, {
      id: newId(), role: 'genie', type: 'contacts_list',
      contacts: filtered.slice(0, 10),
    }]);
  }

  // ── Contact selected ───────────────────────────────────────────────────────
  async function handleSelectContact(contact: ContactItem) {
    setSelectedContact(contact);
    setPhase('contact_selected');
    addUserMessage(contact.name);

    const firstName = contact.name.split(' ')[0];

    await addGenieMessage(`${firstName}. Good choice.`);
    await addGenieMessage(
      `Now I need to see your conversation with ${firstName}. Here's how:\n\n` +
      `1. Open Messages on your phone\n` +
      `2. Find your conversation with ${firstName}\n` +
      `3. Long-press any message → tap More\n` +
      `4. Select as many messages as you can\n` +
      `5. Tap the copy icon (bottom left)\n` +
      `6. Come back here and tap the button below`
    );

    setMessages(prev => [...prev, {
      id: newId(), role: 'genie', type: 'paste_button',
    }]);
    setPhase('awaiting_paste');
  }

  // ── Paste conversation ─────────────────────────────────────────────────────
  async function handlePaste() {
    setPasting(true);
    try {
      const text = await Clipboard.getStringAsync();
      if (!text || text.trim().length < 20) {
        Alert.alert(
          'Nothing to paste',
          "It doesn't look like you've copied any messages yet. Go to Messages, select some, copy, then come back."
        );
        setPasting(false);
        return;
      }

      addUserMessage('Conversation copied ✓');
      setPhase('processing');
      await addGenieMessage("Got it. Give me a moment…");

      // Send to backend
      await processConversation(text);
    } catch (e) {
      Alert.alert('Error', 'Could not read clipboard. Please try again.');
      setPasting(false);
    }
  }

  // ── Process + navigate ─────────────────────────────────────────────────────
  async function processConversation(conversationText: string) {
    try {
      const userId = await AsyncStorage.getItem('pg_user_id');

      // Import API function
      const { analyzeRelationship } = await import('../api');

      const result = await analyzeRelationship({
        userId: userId ?? 'anonymous',
        contactName: selectedContact!.name,
        contactPhone: selectedContact!.phone,
        conversationText,
      });

      // Store insights locally
      await AsyncStorage.setItem('pg_insights', JSON.stringify({
        contact: selectedContact,
        insights: result,
        processedAt: new Date().toISOString(),
      }));

      setPhase('done');
      // Navigate to insights screen
      navigation.replace('Insights');
    } catch (e: any) {
      // Even if API fails, navigate with whatever we have
      await AsyncStorage.setItem('pg_insights', JSON.stringify({
        contact: selectedContact,
        insights: {
          summary: `Your relationship with ${selectedContact?.name} is being processed.`,
          message_count: null,
          who_initiates: 'unknown',
          memories: [],
          relationship_score: null,
          tip: 'Keep showing up consistently.',
        },
        processedAt: new Date().toISOString(),
      }));
      navigation.replace('Insights');
    }
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  function renderMessage({ item }: { item: ChatMessage }) {
    // Permission button
    if (item.role === 'genie' && item.text === '__contacts_permission__') {
      return (
        <View style={s.bubbleRowGenie}>
          <TouchableOpacity style={s.actionBtn} onPress={handleRequestContacts}>
            <Text style={s.actionBtnText}>Allow Contacts Access</Text>
          </TouchableOpacity>
        </View>
      );
    }

    // Contacts list
    if (item.type === 'contacts_list' && item.contacts) {
      return (
        <View style={s.contactsList}>
          {item.contacts.map(c => (
            <TouchableOpacity
              key={c.id}
              style={s.contactRow}
              onPress={() => phase === 'selecting_contact' ? handleSelectContact(c) : undefined}
              activeOpacity={0.7}
            >
              <View style={s.contactDot} />
              <View style={{ flex: 1 }}>
                <Text style={s.contactName}>{c.name}</Text>
                <Text style={s.contactPhone}>{c.phone}</Text>
              </View>
            </TouchableOpacity>
          ))}
        </View>
      );
    }

    // Paste button
    if (item.type === 'paste_button') {
      return (
        <View style={s.bubbleRowGenie}>
          <TouchableOpacity
            style={[s.actionBtn, pasting && s.actionBtnLoading]}
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

    // Processing indicator — show on last genie message during processing
    if (item.role === 'genie' && phase === 'processing' && item === messages[messages.length - 1]) {
      return (
        <View style={s.bubbleRowGenie}>
          <View style={[s.bubble, s.bubbleGenie]}>
            <ThinkingDots />
          </View>
        </View>
      );
    }

    // Normal text bubble
    return (
      <MessageBubble message={item} />
    );
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
      />
    </ImageBackground>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isGenie = message.role === 'genie';
  const fade  = useRef(new Animated.Value(0)).current;
  const slide = useRef(new Animated.Value(10)).current;

  useEffect(() => {
    Animated.parallel([
      Animated.spring(slide, { toValue: 0, useNativeDriver: true, tension: 60, friction: 10 }),
      Animated.timing(fade, { toValue: 1, duration: 250, useNativeDriver: true }),
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
  const dot0 = useRef(new Animated.Value(0.2)).current;
  const dot1 = useRef(new Animated.Value(0.2)).current;
  const dot2 = useRef(new Animated.Value(0.2)).current;
  const dots = [dot0, dot1, dot2];

  useEffect(() => {
    dots.forEach((d, i) => {
      Animated.loop(Animated.sequence([
        Animated.delay(i * 160),
        Animated.timing(d, { toValue: 1, duration: 400, useNativeDriver: true }),
        Animated.timing(d, { toValue: 0.2, duration: 400, useNativeDriver: true }),
      ])).start();
    });
  }, []);

  return (
    <View style={{ flexDirection: 'row', gap: 5, paddingVertical: 4, paddingHorizontal: 4 }}>
      {dots.map((d, i) => (
        <Animated.View key={i} style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: '#C9A84C', opacity: d }} />
      ))}
    </View>
  );
}

const s = StyleSheet.create({
  bg:         { flex: 1, width, height, backgroundColor: '#0A0A0F' },
  gradTop:    { position: 'absolute', top: 0, left: 0, right: 0, height: height * 0.40, zIndex: 1 },
  gradBottom: { position: 'absolute', bottom: 0, left: 0, right: 0, height: height * 0.30, zIndex: 1 },

  header: {
    paddingTop: Platform.OS === 'ios' ? 64 : 48,
    alignItems: 'center',
    paddingBottom: 8,
    zIndex: 3,
  },
  wordmark: {
    fontFamily: 'System', fontSize: 11, fontWeight: '600',
    color: '#C9A84C', letterSpacing: 3.5, textTransform: 'uppercase',
  },

  list:        { flex: 1, zIndex: 3 },
  listContent: { paddingHorizontal: 16, paddingTop: 16, paddingBottom: 48, gap: 10 },

  bubbleRowGenie: { alignItems: 'flex-start' },
  bubbleRowUser:  { alignItems: 'flex-end' },

  bubble: { maxWidth: '80%', borderRadius: 18, paddingHorizontal: 16, paddingVertical: 12 },
  bubbleGenie: {
    backgroundColor: 'rgba(12,12,18,0.88)',
    borderBottomLeftRadius: 4,
    borderWidth: 1, borderColor: '#C9A84C22',
  },
  bubbleUser: { backgroundColor: '#C9A84C', borderBottomRightRadius: 4 },
  bubbleText:      { fontSize: 15, lineHeight: 23 },
  bubbleTextGenie: { color: '#F5F0E8' },
  bubbleTextUser:  { color: '#0A0A0F', fontWeight: '600' },

  actionBtn: {
    backgroundColor: '#C9A84C', borderRadius: 14,
    paddingVertical: 14, paddingHorizontal: 28,
    marginTop: 4,
  },
  actionBtnLoading: { opacity: 0.7 },
  actionBtnText: { color: '#0A0A0F', fontWeight: '700', fontSize: 15 },

  contactsList: {
    width: '90%',
    backgroundColor: 'rgba(12,12,18,0.90)',
    borderRadius: 16,
    borderWidth: 1, borderColor: '#1E1E2E',
    overflow: 'hidden',
  },
  contactRow: {
    flexDirection: 'row', alignItems: 'center',
    paddingHorizontal: 16, paddingVertical: 14,
    borderBottomWidth: 1, borderBottomColor: '#1E1E2E',
    gap: 12,
  },
  contactDot:   { width: 8, height: 8, borderRadius: 4, backgroundColor: '#C9A84C' },
  contactName:  { fontSize: 15, fontWeight: '600', color: '#F5F0E8' },
  contactPhone: { fontSize: 12, color: '#8A8070', marginTop: 1 },
});
