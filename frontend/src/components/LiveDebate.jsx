import { useEffect, useRef } from 'react';
import Message from './Message.jsx';

export default function LiveDebate({ messages, status, statusKind }) {
  const scroller = useRef(null);
  const stick = useRef(true);

  const onScroll = () => {
    const el = scroller.current;
    stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 28;
  };

  // Follow the newest text, unless the user scrolled up to read.
  useEffect(() => {
    const el = scroller.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [messages]);

  // A new debate always starts at the top again.
  useEffect(() => {
    if (messages.length <= 1) stick.current = true;
  }, [messages.length]);

  return (
    <div className="absolute left-[24px] top-[172px] h-[412px] w-[624px] rounded-[12px] border-[1.6px] border-dashed border-line">
      <div className="absolute left-[16px] top-[10px] text-[14px] font-bold leading-[16px] text-muted">LIVE DEBATE</div>
      <div
        ref={scroller}
        onScroll={onScroll}
        className="thin-scroll absolute left-[14.4px] right-[8px] top-[38.4px] h-[337px] overflow-y-auto pr-[6.4px]"
      >
        <div className="flex flex-col gap-[14px]">
          {messages.map((m) => (
            <Message key={m.id} agent={m.agent} tone={m.tone} side={m.side} text={m.text} />
          ))}
        </div>
      </div>
      <div
        className={`absolute left-[16px] right-[16px] top-[385px] overflow-hidden text-[15px] italic leading-[17px] ${
          statusKind === 'error' ? 'text-coral' : 'text-muted'
        }`}
        style={{ whiteSpace: 'pre', textOverflow: 'ellipsis' }}
        title={status}
      >
        {status}
      </div>
    </div>
  );
}
