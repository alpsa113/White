// components/HeaderClock.tsx — 대시보드 상단 좌측 날짜+시각(1초마다 갱신). ui/camera/toolbar.py 이식.
import { useEffect, useState } from "react";

const WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"];

function pad(n: number): string {
  return n.toString().padStart(2, "0");
}

function formatNow(now: Date) {
  const weekday = WEEKDAY_KO[(now.getDay() + 6) % 7]; // JS: Sun=0 → 월요일 기준으로 회전
  const dateStr = `${now.getFullYear()}.${pad(now.getMonth() + 1)}.${pad(now.getDate())}`;
  const hour24 = now.getHours();
  const period = hour24 < 12 ? "오전" : "오후";
  const hour12 = hour24 % 12 === 0 ? 12 : hour24 % 12;
  const timeStr = `${pad(hour12)}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
  return { weekday, dateStr, period, timeStr };
}

export function HeaderClock() {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const { weekday, dateStr, period, timeStr } = formatNow(now);

  return (
    <div className="header-clock">
      <div className="clock-date">
        {dateStr} ({weekday})
      </div>
      <span className="clock-period">{period}</span> <span className="clock-time">{timeStr}</span>
    </div>
  );
}
