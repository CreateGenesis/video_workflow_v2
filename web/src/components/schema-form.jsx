import { useRef, useState } from "react";
import { ImagePlus, Loader2, X } from "lucide-react";
import { Input, Select, Textarea } from "@/components/ui/input";
import { Field } from "@/components/ui/label";
import { Switch } from "@/components/ui/misc";
import { toast } from "@/components/ui/toast";
import { TagInput } from "@/components/common";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

/** Field order: required first, then the schema's own order. */
export function schemaFields(schema) {
  const properties = schema?.properties || {};
  const required = new Set(schema?.required || []);
  return Object.entries(properties).map(([name, prop]) => ({ name, prop, required: required.has(name) }));
}

export function isUpload(prop) {
  return prop?.format === "asset-upload" || (prop?.type === "array" && prop?.items?.format === "asset-upload");
}

export function emptyValue(prop) {
  if (prop.default !== undefined) return prop.default;
  if (prop.type === "array") return [];
  if (prop.type === "boolean") return false;
  if (prop.type === "number" || prop.type === "integer") return "";
  if (prop.type === "object") return {};
  return "";
}

export function initialValues(schema) {
  return Object.fromEntries(schemaFields(schema).map(({ name, prop }) => [name, emptyValue(prop)]));
}

/** Turn form state into the inputs object the server validates (drops empty optional values). */
export function toInputs(schema, values) {
  const out = {};
  for (const { name, prop, required } of schemaFields(schema)) {
    let value = values[name];
    if (prop.type === "number" || prop.type === "integer") {
      if (value === "" || value === null || value === undefined) {
        if (!required) continue;
      } else value = Number(value);
    }
    if (typeof value === "string" && !value.trim() && !required) continue;
    if (Array.isArray(value) && !value.length && !required) continue;
    out[name] = value;
  }
  return out;
}

export function validate(schema, values) {
  const errors = {};
  for (const { name, prop, required } of schemaFields(schema)) {
    const value = values[name];
    const title = prop.title || name;
    if (prop.type === "array") {
      const list = Array.isArray(value) ? value : [];
      if (required && !list.length) errors[name] = `请填写${title}`;
      else if (prop.minItems && list.length && list.length < prop.minItems) errors[name] = `至少 ${prop.minItems} 项`;
      else if (prop.maxItems && list.length > prop.maxItems) errors[name] = `最多 ${prop.maxItems} 项`;
      else if (required && prop.minItems && list.length < prop.minItems) errors[name] = `至少 ${prop.minItems} 项`;
    } else if (prop.type === "number" || prop.type === "integer") {
      if (required && (value === "" || value === undefined)) errors[name] = `请填写${title}`;
      else if (value !== "" && value !== undefined) {
        const number = Number(value);
        if (!Number.isFinite(number)) errors[name] = "请输入数字";
        else if (prop.type === "integer" && !Number.isInteger(number)) errors[name] = "请输入整数";
        else if (prop.minimum !== undefined && number < prop.minimum) errors[name] = `不能小于 ${prop.minimum}`;
        else if (prop.maximum !== undefined && number > prop.maximum) errors[name] = `不能大于 ${prop.maximum}`;
      }
    } else if (prop.type === "string" || !prop.type) {
      const text = typeof value === "string" ? value : "";
      if (required && !text.trim()) errors[name] = `请填写${title}`;
      else if (prop.maxLength && text.length > prop.maxLength) errors[name] = `最多 ${prop.maxLength} 字`;
      else if (prop.minLength && text.length && text.length < prop.minLength) errors[name] = `至少 ${prop.minLength} 字`;
    }
  }
  return errors;
}

function UploadField({ prop, value, onChange, workspaceId, invalid, id }) {
  const multiple = prop.type === "array";
  const max = multiple ? prop.maxItems || 10 : 1;
  const ids = multiple ? value || [] : value ? [value] : [];
  const [previews, setPreviews] = useState({});
  const [busy, setBusy] = useState(0);
  const input = useRef(null);
  const role = prop["x-role"] || prop.items?.["x-role"];

  const pick = async (files) => {
    const list = Array.from(files || []).slice(0, Math.max(0, max - ids.length));
    if (!list.length) return;
    if (!workspaceId) {
      toast.error("没有选中工作区", "请先在顶部选择工作区");
      return;
    }
    setBusy((count) => count + list.length);
    const added = [];
    for (const file of list) {
      try {
        const row = await api.upload(file, workspaceId, file.name);
        added.push(row.id);
        setPreviews((current) => ({ ...current, [row.id]: { url: row.url, name: file.name, kind: row.kind } }));
      } catch (error) {
        toast.error(`${file.name} 上传失败`, error.message);
      } finally {
        setBusy((count) => count - 1);
      }
    }
    if (added.length) {
      const next = [...ids, ...added];
      onChange(multiple ? next : next[0]);
      toast.success(`已上传 ${added.length} 个文件`);
    }
    if (input.current) input.current.value = "";
  };

  const remove = (artifactId) => {
    const next = ids.filter((item) => item !== artifactId);
    onChange(multiple ? next : next[0] || "");
  };

  return (
    <div className={cn("rounded-md border border-dashed bg-[#222] p-2.5", invalid && "border-red-400 bg-[#3a1717]")}>
      <div className="flex flex-wrap gap-2">
        {ids.map((artifactId) => {
          const preview = previews[artifactId];
          return (
            <div key={artifactId} className="group relative size-24 overflow-hidden rounded-md border bg-card">
              {preview?.url && preview.kind === "image" ? (
                <img src={preview.url} alt={preview.name} className="size-full object-cover" />
              ) : (
                <span className="flex size-full items-center justify-center p-1 text-center text-[11px] text-muted-foreground">{preview?.name || artifactId}</span>
              )}
              <button
                type="button"
                className="absolute right-1 top-1 rounded bg-black/60 p-0.5 text-white opacity-90 hover:opacity-100"
                onClick={() => remove(artifactId)}
                aria-label="移除"
              >
                <X className="size-3.5" />
              </button>
            </div>
          );
        })}
        {busy ? (
          <div className="flex size-24 items-center justify-center rounded-md border bg-card text-muted-foreground">
            <Loader2 className="size-5 animate-spin" />
          </div>
        ) : null}
        {ids.length < max ? (
          <button
            type="button"
            id={id}
            onClick={() => input.current?.click()}
            className="flex size-24 flex-col items-center justify-center gap-1 rounded-md border bg-card text-[12px] text-muted-foreground hover:border-primary hover:text-primary"
          >
            <ImagePlus className="size-5" />
            上传
          </button>
        ) : null}
      </div>
      <p className="mt-1.5 text-xs text-muted-foreground">
        {role ? `参考用途：${role}。` : ""}
        {multiple ? `可上传 ${prop.minItems || 0}–${max} 个文件。` : "上传 1 个文件。"}
      </p>
      <input ref={input} type="file" accept="image/*,video/*,audio/*" multiple={multiple} hidden onChange={(event) => pick(event.target.files)} />
    </div>
  );
}

