import { tones } from './tones.js';

export default function ScoresCard({ scores }) {
  return (
    <div className="absolute left-0 top-[192px] h-[132px] w-full rounded-[12px] bg-panel">
      <div className="absolute left-[16px] top-[12px] text-[14.4px] font-bold leading-[16px] text-muted">ARGUMENT SCORES</div>
      {scores.map((s, i) => (
        <div key={s.label} className="absolute left-[16px] flex h-[12px] items-center" style={{ top: 44 + i * 21 }}>
          <div className="w-[48px] text-[14px] leading-[12px] text-ink">{s.label}</div>
          <div className="h-[12px] w-[242px] rounded-[4px] bg-white">
            <div
              className={`h-full rounded-[4px] transition-[width] duration-500 ${tones[s.tone].fill}`}
              style={{ width: `${s.value * 100}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
