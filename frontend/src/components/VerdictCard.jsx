export default function VerdictCard({ verdict }) {
  return (
    <div className="absolute left-0 top-0 h-[176px] w-full rounded-[12px] border-[2px] border-gold bg-gold-light">
      <div className="absolute left-[16px] top-[12px] text-[15.2px] font-bold leading-[16px] text-gold">JUDGE VERDICT</div>
      <div className="absolute left-[16px] right-[16px] top-[36px] truncate text-[26px] font-bold leading-[28px] text-ink" title={verdict.answer}>
        {verdict.answer}
      </div>
      <div
        className={`absolute left-[16px] right-[16px] top-[72px] overflow-hidden text-ink ${
          verdict.summary.length > 38 ? 'line-clamp-2 max-h-[26px] text-[13px] leading-[13px]' : 'truncate text-[14.8px] leading-[16px]'
        }`}
        title={verdict.summary}
      >
        {verdict.summary}
      </div>
      <div className="absolute left-[16px] top-[101px] text-[14.8px] leading-[16px] text-muted">Confidence</div>
      <div className="absolute right-[16px] top-[101px] text-[15.2px] font-bold leading-[16px] text-ink">{verdict.confidence}%</div>
      <div className="absolute left-[16px] right-[16px] top-[124px] h-[16px] rounded-[6px] bg-white">
        <div
          className="h-full rounded-[6px] bg-gold transition-[width] duration-500"
          style={{ width: `${Math.max(0, Math.min(100, verdict.confidence))}%` }}
        />
      </div>
      <div className="absolute left-[16px] right-[16px] top-[150px] truncate text-[13.6px] italic leading-[16px] text-muted" title={verdict.note}>
        {verdict.note}
      </div>
    </div>
  );
}
