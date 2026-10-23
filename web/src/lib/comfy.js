/**
 * Official ComfyUI dark palette (Comfy-Org/ComfyUI_frontend src/assets/palettes/dark.json)
 * and the slot colors the design requires on workflow steps.
 * Hex values are the source of truth for the structural UI test.
 */

export const COMFY_DARK = {
  canvas: "#202020",
  page: "#171718",
  panel: "#353535",
  panelAlt: "#262729",
  text: "#ffffff",
  border: "#4e4e4e",
  primary: "#0b8ce9",
  menu: "#171718",
  menuSecondary: "#303030",
  input: "#222222",
  muted: "#8a8a8a",
  node: "#353535",
  nodeTitle: "#999999",
  clearCanvas: "#141414",
};

export const SLOT_COLORS = {
  IMAGE: "#64B5F6",
  MODEL: "#B39DDB",
  LATENT: "#FF9CF9",
  VAE: "#FF6E6E",
  CONDITIONING: "#FFA931",
  MASK: "#81C784",
};

/** Workflow node kinds mapped onto ComfyUI slot colors. Graph and step list share this. */
export const KIND_SLOT = {
  image: "IMAGE",
  video: "LATENT",
  llm: "CONDITIONING",
  tts: "MASK",
  music: "MASK",
  check: "MASK",
  edit: "VAE",
  ffmpeg: "VAE",
  gate: "VAE",
  pull: "IMAGE",
  inspect: "IMAGE",
  frame: "IMAGE",
};

export function slotOf(kind) {
  return KIND_SLOT[kind] || "MODEL";
}

export function slotColor(kind) {
  return SLOT_COLORS[slotOf(kind)] || SLOT_COLORS.MODEL;
}

/** Entity types on the audit relation graph, also drawn from slot colors. */
export const ENTITY_SLOT = {
  Shot: "LATENT",
  Clip: "VAE",
  Reference: "IMAGE",
  Style: "MODEL",
  Camera: "MODEL",
  Subject: "CONDITIONING",
  Appearance: "CONDITIONING",
  Place: "IMAGE",
  Line: "MASK",
  Voice: "MASK",
  Detail: "MASK",
  Beat: "CONDITIONING",
  Observation: "MASK",
  Edit: "VAE",
};

export function entitySlotColor(type) {
  return SLOT_COLORS[ENTITY_SLOT[type] || "MODEL"] || SLOT_COLORS.MODEL;
}
