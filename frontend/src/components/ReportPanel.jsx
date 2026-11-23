import { useCallback, useEffect, useState } from 'react';
import { api } from '../api.js';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, PieChart, Pie } from 'recharts';

export default function ReportPanel({ debateId, phase }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    if (!debateId) {
      setData(null);
      setError('');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const res = await api.getReport(debateId);
      setData(res);
    } catch (err) {
      setError(err.message || 'Failed to generate summary report.');
    } finally {
      setLoading(false);
    }
  }, [debateId]);

  useEffect(() => {
    load();
  }, [debateId, phase, load]);

  const download = (format) => {
    if (!debateId) return;
    const url = api.downloadReportUrl(debateId, format);
    const link = document.createElement('a');
    link.href = url;
    link.download = '';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="absolute left-[24px] top-[104px] h-[480px] w-[974px] rounded-[12px] border-[1.6px] border-dashed border-line bg-white">
      {/* Top Header Bar */}
      <div className="absolute left-[16px] right-[16px] top-[10px] flex items-center justify-between">
        <div className="text-[14px] font-bold leading-[16px] text-muted">DEBATE SUMMARY REPORT</div>
        {debateId && data && (
          <div className="flex items-center gap-[10px]">
            <button
              type="button"
              onClick={() => download('docx')}
              className="flex h-[30px] cursor-pointer items-center justify-center rounded-[8px] border-0 bg-teal px-[12px] text-[13.5px] font-bold text-white hover:brightness-95"
            >
              Download Word (.docx)
            </button>
            <button
              type="button"
              onClick={() => download('pdf')}
              className="flex h-[30px] cursor-pointer items-center justify-center rounded-[8px] border-0 bg-teal px-[12px] text-[13.5px] font-bold text-white hover:brightness-95"
            >
              Download PDF
            </button>
          </div>
        )}
      </div>

      {/* Main Content Area */}
      <div className="thin-scroll absolute bottom-[12px] left-[14px] right-[8px] top-[46px] overflow-y-auto pr-[8px]">
        {!debateId && (
          <div className="mt-[160px] text-center text-[15.6px] text-muted">
            Run or open a debate first.
          </div>
        )}

        {loading && (
          <div className="mt-[160px] text-center text-[15.6px] font-medium text-teal animate-pulse">
            Writing report...
          </div>
        )}

        {error && !loading && (
          <div className="mt-[140px] text-center">
            <div className="text-[15px] font-medium text-coral">{error}</div>
            <button
              type="button"
              onClick={load}
              className="mt-[12px] inline-flex h-[30px] cursor-pointer items-center justify-center rounded-[8px] border-0 bg-teal px-[14px] text-[13px] font-bold text-white hover:brightness-95"
            >
              Retry
            </button>
          </div>
        )}

        {data && !loading && (
          <div className="flex flex-col gap-[14px] pb-[16px]">
            {/* Question & Meta Banner */}
            <div className="rounded-[10px] border-[1.6px] border-line bg-panel p-[14px]">
              <div className="text-[17px] font-bold leading-[22px] text-ink">{data.question}</div>
              <div className="mt-[6px] flex flex-wrap gap-x-[16px] text-[13px] text-muted">
                <span>Date: {data.date}</span>
                <span>Rounds: {data.rounds}</span>
                <span>Debater Model: {data.model}</span>
                <span>Judge Model: {data.judge_model}</span>
                <span>Tokens: {data.usage?.tokens?.toLocaleString()}</span>
              </div>
            </div>

            {/* Verdict and Executive Summary Grid */}
            <div className="grid grid-cols-3 gap-[12px]">
              {/* Verdict Card */}
              <div className="col-span-1 rounded-[10px] border-[1.8px] border-gold bg-gold-light p-[12px]">
                <div className="text-[12.5px] font-bold text-gold">FINAL VERDICT</div>
                <div className="mt-[4px] text-[20px] font-bold text-ink">{data.verdict?.answer}</div>
                <div className="mt-[4px] text-[13.5px] leading-[18px] text-ink">{data.verdict?.summary}</div>
                <div className="mt-[10px] flex items-center justify-between text-[12.5px] text-muted">
                  <span>Confidence</span>
                  <span className="font-bold text-ink">{data.verdict?.confidence}%</span>
                </div>
                <div className="mt-[4px] h-[10px] w-full rounded-[4px] bg-white">
                  <div
                    className="h-full rounded-[4px] bg-gold"
                    style={{ width: `${Math.max(0, Math.min(100, data.verdict?.confidence || 0))}%` }}
                  />
                </div>
              </div>

              {/* Executive Summary Card */}
              <div className="col-span-2 rounded-[10px] border-[1.6px] border-line bg-white p-[12px]">
                <div className="text-[13px] font-bold text-navy">EXECUTIVE SUMMARY</div>
                <div className="mt-[6px] text-[13.8px] leading-[20px] text-ink">
                  {data.memo?.executive_summary}
                </div>
              </div>
            </div>

            {/* 4 Charts Grid */}
            <div className="rounded-[10px] border-[1.6px] border-line bg-white p-[12px]">
              <div className="mb-[10px] text-[13px] font-bold text-navy">ANALYSIS & METRICS</div>
              <div className="grid grid-cols-2 gap-[12px]">
                {/* Chart 1: Argument Scores */}
                <div className="rounded-[8px] border border-line bg-panel p-[10px]">
                  <div className="mb-[6px] text-[12px] font-bold text-navy">Argument Scores by Agent (0-10)</div>
                  <div className="h-[130px] w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={data.charts?.scores} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                        <XAxis dataKey="agent" tick={{ fontSize: 11, fill: '#1F2937' }} />
                        <YAxis domain={[0, 10]} ticks={[0, 2.5, 5, 7.5, 10]} tick={{ fontSize: 10, fill: '#6B7280' }} />
                        <Tooltip />
                        <Bar dataKey="score" radius={[4, 4, 0, 0]}>
                          {(data.charts?.scores || []).map((entry, index) => (
                            <Cell key={`cell-score-${index}`} fill={entry.color} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>

                {/* Chart 2: Confidence Meter */}
                <div className="rounded-[8px] border border-line bg-panel p-[10px]">
                  <div className="mb-[6px] text-[12px] font-bold text-navy">
                    Judge Confidence Meter ({data.charts?.confidence?.confidence}%)
                  </div>
                  <div className="flex h-[130px] flex-col justify-center px-[10px]">
                    <div className="flex items-center justify-between text-[12px] font-semibold text-ink">
                      <span>0%</span>
                      <span className="text-[15px] font-bold text-gold">{data.charts?.confidence?.confidence}%</span>
                      <span>100%</span>
                    </div>
                    <div className="mt-[8px] h-[22px] w-full rounded-[6px] border border-line bg-white p-[2px]">
                      <div
                        className="h-full rounded-[4px] bg-gold transition-all duration-500"
                        style={{ width: `${data.charts?.confidence?.confidence || 0}%` }}
                      />
                    </div>
                    <div className="mt-[10px] text-center text-[11.5px] italic text-muted">
                      Estimated certainty based on evidence and counter-arguments
                    </div>
                  </div>
                </div>

                {/* Chart 3: Evidence Check Donut */}
                <div className="rounded-[8px] border border-line bg-panel p-[10px]">
                  <div className="mb-[6px] text-[12px] font-bold text-navy">Evidence Check Results</div>
                  <div className="flex h-[130px] items-center">
                    <div className="h-full w-[140px]">
                      <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                          <Pie
                            data={data.charts?.evidence}
                            dataKey="value"
                            nameKey="label"
                            innerRadius={28}
                            outerRadius={48}
                            paddingAngle={3}
                          >
                            {(data.charts?.evidence || []).map((entry, index) => (
                              <Cell key={`cell-evi-${index}`} fill={entry.color} />
                            ))}
                          </Pie>
                          <Tooltip />
                        </PieChart>
                      </ResponsiveContainer>
                    </div>
                    <div className="flex flex-1 flex-col gap-[4px] pl-[10px] text-[11.5px]">
                      {(data.charts?.evidence || []).map((item) => (
                        <div key={item.label} className="flex items-center justify-between">
                          <span className="flex items-center gap-[6px]">
                            <span className="inline-block h-[8px] w-[8px] rounded-full" style={{ backgroundColor: item.color }} />
                            <span className="text-ink">{item.label}</span>
                          </span>
                          <span className="font-bold text-ink">{item.value}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Chart 4: Token Usage by Agent */}
                <div className="rounded-[8px] border border-line bg-panel p-[10px]">
                  <div className="mb-[6px] text-[12px] font-bold text-navy">Tokens Used by Each Agent</div>
                  <div className="h-[130px] w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={data.charts?.tokens} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                        <XAxis dataKey="agent" tick={{ fontSize: 11, fill: '#1F2937' }} />
                        <YAxis tick={{ fontSize: 10, fill: '#6B7280' }} />
                        <Tooltip />
                        <Bar dataKey="tokens" radius={[4, 4, 0, 0]}>
                          {(data.charts?.tokens || []).map((entry, index) => (
                            <Cell key={`cell-tok-${index}`} fill={entry.color} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              </div>
            </div>

            {/* Arguments For and Against */}
            <div className="grid grid-cols-2 gap-[12px]">
              <div className="rounded-[10px] border-[1.6px] border-teal bg-teal-light p-[12px]">
                <div className="text-[13px] font-bold text-teal">ARGUMENTS FOR (Advocate)</div>
                <ul className="mt-[6px] flex flex-col gap-[4px] pl-[16px] text-[13px] leading-[18px] text-ink list-disc">
                  {(data.memo?.arguments_for || []).map((item, idx) => (
                    <li key={idx}>{item}</li>
                  ))}
                </ul>
              </div>

              <div className="rounded-[10px] border-[1.6px] border-coral bg-coral-light p-[12px]">
                <div className="text-[13px] font-bold text-coral">ARGUMENTS AGAINST (Critic)</div>
                <ul className="mt-[6px] flex flex-col gap-[4px] pl-[16px] text-[13px] leading-[18px] text-ink list-disc">
                  {(data.memo?.arguments_against || []).map((item, idx) => (
                    <li key={idx}>{item}</li>
                  ))}
                </ul>
              </div>
            </div>

            {/* Risks & Mitigations */}
            <div className="rounded-[10px] border-[1.6px] border-line bg-white p-[12px]">
              <div className="text-[13px] font-bold text-navy">RISKS & RECOMMENDED MITIGATIONS</div>
              <div className="mt-[8px] flex flex-col gap-[8px]">
                {(data.memo?.risks || []).map((r, idx) => (
                  <div key={idx} className="rounded-[8px] border border-line bg-panel p-[8px] text-[13px]">
                    <div className="font-semibold text-coral">Risk: <span className="font-normal text-ink">{r.risk}</span></div>
                    <div className="mt-[2px] font-semibold text-teal">Mitigation: <span className="font-normal text-ink">{r.mitigation}</span></div>
                  </div>
                ))}
              </div>
            </div>

            {/* Evidence Check */}
            <div className="rounded-[10px] border-[1.6px] border-line bg-white p-[12px]">
              <div className="text-[13px] font-bold text-navy">EVIDENCE CHECK NOTES</div>
              <ul className="mt-[6px] flex flex-col gap-[4px] pl-[16px] text-[13px] leading-[18px] text-ink list-disc">
                {(data.memo?.evidence_notes || []).map((n, idx) => (
                  <li key={idx}>{n}</li>
                ))}
              </ul>
            </div>

            {/* Recommendation & Next Steps */}
            <div className="rounded-[10px] border-[1.6px] border-line bg-white p-[12px]">
              <div className="text-[13px] font-bold text-navy">RECOMMENDATION & NEXT STEPS</div>
              <div className="mt-[6px] text-[13.5px] font-semibold text-teal">
                {data.memo?.recommendation}
              </div>
              <div className="mt-[8px] flex flex-col gap-[4px] pl-[16px] text-[13px] leading-[18px] text-ink list-decimal">
                {(data.memo?.next_steps || []).map((step, idx) => (
                  <div key={idx} className="flex gap-[6px]">
                    <span className="font-bold text-navy">{idx + 1}.</span>
                    <span>{step}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Disclaimer */}
            <div className="text-center text-[12px] italic text-muted">
              {data.disclaimer}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
