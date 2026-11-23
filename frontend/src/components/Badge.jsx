export default function Badge({ n, left, top }) {
  return (
    <div
      className="absolute z-10 flex h-[28px] w-[28px] items-center justify-center rounded-full bg-navy text-[17px] font-bold leading-none text-white"
      style={{ left, top }}
    >
      {n}
    </div>
  );
}
