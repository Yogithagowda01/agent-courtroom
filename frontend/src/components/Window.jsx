// The app window: fixed 1022 x 604 px frame (the sketch at 2x scale).
export default function Window({ children }) {
  return (
    <div className="relative h-[604px] w-[1022px] rounded-[16px] bg-white">
      {children}
      <div className="pointer-events-none absolute inset-0 rounded-[16px] border-[2.8px] border-ink" />
    </div>
  );
}
