import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageHeader, useDocumentTitle } from "@/components/common";
import { api, qs } from "@/lib/api";

export default function ComicPage() {
  const [episodeId, setEpisodeId] = useState("");
  useDocumentTitle("漫剧缺项");
  const missing = useQuery({
    queryKey: ["comic-missing", episodeId],
    queryFn: () => api.get(`/api/comic/missing${qs({ episode_id: episodeId })}`),
    enabled: Boolean(episodeId),
  });
  const body = missing.data;
  return (
    <div>
      <PageHeader title="漫剧缺项" description="只问平台停在哪一闸门、缺哪一项。" />
      <label className="mb-3 block text-sm" htmlFor="episode-id">
        集 id
        <input
          id="episode-id"
          value={episodeId}
          onChange={(event) => setEpisodeId(event.target.value.trim())}
          className="mt-1 w-full rounded border border-[#444] bg-transparent px-2 py-1"
        />
      </label>
      {body ? (
        <div data-testid="comic-missing">
          <p>停在：{body.stopped_at}</p>
          <p>缺：{(body.missing || []).join("、") || "无"}</p>
        </div>
      ) : null}
    </div>
  );
}
