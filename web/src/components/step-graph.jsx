import { useMemo } from "react";
import { Background, BackgroundVariant, Controls, Handle, MarkerType, Position, ReactFlow, ReactFlowProvider } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "@/styles/flow.css";
import { kindLabel } from "@/lib/labels";
import { slotColor, slotOf } from "@/lib/comfy";

function StepNode({ data, selected }) {
  const color = slotColor(data.kind);
  return (
    <div className={selected ? "comfy-node selected" : "comfy-node"} style={{ "--slot": color }}>
      <Handle type="target" position={Position.Left} style={{ background: color }} />
      <div className="comfy-node-title">
        <span className="truncate">{data.title}</span>
        <span className="ml-auto shrink-0 text-[10px] font-normal text-[#999]">{kindLabel(data.kind)}</span>
      </div>
      <div className="comfy-node-body space-y-1.5">
        <div className="comfy-slot">
          <span className="comfy-slot-dot" style={{ background: color }} />
          <span>{slotOf(data.kind)}</span>
          <code className="ml-auto text-[10px] text-[#999]">{data.nodeId}</code>
        </div>
        {data.deps?.length ? <p className="text-[11px] text-[#999]">← {data.deps.join("、")}</p> : <p className="text-[11px] text-[#666]">起点</p>}
        {data.summary ? <p className="line-clamp-2 text-[11px] leading-snug text-[#ccc]">{data.summary}</p> : null}
      </div>
      <Handle type="source" position={Position.Right} style={{ background: color }} />
    </div>
  );
}

const nodeTypes = { step: StepNode };

const COLUMN = 300;
const ROW = 150;
const LEVELS_PER_ROW = 3;

/** Dependency depth decides the column; long pipelines wrap onto the next band so text stays readable. */
function layout(order, deps) {
  const depth = {};
  for (const id of order) {
    const parents = deps[id] || [];
    depth[id] = parents.length ? Math.max(...parents.map((parent) => (depth[parent] ?? 0) + 1)) : 0;
  }
  const levels = {};
  for (const id of order) {
    (levels[depth[id] || 0] ||= []).push(id);
  }
  const positions = {};
  let bandTop = 0;
  const levelIds = Object.keys(levels).map(Number).sort((a, b) => a - b);
  for (let start = 0; start < levelIds.length; start += LEVELS_PER_ROW) {
    const band = levelIds.slice(start, start + LEVELS_PER_ROW);
    const tallest = Math.max(...band.map((level) => levels[level].length));
    band.forEach((level, column) => {
      levels[level].forEach((id, index) => {
        positions[id] = { x: column * COLUMN, y: bandTop + index * ROW };
      });
    });
    bandTop += tallest * ROW + 40;
  }
  return { positions, height: bandTop };
}

export function StepGraph({ nodes = [], order = [], deps = {}, summaries = {} }) {
  const byId = useMemo(() => Object.fromEntries(nodes.map((node) => [node.id, node])), [nodes]);
  const { positions, height } = useMemo(() => layout(order, deps), [order, deps]);
  const flowNodes = useMemo(
    () =>
      order.map((id) => {
        const node = byId[id] || { id, kind: "llm" };
        return {
          id,
          type: "step",
          position: positions[id] || { x: 0, y: 0 },
          data: {
            nodeId: id,
            kind: node.kind,
            title: node.title || id,
            deps: deps[id] || [],
            summary: summaries[id] || "",
          },
        };
      }),
    [order, byId, positions, deps, summaries],
  );
  const edges = useMemo(() => {
    const list = [];
    for (const id of order) {
      for (const parent of deps[id] || []) {
        const color = slotColor((byId[parent] || {}).kind);
        list.push({
          id: `${parent}->${id}`,
          source: parent,
          target: id,
          style: { stroke: color, strokeWidth: 2 },
          markerEnd: { type: MarkerType.ArrowClosed, color, width: 16, height: 16 },
        });
      }
    }
    return list;
  }, [order, deps, byId]);

  if (!order.length) {
    return <p className="px-4 py-6 text-[13px] text-muted-foreground">这个版本没有步骤。</p>;
  }

  return (
    <div className="flow-canvas overflow-hidden border-y border-[#4e4e4e] bg-[#141414]" style={{ height: Math.min(Math.max(height + 60, 220), 620) }} data-testid="step-graph">
      <ReactFlowProvider>
        <ReactFlow
          nodes={flowNodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.12, minZoom: 0.75, maxZoom: 1 }}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable
          colorMode="dark"
          proOptions={{ hideAttribution: true }}
          minZoom={0.5}
          maxZoom={1.6}
          panOnScroll={false}
          zoomOnScroll={false}
          preventScrolling={false}
        >
          <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="#4e4e4e" />
          <Controls showInteractive={false} />

        </ReactFlow>
      </ReactFlowProvider>
    </div>
  );
}
