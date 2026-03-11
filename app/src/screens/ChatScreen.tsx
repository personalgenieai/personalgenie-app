/**
 * ChatScreen — Primary screen. bg_chat.png ghostly hand background.
 * Genie messages left, user messages right.
 * 3-dot thinking animation. Spring entrance per message.
 */
import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  View, Text, StyleSheet, TextInput, TouchableOpacity,
  FlatList, Animated, KeyboardAvoidingView, Platform,
  ImageBackground, Dimensions, SafeAreaView,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { sendChat } from '../api';

const { width, height } = Dimensions.get('window');
const BG = require('../../assets/bg_chat.png');

interface Message {
  id: string;
  role: 'genie' | 'user';
  text: string;
}

export default function ChatScreen() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput]       = useState('');
  const [thinking, setThinking] = useState(false);
  const [userId, setUserId]     = useState<string | null>(null);
  const listRef = useRef<FlatList>(null);
  const msgId   = useRef(0);

  useEffect(() => {
    AsyncStorage.getItem('pg_user_id').then(setUserId);
  }, []);

  const scrollToBottom = useCallback(() => {
    setTimeout(() => listRef.current?.scrollToEnd({ animated: true }), 80);
  }, []);

  async function handleSend() {
    const text = input.trim();
    if (!text || !userId) return;
    setInput('');

    const userMsg: Message = { id: String(++msgId.current), role: 'user', text };
    setMessages(prev => [...prev, userMsg]);
    scrollToBottom();
    setThinking(true);

    try {
      const reply = await sendChat(userId, text);
      const genieMsg: Message = { id: String(++msgId.current), role: 'genie', text: reply };
      setMessages(prev => [...prev, genieMsg]);
    } catch (_) {
      const errMsg: Message = { id: String(++msgId.current), role: 'genie', text: "I'm having trouble connecting. Try again in a moment." };
      setMessages(prev => [...prev, errMsg]);
    } finally {
      setThinking(false);
      scrollToBottom();
    }
  }

  const canSend = input.trim().length > 0 && !!userId;

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
      <KeyboardAvoidingView
        style={s.kav}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        {/* Header */}
        <SafeAreaView style={s.header}>
          <Text style={s.wordmark}>PERSONAL GENIE</Text>
        </SafeAreaView>

        {/* Messages */}
        <FlatList
          ref={listRef}
          data={messages}
          keyExtractor={m => m.id}
          style={s.list}
          contentContainerStyle={s.listContent}
          renderItem={({ item }) => <MessageBubble message={item} />}
          ListEmptyComponent={<EmptyState />}
          ListFooterComponent={thinking ? <ThinkingBubble /> : null}
          showsVerticalScrollIndicator={false}
          onContentSizeChange={scrollToBottom}
        />

        {/* Input row */}
        <View style={s.inputRow}>
          <TextInput
            style={s.input}
            value={input}
            onChangeText={setInput}
            placeholder="Ask your Genie…"
            placeholderTextColor="#4A4438"
            multiline
            maxLength={1000}
            returnKeyType="send"
            onSubmitEditing={handleSend}
            blurOnSubmit={false}
          />
          <TouchableOpacity
            style={[s.sendBtn, !canSend && s.sendBtnDisabled]}
            onPress={handleSend}
            disabled={!canSend}
            activeOpacity={0.8}
          >
            <View style={s.sendArrow} />
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </ImageBackground>
  );
}

