import { Handle, Position } from "@xyflow/react";

function Metric({ label, value }) {
  return (
    <div className="node-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export default function GraphNode({ data, sourcePosition = Position.Bottom, targetPosition = Position.Top }) {
  const isScript = data.nodeType === "script";

  return (
    <div
      className={[
        "graph-node-card",
        `state-${data.displayState}`,
        data.selected ? "is-selected" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <Handle type="target" position={targetPosition} className="node-handle" />
      <div className="node-card-header">
        <span className="node-kind-pill">{isScript ? "Script" : "Agent"}</span>
        <span className={`node-state-pill pill-${data.displayState}`}>{data.displayState}</span>
      </div>

      <div className="node-title">{data.label}</div>

      {!isScript && (
        <div className="node-badges">
          {data.badgeLine.map((badge) => (
            <span key={badge} className="node-badge">
              {badge}
            </span>
          ))}
        </div>
      )}

      {!isScript && (
        <div className="node-metrics-grid">
          <Metric label="Context" value={data.contextLabel} />
          <Metric label="Output" value={data.outputLabel} />
        </div>
      )}

      {data.cycleInfo.length > 0 ? (
        <div className="node-cycle-row">
          {data.cycleInfo.map((cycle) => (
            <span key={cycle.key} className="node-cycle-badge">
              {cycle.kind === "self-loop" ? "Loop" : "Cycle"} {cycle.currentRound}/{cycle.maxRounds || "?"}
            </span>
          ))}
        </div>
      ) : null}

      {data.outputCount > 0 && (
        <div className="node-output-indicator">Outputs {data.outputSummary}</div>
      )}

      <Handle type="source" position={sourcePosition} className="node-handle" />
    </div>
  );
}
