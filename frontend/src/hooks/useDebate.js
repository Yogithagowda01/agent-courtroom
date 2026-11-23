import { useCallback, useEffect, useReducer, useRef } from 'react';
import { sample } from '../data/sample.js';
import { api, openDebateSocket } from '../api.js';
import { speech, isSpeechSupported } from '../utils/speech.js';

export const AGENTS = {
  advocate: { label: 'Advocate', tone: 'teal', side: 'left', short: 'Adv', doing: 'Advocate is speaking' },
  critic: { label: 'Critic', tone: 'coral', side: 'right', short: 'Cri', doing: 'Critic is speaking' },
  evidence: { label: 'Evidence', tone: 'blue', side: 'left', short: 'Evi', doing: 'Evidence Agent is checking claims' },
  risk: { label: 'Risk', tone: 'purple', side: 'right', short: 'Risk', doing: 'Risk Analyst is speaking' },
};
const SCORE_ORDER = ['advocate', 'critic', 'evidence', 'risk'];

const emptyVerdict = { answer: '...', summary: 'Waiting for the judge.', confidence: 0, note: '' };
const zeroScores = SCORE_ORDER.map((k) => ({ label: AGENTS[k].short, tone: AGENTS[k].tone, value: 0 }));
const zeroUsage = { tokens: '0', cost: '$0.00', time: '0s' };

export function formatUsage(u) {
  return {
    tokens: Math.round(u.tokens || 0).toLocaleString('en-US'),
    cost: `$${Number(u.cost || 0).toFixed(2)}`,
    time: `${Math.round(u.seconds || 0)}s`,
  };
}

function scoresFrom(values) {
  return SCORE_ORDER.map((k) => ({
    label: AGENTS[k].short,
    tone: AGENTS[k].tone,
    value: Math.max(0, Math.min(1, (values?.[k] ?? 0) / 10)),
  }));
}

const voiceNote = () => (isSpeechSupported() ? '' : '  (Voice not supported)');

const initialState = () => ({
  phase: 'sample', // sample | running | done | stopped | error
  currentDebateId: null,
  question: sample.question,
  rounds: sample.rounds,
  modelId: 'auto',
  messages: sample.messages.map((m, i) => ({ ...m, id: `sample-${i}` })),
  status: isSpeechSupported() ? sample.status : 'Voice not supported in this browser.',
  statusKind: 'info',
  verdict: sample.verdict,
  scores: sample.scores,
  usage: sample.usage,
  totalRounds: sample.rounds,
});

function messageFor(agent, round, text = '') {
  const a = AGENTS[agent];
  return { id: `${round}-${agent}`, agent: a.label, tone: a.tone, side: a.side, text };
}

function applyEvent(s, e) {
  const vn = voiceNote();
  switch (e.type) {
    case 'debate.started':
      return { ...s, totalRounds: e.rounds, verdict: { ...s.verdict, note: e.note || '' } };
    case 'turn.started':
      return {
        ...s,
        messages: [...s.messages, messageFor(e.agent, e.round)],
        status: `Round ${e.round} of ${s.totalRounds}  ...  ${AGENTS[e.agent].doing}${vn}`,
        statusKind: 'info',
      };
    case 'turn.completed': {
      const id = `${e.round}-${e.agent}`;
      const exists = s.messages.some((m) => m.id === id);
      return {
        ...s,
        messages: exists
          ? s.messages.map((m) => (m.id === id ? { ...m, text: e.text } : m))
          : [...s.messages, messageFor(e.agent, e.round, e.text)],
      };
    }
    case 'usage.updated':
      return { ...s, usage: formatUsage(e) };
    case 'judge.started':
      return { ...s, status: `Round ${s.totalRounds} of ${s.totalRounds}  ...  Judge is scoring${vn}`, statusKind: 'info' };
    case 'verdict.ready':
      return {
        ...s,
        verdict: { answer: e.answer, summary: e.summary, confidence: e.confidence, note: e.note || '' },
        scores: scoresFrom(e.scores),
      };
    case 'debate.completed':
      return e.status === 'done'
        ? { ...s, phase: 'done', status: `Round ${s.totalRounds} of ${s.totalRounds}  ...  Debate complete${vn}`, statusKind: 'info' }
        : { ...s, phase: 'stopped', status: 'Stopped.', statusKind: 'info' };
    case 'debate.error':
      return { ...s, phase: 'error', status: e.message, statusKind: 'error' };
    default:
      return s;
  }
}

