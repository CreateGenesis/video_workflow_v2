// Every raw value the server sends is shown to people through these maps: a Chinese label plus a tone.

export const TASK_STATUS = {
  blocked: { label: "等待上游", tone: "gray" },
  ready: { label: "排队中", tone: "sky" },
  leased: { label: "已领取", tone: "blue" },
  running: { label: "执行中", tone: "blue" },
  submitting: { label: "提交中", tone: "blue" },
  submitted: { label: "生成中", tone: "blue" },
  waiting: { label: "待审批", tone: "amber" },
  needs_attention: { label: "需要处理", tone: "orange" },
  succeeded: { label: "已完成", tone: "green" },
  failed: { label: "失败", tone: "red" },
  canceled: { label: "已取消", tone: "gray" },
};

export const RUN_STATUS = {
  running: { label: "进行中", tone: "blue" },
  waiting: { label: "等待处理", tone: "amber" },
  paused: { label: "已暂停", tone: "violet" },
  succeeded: { label: "已完成", tone: "green" },
  failed: { label: "失败", tone: "red" },
  canceled: { label: "已取消", tone: "gray" },
};

export const RUN_MODE = {
  production: { label: "生产", tone: "gray" },
  trial: { label: "试跑", tone: "violet" },
  "dryrun-llm": { label: "大模型试跑", tone: "violet" },
};

export const VERSION_STATUS = {
  draft: { label: "草稿", tone: "gray" },
  published: { label: "已发布", tone: "green" },
  retired: { label: "已下线", tone: "red" },
};

export const DEVICE_STATUS = {
  pending: { label: "待批准", tone: "amber" },
  approved: { label: "已批准", tone: "green" },
  revoked: { label: "已吊销", tone: "gray" },
  expired: { label: "已过期", tone: "gray" },
};

export const TASK_KIND = {
  llm: "大模型",
  image: "生图",
  video: "视频",
  tts: "配音",
  music: "配乐",
  check: "检查",
  edit: "剪辑",
  gate: "闸门",
  pull: "拉取",
  inspect: "解析",
  frame: "截帧",
  ffmpeg: "ffmpeg",
};

export const ROLE = { producer: "制作", reviewer: "审计员", admin: "管理员", agent: "agent 设备", service: "服务" };

export const ACTOR_KIND = { user: "用户", device: "设备", apikey: "API 密钥", worker: "执行器", system: "系统" };

export const ASSET_KIND = {
  prompt: "提示模板",
  schema: "输出 schema",
  comfy_template: "ComfyUI 模板",
  media: "媒体",
};

export const PROTOCOLS = [
  { value: "openai-chat", label: "OpenAI Chat", kinds: ["llm"] },
  { value: "openai-responses", label: "OpenAI Responses", kinds: ["llm"] },
  { value: "anthropic-messages", label: "Anthropic Messages", kinds: ["llm"] },
  { value: "openai-images", label: "OpenAI Images", kinds: ["image"] },
  { value: "openai-audio", label: "OpenAI Audio", kinds: ["music", "tts"] },
  { value: "autodl-h3", label: "AutoDL H3（按次计费）", kinds: ["video"] },
  { value: "autodl-indextts", label: "AutoDL IndexTTS", kinds: ["tts"] },
  { value: "comfyui", label: "ComfyUI", kinds: ["video", "image", "tts", "music"] },
  { value: "mock", label: "模拟（测试用）", kinds: ["llm", "image", "video", "tts", "music"] },
];

export const PROVIDER_KINDS = ["llm", "image", "video", "tts", "music"];

export const PRICING_UNIT = {
  token_in: "输入 token",
  token_out: "输出 token",
  image: "张",
  video_second: "视频秒",
  gpu_second: "GPU 秒",
  audio_second: "音频秒",
  char: "字",
  call: "次",
};

export const ACTION = {
  "run.create": "发起运行",
  "run.running": "运行恢复",
  "run.succeeded": "运行完成",
  "run.failed": "运行失败",
  "run.canceled": "取消运行",
  "run.pause": "暂停/继续运行",
  "run.rerun_item": "重跑一条",
  "gate.approve": "通过闸门",
  "gate.reject": "驳回闸门",
  "task.create": "创建任务",
  "task.cancel": "取消任务",
  "task.retry": "重试任务",
  "task.priority": "调整优先级",
  "task.approve": "批准任务",
  "task.requery": "重新查询",
  "task.fail": "标记失败",
  "task.resubmit": "强制重提",
  "task.attach": "手动挂接产物",
  "entity.create": "新建实体",
  "entity.update": "修改实体",
  "entity.delete": "删除实体",
  "link.create": "建立关系",
  "link.delete": "删除关系",
  "work.create": "新建作品",
  "work.update": "修改作品",
  "work.archive": "归档作品",
  "note.create": "留审计意见",
  "note.resolve": "关闭审计意见",
  "workflow.draft": "保存工作流草稿",
  "workflow.edit": "修改工作流版本",
  "workflow.publish": "发布工作流",
  "workflow.retire": "下线工作流",
  "check.rerun": "检查触发重跑",
  "device.approve": "批准设备",
  "device.revoke": "吊销设备",
  "device.update": "修改设备",
  "apikey.create": "创建 API 密钥",
  "apikey.revoke": "吊销 API 密钥",
  "user.create": "新建账号",
  "user.update": "修改账号",
  "user.login": "登录",
  "user.password": "修改密码",
  "user.setup": "初始化管理员",
  "settings.update": "修改系统设置",
  "pool.update": "修改资源池",
  "provider.save": "保存供应商",
  "provider.delete": "删除供应商",
  "workspace.create": "新建工作区",
  "workspace.rename": "重命名工作区",
  "asset.version": "素材新版本",
};

export const ATTENTION_ACTIONS = {
  approve: { label: "批准执行", perm: "workflows:publish", spends: true },
  requery: { label: "重新查询", perm: "tasks:resolve" },
  fail: { label: "标记失败", perm: "tasks:resolve", danger: true },
  resubmit: { label: "强制重提", perm: "tasks:resolve", spends: true, danger: true },
};

export function statusOf(map, value) {
  return map[value] || { label: value || "未知", tone: "gray" };
}

export function kindLabel(kind) {
  return TASK_KIND[kind] || kind || "任务";
}

export function actionLabel(action) {
  if (ACTION[action]) return ACTION[action];
  const [head] = String(action || "").split(".");
  const heads = { task: "任务", run: "运行", gate: "闸门", entity: "实体", workflow: "工作流", asset: "素材" };
  return heads[head] ? `${heads[head]}变更` : action;
}

export const ACTIVE_TASK = ["leased", "running", "submitting", "submitted"];
export const OPEN_TASK = ["blocked", "ready", "waiting", "needs_attention", ...ACTIVE_TASK];
export const TERMINAL_RUN = ["succeeded", "failed", "canceled"];