function JsonField({ value, onChange, invalid }) {
  const [text, setText] = useState(() => JSON.stringify(value ?? null, null, 2));
  const [bad, setBad] = useState(false);
  return (
    <Textarea
      className="font-mono text-xs"
      rows={4}
      value={text}
      aria-invalid={bad || invalid || undefined}
      onChange={(event) => {
        setText(event.target.value);
        try {
          onChange(JSON.parse(event.target.value));
          setBad(false);
        } catch {
          setBad(true);
        }
      }}
    />
  );
}

export function SchemaField({ name, prop, required, value, onChange, error, workspaceId, idPrefix = "f" }) {
  const id = `${idPrefix}-${name}`;
  const title = prop.title || name;
  const invalid = Boolean(error);
  let control;
  let hint = prop.description;
  if (isUpload(prop)) {
    control = <UploadField prop={prop} value={value} onChange={onChange} workspaceId={workspaceId} invalid={invalid} id={id} />;
  } else if (prop.enum) {
    control = (
      <Select id={id} value={value ?? ""} onChange={(event) => onChange(event.target.value)} placeholder={required ? undefined : "不选"} options={prop.enum.map((item) => ({ value: item, label: String(item) }))} />
    );
  } else if (prop.type === "boolean") {
    control = (
      <div className="flex h-9 items-center">
        <Switch id={id} checked={Boolean(value)} onCheckedChange={onChange} />
      </div>
    );
  } else if (prop.type === "number" || prop.type === "integer") {
    control = (
      <Input
        id={id}
        type="number"
        inputMode={prop.type === "integer" ? "numeric" : "decimal"}
        step={prop.type === "integer" ? 1 : "any"}
        min={prop.minimum}
        max={prop.maximum}
        value={value ?? ""}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={invalid || undefined}
        className="tnum"
      />
    );
  } else if (prop.type === "array" && (!prop.items || prop.items.type === "string")) {
    control = <TagInput id={id} value={value || []} onChange={onChange} max={prop.maxItems} invalid={invalid} />;
    hint = hint || `输入后按回车添加${prop.maxItems ? `，最多 ${prop.maxItems} 项` : ""}`;
  } else if (prop.type === "array" || prop.type === "object") {
    control = <JsonField value={value} onChange={onChange} invalid={invalid} />;
    hint = hint || "JSON 格式";
  } else if (prop.format === "multiline" || (prop.maxLength || 0) > 200) {
    const length = (value || "").length;
    control = (
      <div className="relative">
        <Textarea id={id} rows={prop.maxLength > 1000 ? 7 : 4} value={value || ""} onChange={(event) => onChange(event.target.value)} aria-invalid={invalid || undefined} />
        {prop.maxLength ? (
          <span className={cn("tnum pointer-events-none absolute bottom-1.5 right-2.5 text-[11px] text-muted-foreground", length > prop.maxLength && "text-[#ff4444]")}>
            {length}/{prop.maxLength}
          </span>
        ) : null}
      </div>
    );
  } else {
    control = <Input id={id} value={value || ""} onChange={(event) => onChange(event.target.value)} maxLength={prop.maxLength ? prop.maxLength + 50 : undefined} aria-invalid={invalid || undefined} />;
  }
  return (
    <Field label={title} htmlFor={id} required={required} error={error} hint={hint}>
      {control}
    </Field>
  );
}

export function SchemaForm({ schema, values, onChange, errors = {}, workspaceId, idPrefix }) {
  const fields = schemaFields(schema);
  if (!fields.length) return <p className="text-[13px] text-muted-foreground">这个工作流不需要输入。</p>;
  return (
    <div className="grid gap-4">
      {fields.map(({ name, prop, required }) => (
        <SchemaField
          key={name}
          name={name}
          prop={prop}
          required={required}
          value={values[name]}
          error={errors[name]}
          workspaceId={workspaceId}
          idPrefix={idPrefix}
          onChange={(next) => onChange({ ...values, [name]: next })}
        />
      ))}
    </div>
  );
}