function MessageBubble({ message }: { message: Message }) {
  const isGenie = message.role === 'genie';
  const slide = useRef(new Animated.Value(12)).current;
  const fade  = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.parallel([
      Animated.spring(slide, { toValue: 0, useNativeDriver: true, tension: 60, friction: 10 }),
      Animated.timing(fade, { toValue: 1, duration: 250, useNativeDriver: true }),
    ]).start();
  }, []);

  return (
    <Animated.View style={[
      s.bubbleRow,
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

function ThinkingBubble() {
  const d0 = useRef(new Animated.Value(0.2)).current;
  const d1 = useRef(new Animated.Value(0.2)).current;
  const d2 = useRef(new Animated.Value(0.2)).current;
  const dots = [d0, d1, d2];

  useEffect(() => {
    dots.forEach((d, i) => {
      Animated.loop(
        Animated.sequence([
          Animated.delay(i * 160),
          Animated.timing(d, { toValue: 1,   duration: 400, useNativeDriver: true }),
          Animated.timing(d, { toValue: 0.2, duration: 400, useNativeDriver: true }),
        ])
      ).start();
    });
  }, []);

  return (
    <View style={[s.bubbleRow, s.bubbleRowGenie]}>
      <View style={[s.bubble, s.bubbleGenie, s.thinkingBubble]}>
        {dots.map((d, i) => (
          <Animated.View key={i} style={[s.dot, { opacity: d }]} />
        ))}
      </View>
    </View>
  );
}

function EmptyState() {
  return (
    <View style={s.empty}>
      <Text style={s.emptyHeadline}>Ask me anything.</Text>
      <Text style={s.emptySub}>Or just say hello.</Text>
    </View>
  );
}

const s = StyleSheet.create({
  bg:          { flex: 1, width, height, backgroundColor: '#0A0A0F' },
  kav:         { flex: 1 },
  gradTop:     { position: 'absolute', top: 0, left: 0, right: 0, height: height * 0.40, zIndex: 1 },
  gradBottom:  { position: 'absolute', bottom: 0, left: 0, right: 0, height: height * 0.50, zIndex: 1 },

  header: {
    zIndex: 3,
    alignItems: 'center',
    paddingTop: Platform.OS === 'ios' ? 0 : 16,
    paddingBottom: 8,
  },
  wordmark: {
    fontFamily: 'System', fontSize: 11, fontWeight: '600',
    color: '#C9A84C', letterSpacing: 3.5, textTransform: 'uppercase',
  },

  list:        { flex: 1, zIndex: 3 },
  listContent: { paddingHorizontal: 16, paddingTop: 8, paddingBottom: 16, gap: 8 },

  bubbleRow:      { flexDirection: 'row', marginVertical: 2 },
  bubbleRowGenie: { justifyContent: 'flex-start' },
  bubbleRowUser:  { justifyContent: 'flex-end' },

  bubble: {
    maxWidth: '78%',
    borderRadius: 18,
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  bubbleGenie: {
    backgroundColor: 'rgba(12,12,18,0.88)',
    borderBottomLeftRadius: 4,
    borderWidth: 1,
    borderColor: '#C9A84C22',
  },
  bubbleUser: {
    backgroundColor: '#C9A84C',
    borderBottomRightRadius: 4,
  },
  bubbleText:      { fontSize: 16, lineHeight: 24 },
  bubbleTextGenie: { color: '#F5F0E8' },
  bubbleTextUser:  { color: '#0A0A0F', fontWeight: '600' },

  thinkingBubble: { flexDirection: 'row', gap: 6, paddingVertical: 16, paddingHorizontal: 20 },
  dot:            { width: 6, height: 6, borderRadius: 3, backgroundColor: '#C9A84C' },

  empty: {
    flex: 1, alignItems: 'center', justifyContent: 'center',
    paddingTop: height * 0.25,
    gap: 8,
  },
  emptyHeadline: { fontFamily: 'Georgia', fontStyle: 'italic', fontSize: 22, color: '#F5F0E8' },
  emptySub:      { fontSize: 15, color: '#8A8070' },

  inputRow: {
    zIndex: 3,
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: 10,
    paddingHorizontal: 16,
    paddingVertical: 12,
    paddingBottom: Platform.OS === 'ios' ? 20 : 12,
    backgroundColor: 'rgba(10,10,15,0.95)',
    borderTopWidth: 1,
    borderTopColor: '#1E1E2E',
  },
  input: {
    flex: 1,
    backgroundColor: 'rgba(18,18,26,0.9)',
    borderRadius: 24,
    borderWidth: 1,
    borderColor: '#2A2740',
    paddingHorizontal: 18,
    paddingVertical: 12,
    fontSize: 16,
    color: '#F5F0E8',
    maxHeight: 120,
  },
  sendBtn: {
    width: 44, height: 44, borderRadius: 22,
    backgroundColor: '#C9A84C',
    alignItems: 'center', justifyContent: 'center',
  },
  sendBtnDisabled: { backgroundColor: '#1E1E2E' },
  sendArrow: {
    width: 0, height: 0,
    borderLeftWidth: 6, borderLeftColor: 'transparent',
    borderRightWidth: 6, borderRightColor: 'transparent',
    borderBottomWidth: 10, borderBottomColor: '#0A0A0F',
    marginBottom: 2,
  },
});
