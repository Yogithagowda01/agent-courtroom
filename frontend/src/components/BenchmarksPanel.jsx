import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api.js';
import { tones } from './tones.js';

const METHOD_TONE = { direct: 'coral', step: 'blue', majority: 'purple', courtroom: 'teal' };
const FALLBACK = [
  { id: 'direct', label: 'Direct answer', sub: '1 call per question' },
  { id: 'step', label: 'Step by step', sub: '1 call, reasons first' },
  { id: 'majority', label: 'Majority vote', sub: '3 samples, most common wins' },
  { id: 'courtroom', label: 'Agent Courtroom', sub: '3 agents + judge' },
];

export default function BenchmarksPanel({ modelId, modelLabel }) {
  const [info, setInfo] = useState({ run: null, questions: 5, methods: FALLBACK });
  const [error, setError] = useState('');
  const timer = useRef(0);

  const refresh = useCallback(() => {
    return api
      .latestBenchmark()
      .then((d) => {
        setInfo(d);
        return d;
      })
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const running = info.run && info.run.status === 'running';

  useEffect(() => {
    if (!running) return undefined;
    timer.current = setInterval(refresh, 1500);
    return () => clearInterval(timer.current);
  }, [running, refresh]);

  const toggle = async () => {
    setError('');
    try {
      if (running) await api.cancelBenchmark();
      else await api.startBenchmark(modelId);
      await refresh();
    } catch (e) {
      setError(e.message);
    }
  };

  const methods = info.run ? info.run.methods : info.methods.map((m) => ({ ...m, correct: 0, answered: 0, tokens: 0, seconds: 0 }));
  const status = error || (info.run && (info.run.error || info.run.current)) || 'Press Run to compare the four methods.';
  const isError = Boolean(error || (info.run && info.run.error));

  return (
    <div className="absolute left-[24px] top-[104px] h-[480px] w-[974px] rounded-[12px] border-[1.6px] border-dashed border-line">
      <div className="absolute left-[16px] top-[10px] text-[14px] font-bold leading-[16px] text-muted">BENCHMARK: DEBATE VS 3 BASELINES</div>
      <button
        type="button"
        onClick={toggle}
        className="absolute right-[16px] top-[8px] flex h-[32px] w-[140px] cursor-pointer items-center justify-center rounded-[8px] border-0 bg-teal p-0 text-[15.6px] font-bold text-white hover:brightness-95"
      >
        {running ? 'Stop' : 'Run benchmark'}
      </button>
      <div className="absolute left-[16px] right-[170px] top-[44px] truncate text-[14.8px] leading-[16px] text-muted">
        {`Model: ${info.run ? info.run.model : modelLabel}. ${info.questions} maths word problems. Change the model on the Debate tab.`}
      </div>

      <div className="absolute left-[14.4px] right-[14.4px] top-[78px] flex flex-col gap-[14px]">
        {methods.map((m) => {
          const t = tones[METHOD_TONE[m.id]];
          const pct = m.answered ? Math.round((m.correct / m.answered) * 100) : 0;
          return (
            <div key={m.id} className={`relative h-[72px] rounded-[12px] border-[1.8px] ${t.border} ${t.bg}`}>
              <div className={`absolute left-[16px] top-[13px] text-[15.6px] font-bold leading-[18px] ${t.text}`}>{m.label}</div>
              <div className="absolute left-[16px] top-[38px] text-[14px] leading-[18px] text-ink">{m.sub}</div>
              <div className="absolute left-[270px] top-[28px] h-[16px] w-[360px] rounded-[6px] bg-white">
                <div className={`h-full rounded-[6px] transition-[width] duration-500 ${t.fill}`} style={{ width: `${pct}%` }} />
              </div>
              <div className="absolute left-[650px] top-[26px] text-[15.6px] font-bold leading-[20px] text-ink">
                {m.answered ? `${m.correct}/${m.answered}   ${pct}%` : '-'}
              </div>
              <div className="absolute right-[16px] top-[26px] text-[14.8px] leading-[20px] text-muted">
                {m.answered ? `${Math.round(m.tokens).toLocaleString('en-US')} tokens   ${Math.round(m.seconds)}s` : ''}
              </div>
            </div>
          );
        })}
      </div>

      <div
        className={`absolute left-[16px] right-[16px] top-[440px] overflow-hidden text-[15px] italic leading-[17px] ${isError ? 'text-coral' : 'text-muted'}`}
        style={{ whiteSpace: 'pre', textOverflow: 'ellipsis' }}
        title={status}
      >
        {status}
      </div>
    </div>
  );
}
