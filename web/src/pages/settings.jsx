import { useState } from "react";
import { useSearchParams } from "react-router";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader, useDocumentTitle } from "@/components/common";
import { api } from "@/lib/api";
import { ACCOUNT_EXAMPLE, verifyAccount } from "@/lib/v3-actions";
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

export function AccountVerifyCard({ post = api.post }) {
  const [token, setToken] = useState("");
  const [result, setResult] = useState(null);
  const onVerify = async () => {
    try {
      setResult(await verifyAccount(token, post));
    } catch (error) {
      setResult({ status: "失败", error: error.message, next: "对照示例检查密钥和地址" });
    }
  };
  return (
    <form className="mb-4 rounded-md border border-[#303030] p-3" data-testid="account-verify" onSubmit={(event) => event.preventDefault()}>
      <p className="text-sm font-medium">账号验证</p>
      <label className="mt-2 block text-xs text-[#aaa]" htmlFor="account-token">
        填写
        <input id="account-token" name="token" type="password" value={token} onChange={(event) => setToken(event.target.value)} className="mt-1 w-full rounded border border-[#444] bg-transparent px-2 py-1" autoComplete="off" />
      </label>
      <p className="mt-2 text-xs text-[#888]">示例：{ACCOUNT_EXAMPLE}</p>
      <button type="button" className="mt-2 rounded bg-[#0b8ce9] px-3 py-1 text-sm text-white" data-testid="verify-button" onClick={onVerify}>
        验证
      </button>
      {result ? <p data-testid="verify-result">{result.status}{result.error ? `：${result.error}` : ""}{result.next ? `。下一步：${result.next}` : ""}</p> : null}
    </form>
  );
}

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
      <AccountVerifyCard />
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
