import { useEffect, useState } from 'react';
import Window from './components/Window.jsx';
import TitleBar from './components/TitleBar.jsx';
import Tabs from './components/Tabs.jsx';
import QuestionBar from './components/QuestionBar.jsx';
import LiveDebate from './components/LiveDebate.jsx';
import VerdictCard from './components/VerdictCard.jsx';
import ScoresCard from './components/ScoresCard.jsx';
import UsageCard from './components/UsageCard.jsx';
import HistoryPanel from './components/HistoryPanel.jsx';
import BenchmarksPanel from './components/BenchmarksPanel.jsx';
import ReportPanel from './components/ReportPanel.jsx';
import Badge from './components/Badge.jsx';
import { sample } from './data/sample.js';
import { SHOW_ANNOTATIONS } from './config.js';
import { api } from './api.js';
import { useDebate } from './hooks/useDebate.js';
import { useFitScale } from './hooks/useFitScale.js';
import { speech, isSpeechSupported } from './utils/speech.js';

const WIDTH = 1022;
const HEIGHT = 604;

export default function App() {
  const { state, actions, start, openDebate } = useDebate();
  const [tab, setTab] = useState(sample.activeTab);
  const [models, setModels] = useState([{ id: 'auto', label: 'Auto' }]);
  const [voiceEnabled, setVoiceEnabled] = useState(() => speech.enabled);
  const voiceSupported = isSpeechSupported();
  const scale = useFitScale(WIDTH, HEIGHT);
  const running = state.phase === 'running';

  const toggleVoice = () => {
    const next = !voiceEnabled;
    setVoiceEnabled(next);
    speech.setEnabled(next);
  };

  // Load the model list now, and again whenever the window regains focus (e.g. after starting Ollama).
  useEffect(() => {
    const load = () => api.models().then(setModels).catch(() => {});
    load();
    window.addEventListener('focus', load);
    return () => window.removeEventListener('focus', load);
  }, []);

  const model = models.find((m) => m.id === state.modelId) || models[0];

  const nextModel = () => {
    const i = models.findIndex((m) => m.id === model.id);
    actions.setModel(models[(i + 1) % models.length].id);
  };

  const open = async (id) => {
    await openDebate(id);
    setTab('Debate');
  };

  return (
    <main className="flex min-h-screen items-center justify-center overflow-hidden">
      <div style={{ width: WIDTH * scale, height: HEIGHT * scale }}>
        <div style={{ width: WIDTH, height: HEIGHT, transform: `scale(${scale})`, transformOrigin: 'top left' }}>
          <Window>
            <TitleBar
              title={sample.title}
              voiceEnabled={voiceEnabled}
              onToggleVoice={toggleVoice}
              voiceSupported={voiceSupported}
            />
            <Tabs tabs={sample.tabs} active={tab} onChange={setTab} />

            {tab === 'Debate' && (
              <>
                <QuestionBar
                  question={state.question}
                  rounds={state.rounds}
                  modelLabel={model.label}
                  running={running}
                  onQuestion={actions.setQuestion}
                  onRounds={() => actions.setRounds((state.rounds % 5) + 1)}
                  onModel={nextModel}
                  onStart={start}
                />
                <LiveDebate messages={state.messages} status={state.status} statusKind={state.statusKind} />
                <div className="absolute left-[668px] top-[172px] h-[412px] w-[330px]">
                  <VerdictCard verdict={state.verdict} />
                  <ScoresCard scores={state.scores} />
                  <UsageCard usage={state.usage} />
                </div>
                {SHOW_ANNOTATIONS && (
                  <>
                    <Badge n={1} left={-2} top={114} />
                    <Badge n={2} left={-2} top={174} />
                    <Badge n={3} left={646} top={174} />
                    <Badge n={4} left={646} top={366} />
                  </>
                )}
              </>
            )}
            {tab === 'History' && <HistoryPanel onOpen={open} />}
            {tab === 'Benchmarks' && <BenchmarksPanel modelId={model.id} modelLabel={model.label} />}
            {tab === 'Report' && <ReportPanel debateId={state.currentDebateId} phase={state.phase} />}
          </Window>
        </div>
      </div>
    </main>
  );
}
