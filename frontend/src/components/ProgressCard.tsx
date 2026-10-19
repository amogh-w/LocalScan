import { useEffect, useState } from "react";

const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const CIRCUMFERENCE = 97.4; // the kit's ring: r = 15.5 in a 36 x 36 box

/**
 * What a long job is doing: the kit's ring with the percent, the step, one sentence of detail and the time so far.
 * Without a percent the ring is replaced by a spinner (the job has not reported how far it is). `elapsed` is the
 * job's age in seconds when it was last reported; the clock counts on from there.
 */
export default function ProgressCard({ title, detail, percent, step, elapsed = 0 }: {
  title: string; detail?: string; percent?: number; step?: string; elapsed?: number;
}) {
  const [now, setNow] = useState(0);
  useEffect(() => {
    setNow(0);
    const t = window.setInterval(() => setNow((n) => n + 1), 1000);
    return () => window.clearInterval(t);
  }, [elapsed, title]);
  const known = percent !== undefined;
  return (
    <div className="progress-card" role="status" aria-live="polite">
      <div className="ring">
        {known ? (
          <>
            <svg viewBox="0 0 36 36" aria-hidden="true">
              <circle cx="18" cy="18" r="15.5" fill="none" strokeWidth="3.5" className="stroke-surface1" />
              <circle cx="18" cy="18" r="15.5" fill="none" strokeWidth="3.5" strokeLinecap="round" className="stroke-accent"
                strokeDasharray={CIRCUMFERENCE} strokeDashoffset={CIRCUMFERENCE * (1 - Math.min(100, percent) / 100)} />
            </svg>
            <span className="ring-num">{Math.round(percent)}%</span>
          </>
        ) : (
          <span className="spin-ring" />
        )}
      </div>
      <div className="progress-text">
        <strong>{title}</strong>
        {detail && <span className="muted">{detail}</span>}
        <span className="muted small">{[step, clock(elapsed + now)].filter(Boolean).join(" · ")}</span>
      </div>
    </div>
  );
}
