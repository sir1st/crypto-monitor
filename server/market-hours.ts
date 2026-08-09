export interface MarketHours {
  name: string;
  timeZone: string;
  abbreviation: string;
  status: "open" | "closed";
  openTime: string;
  closeTime: string;
  currentTime: string;
}

interface MarketDefinition {
  name: string;
  timeZone: string;
  abbreviation: string;
  /** `null` for markets that never close. */
  hours: { open: [number, number]; close: [number, number] } | null;
}

const MARKETS: MarketDefinition[] = [
  { name: "Cryptocurrency Markets", timeZone: "UTC", abbreviation: "CRYPTO", hours: null },
  {
    name: "New York Stock Exchange",
    timeZone: "America/New_York",
    abbreviation: "NYSE",
    hours: { open: [9, 30], close: [16, 0] },
  },
  {
    name: "London Stock Exchange",
    timeZone: "Europe/London",
    abbreviation: "LSE",
    hours: { open: [8, 0], close: [16, 30] },
  },
  {
    name: "Tokyo Stock Exchange",
    timeZone: "Asia/Tokyo",
    abbreviation: "TSE",
    hours: { open: [9, 0], close: [15, 0] },
  },
  {
    name: "Hong Kong Stock Exchange",
    timeZone: "Asia/Hong_Kong",
    abbreviation: "HKEX",
    hours: { open: [9, 30], close: [16, 0] },
  },
  {
    name: "Shanghai Stock Exchange",
    timeZone: "Asia/Shanghai",
    abbreviation: "SSE",
    hours: { open: [9, 30], close: [15, 0] },
  },
];

/**
 * Reads wall-clock hours and minutes in a target timezone.
 *
 * `hour12: false` can render midnight as "24", so the hour is taken modulo 24.
 */
function localTime(date: Date, timeZone: string): { hour: number; minute: number } {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(date);

  const read = (type: "hour" | "minute") =>
    Number(parts.find((p) => p.type === type)?.value ?? "0");

  return { hour: read("hour") % 24, minute: read("minute") };
}

function formatTime(hour: number, minute: number): string {
  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

/**
 * Open/closed status for the major exchanges at a given instant.
 *
 * The weekday check uses each market's own timezone rather than UTC, so a
 * Monday morning in Tokyo isn't reported closed because it is still Sunday UTC.
 */
export function getMarketHours(unixSeconds: number): MarketHours[] {
  const date = new Date(unixSeconds * 1000);

  return MARKETS.map((market) => {
    const { hour, minute } = localTime(date, market.timeZone);
    const currentTime = formatTime(hour, minute);

    if (!market.hours) {
      return {
        name: market.name,
        timeZone: market.timeZone,
        abbreviation: market.abbreviation,
        status: "open" as const,
        openTime: "00:00",
        closeTime: "24:00",
        currentTime,
      };
    }

    const weekday = new Intl.DateTimeFormat("en-US", {
      timeZone: market.timeZone,
      weekday: "short",
    }).format(date);
    const isWeekend = weekday === "Sat" || weekday === "Sun";

    const [openHour, openMinute] = market.hours.open;
    const [closeHour, closeMinute] = market.hours.close;
    const nowMinutes = hour * 60 + minute;
    const openMinutes = openHour * 60 + openMinute;
    const closeMinutes = closeHour * 60 + closeMinute;

    const withinHours =
      closeMinutes < openMinutes
        ? // Session spans midnight.
          nowMinutes >= openMinutes || nowMinutes < closeMinutes
        : nowMinutes >= openMinutes && nowMinutes < closeMinutes;

    return {
      name: market.name,
      timeZone: market.timeZone,
      abbreviation: market.abbreviation,
      status: !isWeekend && withinHours ? ("open" as const) : ("closed" as const),
      openTime: formatTime(openHour, openMinute),
      closeTime: formatTime(closeHour, closeMinute),
      currentTime,
    };
  });
}
