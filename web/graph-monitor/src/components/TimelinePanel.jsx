import { trimText } from "../lib/format";

function describeEvent(event) {
  if (event.type === "tool_use") {
    return `${event.tool} · ${trimText(event.target, 120)}`;
  }
  if (event.type === "message") {
    return trimText(event.text, 220);
  }
  if (event.type === "compaction") {
    return `Context compacted at ${event.pre_tokens ?? 0} pre-tokens`;
  }
  if (event.type === "heartbeat") {
    return "No new sidecar events";
  }
  return trimText(event.message ?? JSON.stringify(event), 220);
}

export default function TimelinePanel({ events, selectedNodeId, showHeartbeats, onToggleHeartbeats, onSelectNode, collapsed, onToggleCollapsed }) {
  return (
    <section className={`panel timeline-panel${collapsed ? " is-collapsed" : ""}`}>
      <button type="button" className="panel-heading panel-heading-toggle" onClick={onToggleCollapsed}>
        <div>
          <div className="panel-kicker">Activity</div>
          <h2>{selectedNodeId ? `${selectedNodeId}` : "Live feed"}</h2>
        </div>
        <div className="panel-heading-right">
          {collapsed ? null : (
            <span
              className="subtle-button"
              role="button"
              tabIndex={0}
              onClick={(e) => { e.stopPropagation(); onToggleHeartbeats(); }}
              onKeyDown={(e) => { if (e.key === "Enter") { e.stopPropagation(); onToggleHeartbeats(); } }}
            >
              {showHeartbeats ? "Hide heartbeats" : "Show heartbeats"}
            </span>
          )}
          <span className="collapse-indicator">{collapsed ? "+" : "−"}</span>
        </div>
      </button>

      {collapsed ? null : (
        <div className="timeline-list">
          {events.length ? (
            events.map((event, index) => (
              <button
                key={`${event.ts}-${event.agent ?? event.type}-${index}`}
                type="button"
                className="timeline-row"
                onClick={() => event.agent && onSelectNode(event.agent)}
              >
                <div className="timeline-row-head">
                  <span className="timeline-event-time">{event.ts}</span>
                  <span className="timeline-event-type">{event.agent ? `${event.agent} · ${event.type}` : event.type}</span>
                </div>
                <div className="timeline-event-body">{describeEvent(event)}</div>
              </button>
            ))
          ) : (
            <div className="panel-empty-copy">No timeline entries match the current filter.</div>
          )}
        </div>
      )}
    </section>
  );
}
