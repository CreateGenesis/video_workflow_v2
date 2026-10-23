import { graphlib, layout } from "@dagrejs/dagre";

/**
 * Layered layout (dagre) shared by the step graph and the relation graph: ranks follow the arrows,
 * node order inside a rank is chosen to keep crossings down. Returns top-left positions for React Flow.
 */
export function layered(nodes, edges, { direction = "LR", nodesep = 28, ranksep = 72 } = {}) {
  const graph = new graphlib.Graph({ multigraph: true });
  graph.setGraph({ rankdir: direction, nodesep, ranksep, edgesep: 12, marginx: 0, marginy: 0, ranker: "network-simplex" });
  graph.setDefaultEdgeLabel(() => ({}));
  for (const node of nodes) graph.setNode(node.id, { width: node.width, height: node.height });
  edges.forEach((edge, index) => {
    if (graph.hasNode(edge.source) && graph.hasNode(edge.target) && edge.source !== edge.target) {
      graph.setEdge(edge.source, edge.target, { weight: edge.weight ?? 1, minlen: edge.minlen ?? 1 }, String(index));
    }
  });
  layout(graph);
  const positions = {};
  for (const node of nodes) {
    const placed = graph.node(node.id);
    positions[node.id] = { x: Math.round(placed.x - node.width / 2), y: Math.round(placed.y - node.height / 2) };
  }
  const size = graph.graph();
  return { positions, width: size.width || 0, height: size.height || 0 };
}

/** Drop edges already implied by a longer path (a→c when a→b→c), so a pipeline reads as a pipeline. `order` is topological. */
export function transitiveReduction(order, deps) {
  const ancestors = {};
  for (const id of order) {
    const all = new Set();
    for (const parent of deps[id] || []) {
      all.add(parent);
      for (const above of ancestors[parent] || []) all.add(above);
    }
    ancestors[id] = all;
  }
  const reduced = {};
  for (const id of order) {
    const parents = deps[id] || [];
    reduced[id] = parents.filter((parent) => !parents.some((other) => other !== parent && ancestors[other]?.has(parent)));
  }
  return reduced;
}
