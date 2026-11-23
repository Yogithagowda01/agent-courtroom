const dots = [
  { left: 28, color: '#F87171' },
  { left: 54, color: '#FBBF24' },
  { left: 80, color: '#34D399' },
];

export default function TitleBar({ title, voiceEnabled = true, onToggleVoice, voiceSupported = true }) {
  return (
    <div className="absolute left-0 right-0 top-0 h-[44px] rounded-t-[16px] bg-bar">
      {dots.map((d) => (
        <span
          key={d.left}
          className="absolute top-[15px] h-[14.4px] w-[14.4px] rounded-full"
          style={{ left: d.left - 7.2, background: d.color }}
        />
      ))}
      <div className="flex h-full items-center justify-center text-[17px] font-bold text-ink">{title}</div>
      <button
        type="button"
        disabled={!voiceSupported}
        onClick={onToggleVoice}
        title={voiceSupported ? (voiceEnabled ? 'Turn voice off' : 'Turn voice on') : 'Voice not supported in this browser'}
        className={`absolute right-[20px] top-[12px] border-0 bg-transparent text-[13.5px] font-medium leading-[20px] transition-colors ${
          !voiceSupported
            ? 'cursor-not-allowed text-muted/50'
            : 'cursor-pointer text-muted hover:text-ink'
        }`}
      >
        Voice: {voiceSupported ? (voiceEnabled ? 'On' : 'Off') : 'Off'}
      </button>
    </div>
  );
}
