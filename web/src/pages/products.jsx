import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { PageHeader, useDocumentTitle } from "@/components/common";
import { api, qs } from "@/lib/api";
export default function ProductsPage() {
  const [q, setQ] = useState("");
  useDocumentTitle("产物");
  const products = useQuery({
    queryKey: ["products", q],
    queryFn: () => api.get(`/api/products${qs({ q })}`),
  });
  const items = products.data?.items || [];
  return (
    <div>
      <PageHeader title="产物" description="按提示词搜索生成结果。未验收的生图和首帧、末帧不进素材库。" />
      <label className="mb-3 flex items-center gap-2" htmlFor="product-search">
        <Search className="size-4" />
        <Input id="product-search" value={q} onChange={(event) => setQ(event.target.value)} placeholder="搜索提示词" />
      </label>
      <ul className="space-y-2">
        {items.map((item) => (
          <li key={item.id} className="rounded border border-[#303030] p-3 text-sm">
            <p>{item.prompt}</p>
            <p className="text-xs text-[#888]">{item.model} · {item.kind}</p>
          </li>
        ))}
      </ul>
      {!items.length && products.data ? <p className="text-sm text-[#888]">没有匹配的产物。</p> : null}
    </div>
  );
}