function reducer(s, a) {
  switch (a.type) {
    case 'question':
      return { ...s, question: a.value };
    case 'rounds':
      return { ...s, rounds: a.value };
    case 'model':
      return { ...s, modelId: a.value };
    case 'set_debate_id':
      return { ...s, currentDebateId: a.id };
    case 'notice':
      return { ...s, status: a.text, statusKind: 'error' };
    case 'start':
      return {
        ...s,
        phase: 'running',
        messages: [],
        status: 'Connecting...',
        statusKind: 'info',
        verdict: emptyVerdict,
        scores: zeroScores,
        usage: zeroUsage,
        totalRounds: s.rounds,
      };
    case 'stopping':
      return { ...s, status: 'Stopping...', statusKind: 'info' };
    case 'event':
      return applyEvent(s, a.event);
    case 'deltas':
      return { ...s, messages: s.messages.map((m) => (a.map[m.id] ? { ...m, text: m.text + a.map[m.id] } : m)) };
    case 'loaded':
      return { ...s, ...a.state };
    default:
      return s;
  }
}

export function useDebate() {
  const [state, dispatch] = useReducer(reducer, undefined, initialState);
  const stateRef = useRef(state);
  stateRef.current = state;
  const wsRef = useRef(null);

  useEffect(() => {
    const onUnload = () => speech.cancel();
    window.addEventListener('beforeunload', onUnload);
    return () => {
      window.removeEventListener('beforeunload', onUnload);
      speech.cancel();
      if (wsRef.current) wsRef.current.close();
    };
  }, []);

  const connect = useCallback((id) => {
    const buffer = {};
    let raf = 0;
    let finished = false;
    const flush = () => {
      raf = 0;
      const keys = Object.keys(buffer);
      if (!keys.length) return;
      const map = {};
      keys.forEach((k) => {
        map[k] = buffer[k];
        delete buffer[k];
      });
      dispatch({ type: 'deltas', map });
    };

    const ws = openDebateSocket(id);
    wsRef.current = ws;
    ws.onmessage = (msg) => {
      const e = JSON.parse(msg.data);
      if (e.type === 'turn.delta') {
        speech.onTurnDelta(e.agent, e.round, e.text);
        const key = `${e.round}-${e.agent}`;
        buffer[key] = (buffer[key] || '') + e.text;
        if (!raf) raf = requestAnimationFrame(flush); // at most one repaint per frame: no lag
        return;
      }
      if (e.type === 'turn.started') {
        speech.onTurnStarted(e.agent, e.round);
      }
      if (e.type === 'turn.completed') {
        speech.onTurnCompleted(e.agent, e.round, e.text);
      }
      if (e.type === 'verdict.ready') {
        speech.onVerdictReady(e);
      }
      if (raf) {
        cancelAnimationFrame(raf);
        flush(); // keep events in order
      }
      if (e.type === 'debate.completed' || e.type === 'debate.error') {
        finished = true;
        if (e.status === 'cancelled' || e.type === 'debate.error') {
          speech.cancel();
        }
      }
      dispatch({ type: 'event', event: e });
    };
    ws.onclose = () => {
      if (raf) cancelAnimationFrame(raf);
      if (!finished) dispatch({ type: 'event', event: { type: 'debate.error', message: 'Connection lost. Please try again.' } });
      if (wsRef.current === ws) wsRef.current = null;
    };
  }, []);

  const stop = useCallback(() => {
    speech.cancel();
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'cancel' }));
      dispatch({ type: 'stopping' });
    }
  }, []);

  const start = useCallback(async () => {
    speech.cancel();
    const s = stateRef.current;
    if (s.phase === 'running') {
      stop();
      return;
    }
    const question = s.question.trim();
    if (question.length < 10) {
      dispatch({ type: 'notice', text: 'Please type a question of at least 10 characters.' });
      return;
    }
    dispatch({ type: 'start' });
    try {
      const { id } = await api.createDebate({ question, rounds: s.rounds, model: s.modelId });
      dispatch({ type: 'set_debate_id', id });
      connect(id);
    } catch (err) {
      dispatch({ type: 'event', event: { type: 'debate.error', message: err.message } });
    }
  }, [connect, stop]);

  const openDebate = useCallback(async (id) => {
    speech.cancel();
    const d = await api.getDebate(id);
    const last = d.messages.length ? d.messages[d.messages.length - 1].round : d.rounds;
    const v = d.verdict;
    dispatch({
      type: 'loaded',
      state: {
        phase: d.status === 'done' ? 'done' : 'stopped',
        currentDebateId: id,
        question: d.question,
        rounds: d.rounds,
        totalRounds: d.rounds,
        messages: d.messages.map((m) => messageFor(m.agent, m.round, m.text)),
        status: d.status === 'done' ? `Round ${last} of ${d.rounds}  ...  Debate complete` : 'Stopped.',
        statusKind: 'info',
        verdict: v
          ? { answer: v.answer, summary: v.summary, confidence: v.confidence, note: v.note || d.note || '' }
          : emptyVerdict,
        scores: v ? scoresFrom(v.scores) : zeroScores,
        usage: formatUsage({ tokens: d.tokens, cost: d.cost, seconds: d.seconds }),
      },
    });
  }, []);

  const actions = {
    setQuestion: (value) => dispatch({ type: 'question', value }),
    setRounds: (value) => dispatch({ type: 'rounds', value }),
    setModel: (value) => dispatch({ type: 'model', value }),
  };

  return { state, actions, start, openDebate };
}
