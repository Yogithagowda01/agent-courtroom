// All text and numbers shown in the prototype live here.
// When the backend is ready, replace this file with live data from the API.
export const sample = {
  title: 'Agent Courtroom',
  tabs: ['Debate', 'History', 'Benchmarks', 'Report'],
  activeTab: 'Debate',
  question: 'Should a 5-person startup use microservices?',
  rounds: 3,
  model: 'Auto',
  messages: [
    { agent: 'Advocate', tone: 'teal', side: 'left', text: 'Independent deploys and per-service scaling.' },
    { agent: 'Critic', tone: 'coral', side: 'right', text: 'Five engineers cannot afford the infra overhead.' },
    { agent: 'Evidence', tone: 'blue', side: 'left', text: 'Scaling-needs claim is unsourced. Flagged.' },
    { agent: 'Risk', tone: 'purple', side: 'right', text: 'Extra monitoring and on-call load.' },
  ],
  status: 'Round 2 of 3  ...  Judge is scoring',
  verdict: {
    answer: 'Not now',
    summary: 'Start with a modular monolith.',
    confidence: 80,
    note: 'sample values shown',
  },
  scores: [
    { label: 'Adv', tone: 'teal', value: 0.62 },
    { label: 'Cri', tone: 'coral', value: 0.82 },
    { label: 'Evi', tone: 'blue', value: 0.7 },
    { label: 'Risk', tone: 'purple', value: 0.55 },
  ],
  usage: { tokens: '4,210', cost: '$0.03', time: '18s' },
};
