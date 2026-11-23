const STORAGE_KEY = 'agent_courtroom_voice';

export const ROLE_CONFIG = {
  advocate: { name: 'Advocate', pitch: 1.05, rate: 1.0 },
  critic: { name: 'Critic', pitch: 0.9, rate: 1.05 },
  risk: { name: 'Risk Analyst', pitch: 0.95, rate: 0.95 },
  evidence: { name: 'Evidence Agent', pitch: 1.1, rate: 1.0 },
  judge: { name: 'Judge', pitch: 0.85, rate: 0.9 },
};

export function isSpeechSupported() {
  return (
    typeof window !== 'undefined' &&
    'speechSynthesis' in window &&
    'SpeechSynthesisUtterance' in window &&
    typeof window.speechSynthesis.speak === 'function'
  );
}

export function cleanText(text) {
  if (!text) return '';
  let t = String(text);
  // Remove role tags/prefixes like "Advocate:", "[ROLE:critic]"
  t = t.replace(/\[ROLE:\w+\]/gi, '');
  t = t.replace(/^(advocate|critic|risk analyst|risk|evidence agent|evidence|judge)\s*[:\-]\s*/i, '');
  // Replace percentages: "80%" -> "80 percent"
  t = t.replace(/(\d+(?:\.\d+)?)\s*%/g, '$1 percent');
  t = t.replace(/%/g, ' percent');
  // Remove markdown symbols: bold/italic, backticks, headings, blockquotes
  t = t.replace(/[*_~`#]+/g, '');
  t = t.replace(/^\s*[-*•>]\s+/gm, '');
  // Clean whitespace
  t = t.replace(/\s+/g, ' ').trim();
  return t;
}

export function cleanVerdictText(verdict) {
  if (!verdict) return '';
  const ans = cleanText(verdict.answer || '').replace(/[.!?]+$/, '');
  const summ = cleanText(verdict.summary || '').replace(/[.!?]+$/, '');
  const conf = Math.round(Number(verdict.confidence) || 0);
  return `Verdict: ${ans}. ${summ}. Confidence ${conf} percent.`;
}

let voiceMap = {};

export function updateVoiceMap() {
  if (!isSpeechSupported()) return;
  const allVoices = window.speechSynthesis.getVoices() || [];
  if (!allVoices.length) return;

  const enVoices = allVoices.filter((v) => v.lang && /^en([-_]|$)/i.test(v.lang));
  const pool = enVoices.length ? enVoices : allVoices;

  const rank = (v) => {
    const lang = (v.lang || '').toLowerCase().replace('_', '-');
    if (lang.startsWith('en-in')) return 1;
    if (lang.startsWith('en-gb')) return 2;
    if (lang.startsWith('en-us')) return 3;
    if (lang.startsWith('en')) return 4;
    return 5;
  };

  const sorted = [...pool].sort((a, b) => rank(a) - rank(b));
  const roles = ['advocate', 'critic', 'risk', 'evidence', 'judge'];

  voiceMap = {};
  roles.forEach((role, i) => {
    voiceMap[role] = sorted[i % sorted.length];
  });
}

// Try loading voices immediately and on voiceschanged event
if (isSpeechSupported()) {
  updateVoiceMap();
  if (typeof window.speechSynthesis.addEventListener === 'function') {
    window.speechSynthesis.addEventListener('voiceschanged', updateVoiceMap);
  } else {
    window.speechSynthesis.onvoiceschanged = updateVoiceMap;
  }
}

class SpeechController {
  constructor() {
    this.enabled = this.loadEnabled();
    this.currentAgent = null;
    this.currentRound = null;
    this.turnBuffer = '';
    this.isFirstSentence = true;
    this.activeUtterances = new Set();
  }

  loadEnabled() {
    if (!isSpeechSupported()) return false;
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      return stored === null ? true : stored !== 'false';
    } catch {
      return true;
    }
  }

  setEnabled(val) {
    this.enabled = !!val;
    try {
      localStorage.setItem(STORAGE_KEY, this.enabled ? 'true' : 'false');
    } catch {}
    if (!this.enabled) {
      this.cancel();
    }
  }

  cancel() {
    this.turnBuffer = '';
    this.currentAgent = null;
    this.currentRound = null;
    this.isFirstSentence = true;
    this.activeUtterances.clear();
    if (isSpeechSupported()) {
      try {
        window.speechSynthesis.cancel();
      } catch {}
    }
  }

  enqueue(agent, sentence) {
    if (!this.enabled || !isSpeechSupported()) return;
    const cleaned = cleanText(sentence);
    if (!cleaned) return;

    const roleConfig = ROLE_CONFIG[agent] || ROLE_CONFIG.advocate;
    let spokenText = cleaned;
    if (this.isFirstSentence && agent !== 'judge') {
      spokenText = `${roleConfig.name}: ${cleaned}`;
      this.isFirstSentence = false;
    }

    try {
      updateVoiceMap();
      const u = new SpeechSynthesisUtterance(spokenText);
      const voice = voiceMap[agent];
      if (voice) u.voice = voice;
      u.pitch = roleConfig.pitch;
      u.rate = roleConfig.rate;
      u.lang = voice ? voice.lang : 'en-US';
      u.speaker = roleConfig.name;

      this.activeUtterances.add(u);
      u.onend = () => this.activeUtterances.delete(u);
      u.onerror = () => this.activeUtterances.delete(u);

      window.speechSynthesis.speak(u);
    } catch (err) {
      console.warn('speechSynthesis.speak error:', err);
    }
  }

  onTurnStarted(agent, round) {
    if (!this.enabled) return;
    this.flushBuffer();
    this.currentAgent = agent;
    this.currentRound = round;
    this.turnBuffer = '';
    this.isFirstSentence = true;
  }

  onTurnDelta(agent, round, text) {
    if (!this.enabled) return;
    if (this.currentAgent !== agent || this.currentRound !== round) {
      this.onTurnStarted(agent, round);
    }
    this.turnBuffer += text;

    // Extract complete sentences ending with [.!?] followed by whitespace
    const regex = /^([\s\S]*?[.!?]+)(?=\s+)([\s\S]*)$/;
    while (true) {
      const m = this.turnBuffer.match(regex);
      if (!m) break;
      const sentence = m[1].trim();
      this.turnBuffer = m[2].trimStart();
      if (sentence) {
        this.enqueue(agent, sentence);
      }
    }
  }

  onTurnCompleted(agent, round, finalText) {
    if (!this.enabled) return;
    this.flushBuffer();
  }

  flushBuffer() {
    if (this.currentAgent && this.turnBuffer.trim()) {
      const remaining = this.turnBuffer.trim();
      this.turnBuffer = '';
      this.enqueue(this.currentAgent, remaining);
    }
  }

  onVerdictReady(verdict) {
    if (!this.enabled) return;
    this.flushBuffer();
    const verdictText = cleanVerdictText(verdict);
    if (verdictText) {
      this.enqueue('judge', verdictText);
    }
  }
}

export const speech = new SpeechController();
