import { useCallback, useEffect, useState } from 'react';
import { api } from '../api.js';

function when(ts) {
  return new Date(ts * 1000).toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

export default function HistoryPanel({ onOpen }) {
  const [items, setItems] = useState(null);
  const [error, setError] = useState('');

  const load = useCallback(() => {
    api
      .listDebates()
      .then((d) => {
        setItems(d);
        setError('');
      })
      .catch((e) => setError(e.message));
  }, []);

  useEffect(load, [load]);

  const remove = async (id) => {
    try {
      await api.deleteDebate(id);
      setItems((list) => list.filter((d) => d.id !== id));
    } catch (e) {
      setError(e.message);
    }
  };

  const open = async (id) => {
    try {
      await onOpen(id);
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div className="absolute left-[24px] top-[104px] h-[480px] w-[974px] rounded-[12px] border-[1.6px] border-dashed border-line">
      <div className="absolute left-[16px] top-[10px] text-[14px] font-bold leading-[16px] text-muted">PAST DEBATES</div>
      <div className="thin-scroll absolute bottom-[14px] left-[14.4px] right-[8px] top-[38.4px] overflow-y-auto pr-[6.4px]">
        {error && <div className="mb-[10px] text-[14.8px] text-coral">{error}</div>}
        {items && items.length === 0 && !error && (
          <div className="mt-[150px] text-center text-[15.6px] text-muted">No debates yet. Run one from the Debate tab.</div>
        )}
        <div className="flex flex-col gap-[12px]">
          {(items || []).map((d) => (
            <div key={d.id} className="flex shrink-0 items-center rounded-[12px] border-[1.8px] border-line bg-white hover:bg-panel">
              <button
                type="button"
                onClick={() => open(d.id)}
                className="min-w-0 flex-1 cursor-pointer border-0 bg-transparent px-[16px] py-[11px] text-left"
              >
                <div className="truncate text-[15.6px] font-bold leading-[20px] text-ink">{d.question}</div>
                <div className="mt-[3px] truncate text-[14px] leading-[18px] text-muted">
                  {[
                    when(d.created_at),
                    d.answer ? `${d.answer} (${d.confidence}%)` : d.status === 'cancelled' ? 'Stopped' : d.status === 'failed' ? 'Failed' : d.status,
                    d.note,
                    `${Math.round(d.tokens || 0).toLocaleString('en-US')} tokens`,
                  ]
                    .filter(Boolean)
                    .join('   |   ')}
                </div>
              </button>
              <button
                type="button"
                onClick={() => remove(d.id)}
                className="mr-[12px] cursor-pointer rounded-[8px] border-0 bg-transparent px-[10px] py-[6px] text-[14px] text-coral hover:bg-coral-light"
              >
                Delete
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
