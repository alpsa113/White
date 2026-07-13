// utils/formatters.ts — utils/formatters.py의 표시용 포맷팅 함수 이식.
import type { Detection, LogEntry } from "../types";

/** created_at을 "YYYY-MM-DD HH:MM:SS" 문자열로 반환합니다. */
export function fmtDt(a: Partial<Detection> | Partial<LogEntry> | Record<string, unknown>): string {
  const val = (a as Record<string, unknown>).created_at;
  if (!val) return "";
  return String(val).slice(0, 19);
}

/** fmtDt 결과를 "YYYY.MM.DD. HH:MM:SS" 형식으로 바꿉니다(탐지 이력 패널 표시용). */
export function fmtDtDot(a: Partial<Detection> | Record<string, unknown>): string {
  const raw = fmtDt(a);
  const [datePart, timePart] = raw.split(" ");
  if (!datePart || !timePart) return raw;
  const [y, m, d] = datePart.split("-");
  if (!y || !m || !d) return raw;
  return `${y}.${m}.${d}. ${timePart}`;
}

export function fmtPercent(score: number): string {
  return `${(score * 100).toFixed(1)}%`;
}

export function isPersonClass(className: string): boolean {
  return className === "사람";
}
