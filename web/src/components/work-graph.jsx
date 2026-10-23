import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Background, Controls, Handle, MarkerType, Position, ReactFlow, ReactFlowProvider, applyNodeChanges, useReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "@/styles/flow.css";
import { Library, LayoutGrid, Maximize, Network, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, IdText, JsonView, KeyValues, Time } from "@/components/common";
import { MediaMeta, Thumb, mediaKind } from "@/components/media";
import { entitySlotColor } from "@/lib/comfy";
import { useOntology } from "@/lib/session";

/** Columns left to right: who → where/how → the shot → what it uses → what came out. */
const COLUMNS = [
  { label: "人物与细节", types: ["Subject", "Appearance", "Detail", "Voice"] },
  { label: "场景 · 风格 · 运镜", types: ["Place", "Style", "Camera", "Beat"] },
  { label: "镜头", types: ["Shot"] },
  { label: "台词与参考图", types: ["Line", "Reference"] },
  { label: "成片与剪辑", types: ["Clip", "Observation", "Edit"] },
];
const COLUMN_OF = Object.fromEntries(COLUMNS.flatMap((column, index) => column.types.map((type) => [type, index])));
const COLUMN_W = 300;
const NODE_W = 216;
const GAP = 16;

const SHORT = {
  has_appearance: "外形", wears: "穿着", located_in: "空间", holds: "物件", detail_of: "属于", styled_as: "风格",
  shot_with: "运镜", voices: "台词", voiced_by: "音色", contrasts_with: "反差", continues: "接续", references: "参考",
  derived_from: "派生", uses_clip: "使用", clip_of: "成片", line_of: "配音",
};

function EntityNode({ data }) {
  const artifact = data.artifact;
  const showImage = artifact && mediaKind(artifact) === "image";
  const color = entitySlotColor(data.type);
  return (
    <div className={data.active ? "entity-node active" : data.dim ? "entity-node dim" : "entity-node"} style={{ "--slot": color, width: NODE_W }}>
      <Handle id="l" type="target" position={Position.Left} isConnectable={false} />
      <Handle id="ls" type="source" position={Position.Left} isConnectable={false} />
      <div className="flex items-center gap-1.5 px-2.5 pt-2 text-[11.5px] text-[#a8a8a8]">
        {data.asset ? <Library className="size-3" /> : null}
        <span className="truncate">{data.typeLabel}</span>
        {data.asset ? <span className="ml-auto shrink-0">素材库 v{data.version}</span> : null}
      </div>
      <div className="line-clamp-2 px-2.5 pt-0.5 pb-2 text-[13px] font-medium leading-snug text-white">{data.title}</div>
      {showImage ? <img src={artifact.url} alt="" className="h-16 w-full object-cover" loading="lazy" /> : null}
      {artifact && !showImage ? <div className="px-2.5 pb-2 text-[11.5px] text-[#a8a8a8]">{mediaKind(artifact) === "video" ? "视频" : "文件"}</div> : null}
      <Handle id="r" type="source" position={Position.Right} isConnectable={false} />
      <Handle id="rt" type="target" position={Position.Right} isConnectable={false} />
    </div>
  );
}

function ColumnLabel({ data }) {
  return <div className="pointer-events-none w-[216px] text-[12px] font-medium tracking-wide text-[#8a8a8a]">{data.label}</div>;
}

const nodeTypes = { entity: EntityNode, column: ColumnLabel };

function titleOf(item) {
  const data = item.data || {};
  return data.title || data.text || data.action || data.name || item.id;
}

const heightOf = (item) => (item.artifact && mediaKind(item.artifact) === "image" ? 130 : 64);

/**
 * Column per kind of entity; inside a column, entities are ordered next to what they connect to
 * (a few barycenter sweeps), which keeps lines short and mostly uncrossed.
 */
