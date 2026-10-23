import { useSearchParams } from "react-router";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader, useDocumentTitle } from "@/components/common";
import { useSession } from "@/lib/session";
import ProvidersTab from "@/pages/settings/providers";
import PoolsTab from "@/pages/settings/pools";
import UsersTab from "@/pages/settings/users";
import KeysTab from "@/pages/settings/keys";
import DevicesTab from "@/pages/settings/devices";
import SystemTab from "@/pages/settings/system";
import ToolsTab from "@/pages/settings/tools";
import AccountTab from "@/pages/settings/account";

const TABS = [
  { value: "providers", label: "供应商", perm: "admin", Component: ProvidersTab },
  { value: "pools", label: "资源池", perm: "queue:read", Component: PoolsTab },
  { value: "users", label: "用户", perm: "admin", Component: UsersTab },
  { value: "keys", label: "API 密钥", perm: "admin", Component: KeysTab },
  { value: "devices", label: "设备", Component: DevicesTab },
  { value: "system", label: "系统", perm: "admin", Component: SystemTab },
  { value: "tools", label: "工具下载", Component: ToolsTab },
  { value: "account", label: "我的账号", Component: AccountTab },
];

export default function SettingsPage() {
  const { can } = useSession();
  const [params, setParams] = useSearchParams();
  const tabs = TABS.filter((tab) => !tab.perm || can(tab.perm));
  const requested = params.get("tab");
  const tab = tabs.find((item) => item.value === requested)?.value || tabs[0].value;
  useDocumentTitle(`设置 · ${tabs.find((item) => item.value === tab)?.label}`);
  return (
    <div>
      <PageHeader title="设置" description={can("admin") ? "供应商、资源池、账号、密钥与系统开关。" : "你的设备、工具下载和账号。"} />
      <Tabs value={tab} onValueChange={(value) => setParams({ tab: value }, { replace: true })}>
        <TabsList>
          {tabs.map((item) => (
            <TabsTrigger key={item.value} value={item.value}>
              {item.label}
            </TabsTrigger>
          ))}
        </TabsList>
        {tabs.map(({ value, Component }) => (
          <TabsContent key={value} value={value}>
            {value === tab ? <Component /> : null}
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}
