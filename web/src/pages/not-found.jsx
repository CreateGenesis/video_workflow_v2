import { Link } from "react-router";
import { Compass } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState, useDocumentTitle } from "@/components/common";

export default function NotFound() {
  useDocumentTitle("页面不存在");
  return (
    <EmptyState
      icon={Compass}
      title="没有这个页面"
      description="地址可能写错了，或者页面已经移动。"
      action={
        <Button asChild size="sm">
          <Link to="/">回到工作台</Link>
        </Button>
      }
    />
  );
}
