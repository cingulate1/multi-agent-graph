export function formatNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "—";
  }

  return new Intl.NumberFormat("en-US").format(number);
}

export function formatCompactNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "—";
  }

  if (number >= 1_000_000) {
    return `${(number / 1_000_000).toFixed(number >= 10_000_000 ? 0 : 1)}M`;
  }
  if (number >= 1_000) {
    return `${(number / 1_000).toFixed(number >= 10_000 ? 0 : 1)}K`;
  }

  return `${number}`;
}

export function formatBytes(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0) {
    return "—";
  }

  if (number >= 1024 * 1024) {
    return `${(number / (1024 * 1024)).toFixed(1)} MB`;
  }
  if (number >= 1024) {
    return `${(number / 1024).toFixed(1)} KB`;
  }

  return `${number} B`;
}

export function formatIsoTimestamp(value) {
  if (!value) {
    return "—";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function titleCase(value) {
  if (!value) {
    return "Unknown";
  }

  return `${value}`
    .replace(/[-_]+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export function normalizeDisplayState(value) {
  if (!value) {
    return "pending";
  }

  if (value === "complete") {
    return "completed";
  }

  return value;
}

export function formatRelativeTime(ts) {
  if (!ts) {
    return "";
  }

  let date = new Date(ts);
  if (Number.isNaN(date.getTime())) {
    const match = ts.match(/^(\d{1,2}):(\d{2}):(\d{2})$/);
    if (match) {
      date = new Date();
      date.setHours(parseInt(match[1], 10), parseInt(match[2], 10), parseInt(match[3], 10), 0);
    } else {
      return ts;
    }
  }

  const diffMs = Date.now() - date.getTime();
  if (diffMs < 0) {
    return "just now";
  }

  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) {
    return "just now";
  }
  if (diffMin < 60) {
    return `${diffMin} m ago`;
  }

  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) {
    return `${diffHr} h ago`;
  }

  return `${Math.floor(diffHr / 24)} d ago`;
}

export function trimText(value, maxLength = 180) {
  if (!value) {
    return "";
  }
  if (value.length <= maxLength) {
    return value;
  }
  return `${value.slice(0, maxLength - 1)}…`;
}
