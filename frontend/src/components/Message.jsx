import { tones } from './tones.js';

export default function Message({ agent, tone, side, text }) {
  const t = tones[tone];
  return (
    <div
      className={`min-h-[72px] w-[428px] shrink-0 rounded-[12px] border-[1.8px] pb-[12px] pl-[16px] pr-[16px] pt-[13px] ${t.border} ${t.bg} ${
        side === 'right' ? 'self-end' : 'self-start'
      }`}
    >
      <div className={`text-[15.6px] font-bold leading-[18px] ${t.text}`}>{agent}</div>
      <div className="mt-[7px] min-h-[18px] break-words text-[15.6px] leading-[18px] text-ink">{text}</div>
    </div>
  );
}