function autoLayout(items, links) {
  const columnOf = (item) => COLUMN_OF[item.type] ?? COLUMNS.length;
  const columns = {};
  for (const item of items) (columns[columnOf(item)] ||= []).push(item);
  const neighbours = {};
  for (const link of links) {
    (neighbours[link.source_id] ||= []).push(link.target_ref);
    (neighbours[link.target_ref] ||= []).push(link.source_id);
  }
  const rank = {};
  const reindex = () => Object.values(columns).forEach((list) => list.forEach((item, index) => (rank[item.id] = index / Math.max(list.length - 1, 1))));
  reindex();
  const keys = Object.keys(columns).map(Number).sort((a, b) => a - b);
  for (let sweep = 0; sweep < 6; sweep += 1) {
    const pass = sweep % 2 ? [...keys].reverse() : keys;
    for (const key of pass) {
      if (key === 2) continue; // shots keep their story order as the spine
      const score = (item) => {
        const around = (neighbours[item.id] || []).filter((id) => rank[id] !== undefined);
        return around.length ? around.reduce((sum, id) => sum + rank[id], 0) / around.length : rank[item.id];
      };
      columns[key] = [...columns[key]].map((item) => [score(item), item]).sort((a, b) => a[0] - b[0]).map(([, item]) => item);
      reindex();
    }
  }
  const heights = Object.fromEntries(keys.map((key) => [key, columns[key].reduce((sum, item) => sum + heightOf(item) + GAP, -GAP)]));
  const tallest = Math.max(...Object.values(heights));
  const positions = {};
  keys.forEach((key, index) => {
    let y = (tallest - heights[key]) / 2 + 36;
    for (const item of columns[key]) {
      positions[item.id] = { x: index * COLUMN_W, y: Math.round(y) };
      y += heightOf(item) + GAP;
    }
  });
  const labels = keys.map((key, index) => ({ id: `column:${key}`, label: COLUMNS[key]?.label || "其他", x: index * COLUMN_W }));
  return { positions, labels, columnOf: Object.fromEntries(items.map((item) => [item.id, columnOf(item)])) };
}

function buildGraph(snapshot, ontology) {
  const typeLabel = (type) => ontology?.types?.[type]?.label || type;
  const items = [
    ...snapshot.entities.map((entity) => ({ ...entity, asset: false })),
    ...snapshot.assets.map((asset) => ({ ...asset, asset: true })),
  ].sort((a, b) => (a.type === b.type ? (a.ord ?? 0) - (b.ord ?? 0) : String(a.type).localeCompare(String(b.type))));
  const ids = new Set(items.map((item) => item.id));
  const links = snapshot.links.filter((link) => ids.has(link.source_id) && ids.has(link.target_ref));
  const { positions, labels, columnOf } = autoLayout(items, links);
  const nodes = [
    ...labels.map((label) => ({ id: label.id, type: "column", position: { x: label.x, y: 0 }, selectable: false, draggable: false, data: label })),
    ...items.map((item) => ({
      id: item.id,
      type: "entity",
      position: positions[item.id],
      data: { type: item.type, typeLabel: typeLabel(item.type), title: titleOf(item), artifact: item.artifact, asset: item.asset, version: item.version, raw: item },
    })),
  ];
  return { nodes, links, columnOf };
}

function edgesFor(links, columnOf, selected, ontology) {
  return links.map((link) => {
    const from = columnOf[link.source_id];
    const to = columnOf[link.target_ref];
    const forward = from < to;
    const same = from === to;
    const hot = selected && (link.source_id === selected || link.target_ref === selected);
    const color = hot ? "#0b8ce9" : "#5c5c5c";
    return {
      id: link.id,
      source: link.source_id,
      target: link.target_ref,
      sourceHandle: forward || same ? "r" : "ls",
      targetHandle: forward ? "l" : same ? "rt" : "rt",
      type: "default",
      label: hot ? SHORT[link.name] || ontology?.relations?.[link.name]?.label || link.name : undefined,
      className: selected && !hot ? "dim" : undefined,
      markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12, color },
      style: { stroke: color, strokeWidth: hot ? 2 : 1.25 },
      zIndex: hot ? 1 : 0,
      labelBgPadding: [4, 2],
      labelBgBorderRadius: 3,
      data: link,
    };
  });
}

