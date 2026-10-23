import { useMemo } from "react";
import { Background, BackgroundVariant, Handle, MarkerType, Position, ReactFlow, ReactFlowProvider } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "@/styles/flow.css";
import { Clapperboard, Image, Mic, Music, ScanSearch, Scissors, Sparkles, UserCheck, Workflow } from "lucide-react";
import { kindLabel } from "@/lib/labels";
import { slotColor } from "@/lib/comfy";
import { layered, transitiveReduction } from "@/lib/graph-layout";

const KIND_ICON = { llm: Sparkles, image: Image, video: Clapperboard, tts: Mic, music: Music, check: ScanSearch, edit: Scissors, gate: UserCheck };
const NODE_W = 248;
const NODE_H = 62;

export function KindIcon({ kind, className }) {
  const Icon = KIND_ICON[kind] || Workflow;
  return <Icon className={className} style={{ color: slotColor(kind) }} />;
}

function StepNode({ data }) {
  const color = slotColor(data.kind);
  return (
    <div
      className={data.active ? "step-node active" : data.dim ? "step-node dim" : "step-node"}
      style={{ "--slot": color, width: NODE_W, height: NODE_H }}
      title={data.title}
    >
      <Handle type="target" position={Position.Top} isConnectable={false} />
      <span className="step-node-index tnum">{data.index}</span>
      <KindIcon kind={data.kind} className="size-4 shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="truncate text-[13px] font-semibold text-white">{data.title}</div>
        <div className="truncate text-[11.5px] text-[#a8a8a8]">{data.caption}</div>
      </div>
      {data.status ? <span className="step-node-status" style={{ background: data.status }} /> : null}
      <Handle type="source" position={Position.Bottom} isConnectable={false} />
    </div>
  );
}

const nodeTypes = { step: StepNode };

function caption(node) {
  const parts = [kindLabel(node.kind)];
  if (node.for_each) parts.push("逐条");
  if (node.kind === "image" && node.candidates > 1) parts.push(`${node.candidates} 张候选`);
  if (node.kind === "gate") parts.push(node.auto_approve ? "自动通过" : "人工审批");
  if (node.provider) parts.push(node.provider);
  return parts.join(" · ");
}

/**
 * Workflow steps top to bottom. Edges implied by a longer path are left out so the pipeline reads
 * cleanly; the full dependency list is in the step detail. Click a step to select it.
 */
export function StepGraph({ nodes = [], order = [], deps = {}, selected, onSelect, statusColor = {} }) {
  const byId = useMemo(() => Object.fromEntries(nodes.map((node) => [node.id, node])), [nodes]);
  const reduced = useMemo(() => transitiveReduction(order, deps), [order, deps]);
  const pairs = useMemo(() => order.flatMap((id) => (reduced[id] || []).map((parent) => ({ source: parent, target: id }))), [order, reduced]);
  const placed = useMemo(
    () => layered(order.map((id) => ({ id, width: NODE_W, height: NODE_H })), pairs, { direction: "TB", nodesep: 24, ranksep: 34 }),
    [order, pairs],
  );
  const touching = useMemo(() => {
    if (!selected) return null;
    const ids = new Set([selected, ...(deps[selected] || [])]);
    for (const id of order) if ((deps[id] || []).includes(selected)) ids.add(id);
    return ids;
  }, [selected, deps, order]);
  const flowNodes = order.map((id, index) => {
    const node = byId[id] || { id, kind: "llm" };
    return {
      id,
      type: "step",
      position: placed.positions[id] || { x: 0, y: 0 },
      selectable: Boolean(onSelect),
      data: {
        index: index + 1,
        kind: node.kind,
        title: node.title || id,
        caption: caption(node),
        active: selected === id,
        dim: touching ? !touching.has(id) : false,
        status: statusColor[id],
      },
    };
  });
  const edges = pairs.map(({ source, target }) => {
    const hot = selected && (source === selected || target === selected);
    const color = hot ? "#0b8ce9" : "#6a6a6a";
    return {
      id: `${source}->${target}`,
      source,
      target,
      type: "smoothstep",
      pathOptions: { borderRadius: 10 },
      style: { stroke: color, strokeWidth: hot ? 2 : 1.5 },
      markerEnd: { type: MarkerType.ArrowClosed, color, width: 14, height: 14 },
      zIndex: hot ? 1 : 0,
    };
  });

  if (!order.length) {
    return <p className="px-4 py-6 text-[13px] text-muted-foreground">这个版本没有步骤。</p>;
  }
  const height = Math.min(placed.height + 48, 680);

  return (
    <div className="flow-canvas overflow-hidden bg-[#141414]" style={{ height }} data-testid="step-graph">
      <ReactFlowProvider>
        <ReactFlow
          nodes={flowNodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodeClick={onSelect ? (_event, node) => onSelect(node.id) : undefined}
          fitView
          fitViewOptions={{ padding: 0.08, maxZoom: 1, minZoom: 0.6 }}
          nodesDraggable={false}
          nodesConnectable={false}
          edgesFocusable={false}
          colorMode="dark"
          proOptions={{ hideAttribution: true }}
          minZoom={0.6}
          maxZoom={1}
          panOnDrag={placed.height + 48 > height}
          panOnScroll={false}
          zoomOnScroll={false}
          zoomOnPinch={false}
          zoomOnDoubleClick={false}
          preventScrolling={false}
        >
          <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="#333" />
        </ReactFlow>
      </ReactFlowProvider>
    </div>
  );
}
