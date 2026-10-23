import { useQuery } from "@tanstack/react-query";
import { ErrorState, SkeletonCards } from "@/components/common";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";
import { Pools } from "@/pages/queue";

export default function PoolsTab() {
  const { can } = useSession();
  const queue = useQuery({ queryKey: ["queue"], queryFn: () => api.get("/api/queue") });
  if (queue.isLoading) return <SkeletonCards count={6} />;
  if (queue.isError) return <ErrorState error={queue.error} retry={queue.refetch} />;
  return (
    <div className="space-y-3">
      <p className="text-[13px] text-muted-foreground">
        每个资源池有固定数量的槽位，异步任务在等待供应商出结果时也占着槽位，所以并发上限就是真实的同时执行数。
        {can("queue:manage") ? "用开关暂停或恢复领取，点铅笔修改并发。" : "只有管理员可以修改。"}
      </p>
      <Pools pools={queue.data.pools} instances={queue.data.instances} canManage={can("queue:manage")} />
    </div>
  );
}
