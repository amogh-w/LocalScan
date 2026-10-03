import { useEffect, useState } from "react";
import { buildStyles, CircularProgressbarWithChildren } from "react-circular-progressbar";
import "react-circular-progressbar/dist/styles.css";

const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

/**
 * What a long job is doing: a ring with the percent, the step, one sentence of detail and the time so far.
 * Without a percent the ring pulses (the job has not reported how far it is). `elapsed` is the job's age in
 * seconds when it was last reported; the clock counts on from there.
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
      <div className={`ring${known ? "" : " pulse"}`}>
        <CircularProgressbarWithChildren value={known ? percent : 100} strokeWidth={10}
          styles={buildStyles({
            pathColor: "var(--accent)", trailColor: "var(--raised)", pathTransitionDuration: 0.6, strokeLinecap: "round",
          })}>
          {known && <span className="ring-num">{Math.round(percent)}%</span>}
        </CircularProgressbarWithChildren>
      </div>
      <div className="progress-text">
        <strong>{title}</strong>
        {detail && <span className="muted">{detail}</span>}
        <span className="muted small">{[step, clock(elapsed + now)].filter(Boolean).join(" · ")}</span>
      </div>
    </div>
  );
}
