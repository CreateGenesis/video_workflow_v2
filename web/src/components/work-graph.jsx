import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Background, Controls, Handle, MarkerType, MiniMap, Position, ReactFlow, ReactFlowProvider, applyNodeChanges, useReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "@/styles/flow.css";
import { Library, LayoutGrid, Maximize, Network, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { toast } from "@/components/ui/toast";
import { EmptyState, IdText, JsonView, KeyValues, Time } from "@/components/common";
import { MediaMeta, Thumb, mediaKind } from "@/components/media";
import { entitySlotColor } from "@/lib/comfy";
import { api } from "@/lib/api";
import { useOntology } from "@/lib/session";
import { cn } from "@/lib/utils";

const COLUMN = {
  Subject: 0, Appearance: 0, Detail: 0, Voice: 0,
  Place: 1, Style: 1, Camera: 1, Beat: 1,
  Shot: 2,
  Line: 3, Reference: 3,
  Clip: 4, Observation: 4, Edit: 4,
};

const SHORT = {
  has_appearance: "外形", wears: "穿着", located_in: "空间", holds: "物件", detail_of: "属于", styled_as: "风格",
  shot_with: "运镜", voices: "台词", voiced_by: "音色", contrasts_with: "反差", continues: "接续", references: "参考",
  derived_from: "派生", uses_clip: "使用", clip_of: "成片", line_of: "配音",
};



function EntityNode({ data, selected }) {
  const artifact = data.artifact;
  const showImage = artifact && mediaKind(artifact) === "image";
  const color = entitySlotColor(data.type);
  return (
    <div className={selected ? "comfy-node selected" : "comfy-node"} style={{ "--slot": color, width: 200 }}>
      <Handle type="target" position={Position.Left} style={{ background: color }} />
      <div className="comfy-node-title">
        {data.asset ? <Library className="size-3" /> : null}
        <span className="truncate">{data.typeLabel}</span>
        {data.asset ? <span className="ml-auto text-[10px] font-normal">v{data.version}</span> : null}
      </div>
      <div className="comfy-node-body">
        <div className="line-clamp-2 text-[13px] font-medium leading-snug text-white">{data.title}</div>
        {showImage ? <img src={artifact.url} alt="" className="mt-1.5 h-16 w-full rounded object-cover" loading="lazy" /> : null}
        {artifact && !showImage ? <div className="mt-1 text-[11px] text-[#999]">{mediaKind(artifact) === "video" ? "视频" : "文件"}</div> : null}
      </div>
      <Handle type="source" position={Position.Right} style={{ background: color }} />
    </div>
  );
}

const nodeTypes = { entity: EntityNode };

function titleOf(item) {
  const data = item.data || {};
  return data.title || data.text || data.action || data.name || item.id;
}

function autoLayout(items) {
  const columns = {};
  const positions = {};
  for (const item of items) {
    const column = COLUMN[item.type] ?? 5;
    columns[column] = columns[column] || [];
    columns[column].push(item);
  }
  for (const [column, list] of Object.entries(columns)) {
    let y = 0;
    for (const item of list) {
      positions[item.id] = { x: Number(column) * 270, y };
      y += item.artifact && mediaKind(item.artifact) === "image" ? 150 : 90;
    }
  }
  return positions;
}

function buildGraph(snapshot, ontology, forceAuto) {
  const typeLabel = (type) => ontology?.types?.[type]?.label || type;
  const items = [
    ...snapshot.entities.map((entity) => ({ ...entity, asset: false })),
    ...snapshot.assets.map((asset) => ({ ...asset, asset: true })),
  ].sort((a, b) => (a.type === b.type ? (a.ord ?? 0) - (b.ord ?? 0) : String(a.type).localeCompare(String(b.type))));
  const auto = autoLayout(items);
  const nodes = items.map((item) => ({
    id: item.id,
    type: "entity",
    position: !forceAuto && !item.asset && item.position && (item.position.x || item.position.y) ? item.position : auto[item.id],
    data: {
      type: item.type,
      typeLabel: typeLabel(item.type),
      title: titleOf(item),
      artifact: item.artifact,
      asset: item.asset,
      version: item.version,
      raw: item,
    },
  }));
  const ids = new Set(nodes.map((node) => node.id));
  const edges = snapshot.links
    .filter((link) => ids.has(link.source_id) && ids.has(link.target_ref))
    .map((link) => ({
      id: link.id,
      source: link.source_id,
      target: link.target_ref,
      label: SHORT[link.name] || ontology?.relations?.[link.name]?.label || link.name,
      type: "smoothstep",
      markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: "#98a2b3" },
      style: { stroke: "#98a2b3", strokeWidth: 1.25 },
      labelBgPadding: [4, 2],
      labelBgBorderRadius: 3,
      data: link,
    }));
  return { nodes, edges };
}

