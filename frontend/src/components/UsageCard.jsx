export default function UsageCard({ usage }) {
  return (
    <div className="absolute left-0 top-[340px] h-[72px] w-full rounded-[12px] border-[1.6px] border-line bg-white">
      <div className="absolute left-[16px] top-[10px] whitespace-pre text-[14.8px] leading-[16px] text-ink">{`Tokens  ${usage.tokens}`}</div>
      <div className="absolute left-[16px] top-[32px] whitespace-pre text-[14.8px] leading-[16px] text-ink">{`Cost  ${usage.cost}   Time  ${usage.time}`}</div>
    </div>
  );
}
