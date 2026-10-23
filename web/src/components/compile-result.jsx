import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { TBody, THead, Table } from "@/components/ui/misc";
import { Collapsible, CopyButton, JsonView, Money, Notice } from "@/components/common";
import { itemLabel } from "@/lib/format";
import { PRICING_UNIT } from "@/lib/labels";

export function EstimateTable({ breakdown }) {
  if (!breakdown?.length) return <p className="text-[13px] text-muted-foreground">没有计费步骤。</p>;
  return (
    <div className="overflow-hidden rounded-md border">
      <Table>
        <THead>
          <tr>
            <th>步骤</th>
            <th>条目</th>
            <th>供应商</th>
            <th>用量</th>
            <th className="text-right">金额</th>
          </tr>
        </THead>
        <TBody>
          {breakdown.map((row, index) => (
            <tr key={index}>
              <td className="font-medium">{row.label || row.node}</td>
              <td className="text-muted-foreground">{row.item !== "" ? itemLabel(row.item) : "—"}</td>
              <td className="text-[13px] text-muted-foreground">{row.provider}</td>
              <td className="tnum text-[13px]">
                {(row.usage || []).map((usage) => `${usage.quantity} ${PRICING_UNIT[usage.unit] || usage.unit}`).join("，") || "—"}
              </td>
              <td className="text-right">
                <Money value={row.yuan} />
              </td>
            </tr>
          ))}
        </TBody>
      </Table>
    </div>
  );
}

export function CompileResult({ result, budget }) {
  const over = budget && result.estimate_yuan > budget;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-x-6 gap-y-2">
        <div>
          <p className="text-[13px] text-muted-foreground">估算花费</p>
          <p className={`tnum text-2xl font-semibold ${over ? "text-[#ff9c9c]" : ""}`}>
            <Money value={result.estimate_yuan} digits={2} />
          </p>
        </div>
        {budget ? (
          <div>
            <p className="text-[13px] text-muted-foreground">预算上限</p>
            <p className="tnum text-lg font-medium">
              <Money value={budget} digits={2} />
            </p>
          </div>
        ) : null}
        <div>
          <p className="text-[13px] text-muted-foreground">最终提示词</p>
          <p className="tnum text-lg font-medium">{result.prompts?.length || 0} 条</p>
        </div>
      </div>
      {over ? <Notice tone="warn" icon={AlertTriangle}>估算超过预算上限，服务端会拒绝发起这个运行。</Notice> : null}
      {result.problems?.length ? (
        <div className="space-y-1 rounded-md border border-[#6a2424] bg-[#3a1717] px-3 py-2 text-[13px] text-[#ff9c9c]">
          {result.problems.map((problem, index) => (
            <p key={index} className="flex items-start gap-1.5">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
              {typeof problem === "string" ? problem : JSON.stringify(problem)}
            </p>
          ))}
        </div>
      ) : (
        <Notice tone="success" icon={CheckCircle2}>编译通过，没有发现问题。</Notice>
      )}
      <div>
        <p className="mb-1.5 text-[13px] font-medium">逐项估算</p>
        <EstimateTable breakdown={result.breakdown} />
      </div>
      <div className="space-y-2">
        <p className="text-[13px] font-medium">每一条提示词</p>
        {(result.prompts || []).map((prompt, index) => (
          <Collapsible
            key={`${prompt.node}-${prompt.item}-${index}`}
            defaultOpen={index === 0}
            title={`${prompt.node} · ${itemLabel(prompt.item)}${prompt.title ? ` · ${prompt.title}` : ""}`}
            extra={
              <span className="flex items-center gap-2 text-xs font-normal text-muted-foreground">
                {prompt.duration ? <span className="tnum">{prompt.duration} 秒</span> : null}
                {prompt.resolution ? <span>{prompt.resolution}</span> : null}
                {prompt.warnings?.length ? <span className="text-[#ffa931]">{prompt.warnings.length} 条警告</span> : null}
              </span>
            }
          >
            <div className="space-y-2">
              {prompt.warnings?.length ? (
                <ul className="space-y-1 text-[13px] text-[#ffa931]">
                  {prompt.warnings.map((warning, i) => (
                    <li key={i} className="flex items-start gap-1.5">
                      <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
                      {warning}
                    </li>
                  ))}
                </ul>
              ) : null}
              {prompt.references?.length ? <p className="text-xs text-muted-foreground">参考图：{prompt.references.join("、")}</p> : null}
              <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-md bg-[#222] p-3 text-[13px] leading-relaxed text-[#ddd]" style={{ fontFamily: "inherit" }}>
                {prompt.prompt}
              </pre>
              <CopyButton value={prompt.prompt} label="复制提示词" />
            </div>
          </Collapsible>
        ))}
      </div>
      {result.llm && Object.keys(result.llm).length ? (
        <Collapsible title="大模型步骤输出（来自试跑样例）">
          <JsonView value={result.llm} />
        </Collapsible>
      ) : null}
    </div>
  );
}