function Canvas({ snapshot }) {
  const ontology = useOntology();
  const flow = useReactFlow();
  const [nodes, setNodes] = useState([]);
  const [selected, setSelected] = useState(null);
  const signature = useMemo(
    () => JSON.stringify([snapshot.entities.map((e) => [e.id, e.updated_at]), snapshot.assets.map((a) => a.id), snapshot.links.map((l) => l.id)]),
    [snapshot],
  );
  const graph = useMemo(() => buildGraph(snapshot, ontology.data), [signature, ontology.data]); // eslint-disable-line react-hooks/exhaustive-deps
  const loaded = useRef(false);

  useEffect(() => {
    setNodes(graph.nodes);
    if (!loaded.current && graph.nodes.length) {
      loaded.current = true;
      requestAnimationFrame(() => flow.fitView({ padding: 0.08, maxZoom: 1 }));
    }
  }, [graph, flow]);

  const neighbours = useMemo(() => {
    if (!selected) return null;
    const ids = new Set([selected]);
    for (const link of graph.links) {
      if (link.source_id === selected) ids.add(link.target_ref);
      if (link.target_ref === selected) ids.add(link.source_id);
    }
    return ids;
  }, [selected, graph.links]);
  const shown = useMemo(
    () =>
      nodes.map((node) =>
        node.type === "entity" ? { ...node, data: { ...node.data, active: node.id === selected, dim: neighbours ? !neighbours.has(node.id) : false } } : node,
      ),
    [nodes, selected, neighbours],
  );
  const edges = useMemo(() => edgesFor(graph.links, graph.columnOf, selected, ontology.data), [graph, selected, ontology.data]);
  const panelOpen = Boolean(selected);
  useEffect(() => {
    if (!loaded.current) return;
    const timer = setTimeout(() => flow.fitView({ padding: 0.08, maxZoom: 1, duration: 200 }), 30);
    return () => clearTimeout(timer);
  }, [panelOpen, flow]);
  const onNodesChange = useCallback((changes) => setNodes((current) => applyNodeChanges(changes, current)), []);

  const tidy = () => {
    setNodes(graph.nodes);
    requestAnimationFrame(() => flow.fitView({ padding: 0.08, maxZoom: 1, duration: 300 }));
  };

  const selectedItem = selected ? nodes.find((node) => node.id === selected)?.data : null;
  const links = selected ? snapshot.links.filter((link) => link.source_id === selected || link.target_ref === selected) : [];
  const nameOf = (id) => {
    const node = nodes.find((item) => item.id === id);
    return node ? `${node.data.typeLabel} · ${node.data.title}` : id;
  };

  if (!snapshot.entities.length && !snapshot.assets.length) {
    return <EmptyState icon={Network} title="关系图是空的" description="作品里还没有实体。agent 添加主体、镜头、参考等实体并连上关系后，这里会画出整张本体图。" />;
  }

  return (
    <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto]">
      <Card className="flow-canvas relative h-[calc(100dvh-260px)] min-h-[420px] overflow-hidden">
        <div className="absolute right-3 bottom-3 z-10 flex items-center gap-1.5">
          <span className="mr-1 hidden text-xs text-[#8a8a8a] md:inline">点实体高亮它的关系，可拖动</span>
          <Button size="xs" variant="outline" onClick={tidy}>
            <LayoutGrid />
            重新排布
          </Button>
          <Button size="xs" variant="outline" onClick={() => flow.fitView({ padding: 0.08, duration: 300 })}>
            <Maximize />
            适应画布
          </Button>
        </div>
        <ReactFlow
          nodes={shown}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onNodeClick={(_event, node) => node.type === "entity" && setSelected(node.id === selected ? null : node.id)}
          onPaneClick={() => setSelected(null)}
          nodesConnectable={false}
          edgesFocusable={false}
          minZoom={0.2}
          maxZoom={1.6}
          colorMode="dark"
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={20} size={1} color="#333" />
          <Controls showInteractive={false} position="bottom-left" />
        </ReactFlow>
      </Card>
      {selectedItem ? (
        <Card className="w-full overflow-hidden lg:w-[340px]">
          <div className="flex items-center justify-between border-b px-4 py-2.5">
            <div className="min-w-0">
              <p className="text-xs text-muted-foreground">
                {selectedItem.typeLabel}
                {selectedItem.asset ? ` · 素材库 ${selectedItem.raw.asset}@${selectedItem.version}` : ""}
              </p>
              <p className="truncate text-sm font-semibold">{selectedItem.title}</p>
            </div>
            <Button size="icon-sm" variant="ghost" onClick={() => setSelected(null)} aria-label="关闭">
              <X />
            </Button>
          </div>
          <div className="max-h-[calc(100dvh-320px)] space-y-3 overflow-y-auto p-4">
            {selectedItem.artifact ? (
              <div>
                <Thumb artifact={selectedItem.artifact} />
                <MediaMeta artifact={selectedItem.artifact} className="mt-1" />
              </div>
            ) : null}
            <KeyValues
              items={[
                ["编号", <IdText id={selectedItem.raw.id} />],
                selectedItem.raw.created_by ? ["创建者", selectedItem.raw.created_by] : null,
                selectedItem.raw.updated_at ? ["更新", <Time value={selectedItem.raw.updated_at} />] : null,
              ]}
            />
            <EntityFields type={selectedItem.type} data={selectedItem.raw.data || {}} ontology={ontology.data} />
            <div>
              <p className="mb-1 text-xs font-medium text-muted-foreground">关系（{links.length}）</p>
              {links.length ? (
                <ul className="space-y-1 text-[13px]">
                  {links.map((link) => {
                    const out = link.source_id === selected;
                    return (
                      <li key={link.id} className="rounded-md border bg-[#222] px-2 py-1.5">
                        <span className="text-muted-foreground">{out ? "→" : "←"} {ontology.data?.relations?.[link.name]?.label || link.name}</span>
                        <button className="block w-full truncate text-left text-primary hover:underline" onClick={() => setSelected(out ? link.target_ref : link.source_id)}>
                          {nameOf(out ? link.target_ref : link.source_id)}
                        </button>
                        {link.note ? <span className="block text-xs text-muted-foreground">{link.note}</span> : null}
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <p className="text-[13px] text-muted-foreground">没有关系</p>
              )}
            </div>
          </div>
        </Card>
      ) : null}
    </div>
  );
}

/** Entity fields with the ontology's Chinese labels; anything the ontology doesn't know is kept as JSON. */
function EntityFields({ type, data, ontology }) {
  const fields = ontology?.types?.[type]?.fields || [];
  const known = fields.filter((field) => data[field.name] != null && data[field.name] !== "");
  const rest = Object.fromEntries(Object.entries(data).filter(([key]) => !fields.some((field) => field.name === key)));
  const show = (value) => (typeof value === "string" || typeof value === "number" ? String(value) : <JsonView value={value} maxHeight="10rem" />);
  return (
    <div className="space-y-2">
      {known.length ? <KeyValues items={known.map((field) => [field.label.split("，")[0], show(data[field.name])])} /> : null}
      {Object.keys(rest).length ? <JsonView value={rest} maxHeight="12rem" /> : null}
    </div>
  );
}

export default function WorkGraph(props) {
  return (
    <ReactFlowProvider>
      <Canvas {...props} />
    </ReactFlowProvider>
  );
}
