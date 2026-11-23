export default function Tabs({ tabs, active, onChange }) {
  return (
    <div className="absolute left-[24px] top-[56px] flex gap-[12px]">
      {tabs.map((t) =>
        t === active ? (
          <button
            key={t}
            type="button"
            onClick={() => onChange(t)}
            className="flex h-[32px] w-[124px] cursor-pointer items-center justify-center rounded-[8px] border-0 bg-navy p-0 text-[15.6px] font-bold text-white"
          >
            {t}
          </button>
        ) : (
          <button
            key={t}
            type="button"
            onClick={() => onChange(t)}
            className="flex h-[32px] w-[124px] cursor-pointer items-center justify-center rounded-[8px] border-[1.6px] border-line bg-white p-0 text-[15.6px] text-muted hover:bg-panel"
          >
            {t}
          </button>
        )
      )}
    </div>
  );
}
