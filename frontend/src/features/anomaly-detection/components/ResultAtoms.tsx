import { COLOR_LABEL } from "../../../lib/colors";
import type { Color, Reason, Segment } from "../../../types/api";

export function Chip({ color, label }: { color: Color; label?: string }) {
  return <span className={`chip ${color}`}>{label ?? COLOR_LABEL[color]}</span>;
}

export function Highlight({ segments, fallback }: { segments?: Segment[]; fallback?: string | null }) {
  if (!segments || segments.length === 0) return <span>{fallback ?? "—"}</span>;
  return (
    <span className="hl">
      {segments.map((s, i) => (
        <span key={i} className={`seg ${s.kind}`}>
          {s.text}
        </span>
      ))}
    </span>
  );
}

export function Reasons({ reasons }: { reasons?: Reason[] }) {
  return (
    <>
      {(reasons ?? [])
        .filter((r) => r.severity !== "info")
        .map((r) => (
          <div key={r.code} className={`reason ${r.severity}`}>
            <code>{r.code}</code> {r.message}
          </div>
        ))}
    </>
  );
}
