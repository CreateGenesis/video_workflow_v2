import { useMemo } from "react";
import { Background, BackgroundVariant, Controls, Handle, MarkerType, MiniMap, Position, ReactFlow, ReactFlowProvider } from "@xyflow/react";
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

function layout(order, deps) {
  const depth = {};
  for (const id of order) {
    const parents = deps[id] || [];
    depth[id] = parents.length ? Math.max(...parents.map((parent) => (depth[parent] ?? 0) + 1)) : 0;
  }
  const columns = {};
  for (const id of order) {
    const column = depth[id] || 0;
    columns[column] = columns[column] || [];
    columns[column].push(id);
  }
  const positions = {};
  for (const [column, ids] of Object.entries(columns)) {
    ids.forEach((id, index) => {
      positions[id] = { x: Number(column) * 280, y: index * 150 };
    });
  }
  return positions;
}

export function StepGraph({ nodes = [], order = [], deps = {}, summaries = {} }) {
  const byId = useMemo(() => Object.fromEntries(nodes.map((node) => [node.id, node])), [nodes]);
  const positions = useMemo(() => layout(order, deps), [order, deps]);
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
    <div className="flow-canvas h-[460px] overflow-hidden rounded-lg border border-[#4e4e4e] bg-[#141414]" data-testid="step-graph">
      <ReactFlowProvider>
        <ReactFlow
          nodes={flowNodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable
          colorMode="dark"
          proOptions={{ hideAttribution: true }}
          minZoom={0.4}
          maxZoom={1.6}
        >
          <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="#4e4e4e" />
          <Controls showInteractive={false} />
          <MiniMap
            pannable
            zoomable
            bgColor="#171718"
            maskColor="rgba(23,23,24,0.72)"
            nodeColor={(node) => slotColor(node.data?.kind)}
          />
        </ReactFlow>
      </ReactFlowProvider>
    </div>
  );
}