function Canvas({ workId, snapshot }) {
  const ontology = useOntology();
  const flow = useReactFlow();
  const [nodes, setNodes] = useState([]);
  const [edges, setEdges] = useState([]);
  const [selected, setSelected] = useState(null);
  const pending = useRef({});
  const timer = useRef(null);
  const signature = useMemo(
    () => JSON.stringify([snapshot.entities.map((e) => [e.id, e.updated_at]), snapshot.assets.map((a) => a.id), snapshot.links.map((l) => l.id)]),
    [snapshot],
  );
  const loaded = useRef(false);

  useEffect(() => {
    const graph = buildGraph(snapshot, ontology.data, false);
    setNodes((current) => {
      // Keep positions the user is dragging right now.
      const byId = Object.fromEntries(current.map((node) => [node.id, node]));
      return graph.nodes.map((node) => (byId[node.id] && pending.current[node.id] ? { ...node, position: byId[node.id].position } : node));
    });
    setEdges(graph.edges);
    if (!loaded.current && graph.nodes.length) {
      loaded.current = true;
      requestAnimationFrame(() => flow.fitView({ padding: 0.15, maxZoom: 1.1 }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature, ontology.data]);

  const save = useCallback(() => {
    const positions = pending.current;
    pending.current = {};
    if (!Object.keys(positions).length) return;
    api.post(`/api/works/${workId}/layout`, { positions }).catch((error) => toast.error("布局没有保存", error.message));
  }, [workId]);

  const onNodesChange = useCallback(
    (changes) => {
      setNodes((current) => applyNodeChanges(changes, current));
      for (const change of changes) {
        if (change.type === "position" && change.position && !String(change.id).startsWith("asset:")) {
          pending.current[change.id] = { x: Math.round(change.position.x), y: Math.round(change.position.y) };
        }
      }
    },
    [],
  );

  const onNodeDragStop = useCallback(() => {
    clearTimeout(timer.current);
    timer.current = setTimeout(save, 400);
  }, [save]);

  const tidy = () => {
    const graph = buildGraph(snapshot, ontology.data, true);
    setNodes(graph.nodes);
    for (const node of graph.nodes) {
      if (!node.data.asset) pending.current[node.id] = { x: Math.round(node.position.x), y: Math.round(node.position.y) };
    }
    save();
    requestAnimationFrame(() => flow.fitView({ padding: 0.15, maxZoom: 1.1, duration: 300 }));
    toast.success("已重新排布并保存");
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
        <div className="absolute left-3 top-3 z-10 flex gap-1.5">
          <Button size="xs" variant="outline" onClick={tidy}>
            <LayoutGrid />
            整理布局
          </Button>
          <Button size="xs" variant="outline" onClick={() => flow.fitView({ padding: 0.15, duration: 300 })}>
            <Maximize />
            适应画布
          </Button>
        </div>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onNodeDragStop={onNodeDragStop}
          onNodeClick={(_event, node) => setSelected(node.id)}
          onPaneClick={() => setSelected(null)}
          nodesConnectable={false}
          edgesFocusable={false}
          minZoom={0.15}
          maxZoom={2}
          colorMode="dark"
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={20} size={1} color="#4e4e4e" />
          <Controls showInteractive={false} position="bottom-left" />
          <MiniMap
            pannable
            zoomable
            className="!hidden sm:!block"
            bgColor="#171718"
            maskColor="rgba(23,23,24,0.72)"
            nodeColor={(node) => entitySlotColor(node.data.type)}
          />
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
            <div>
              <p className="mb-1 text-xs font-medium text-muted-foreground">数据</p>
              <JsonView value={selectedItem.raw.data} maxHeight="16rem" />
            </div>
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

export default function WorkGraph(props) {
  return (
    <ReactFlowProvider>
      <Canvas {...props} />
    </ReactFlowProvider>
  );
}
