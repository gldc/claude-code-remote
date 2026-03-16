import { createContext, useContext, useEffect, useState } from "react";
import { getAnalytics } from "./api";

interface AppConfig {
  showCost: boolean;
}

const ConfigContext = createContext<AppConfig>({ showCost: false });

export function useConfig() {
  return useContext(ConfigContext);
}

export function ConfigProvider({ children }: { children: React.ReactNode }) {
  const [config, setConfig] = useState<AppConfig>({ showCost: false });

  useEffect(() => {
    getAnalytics()
      .then((a) => setConfig({ showCost: a.show_cost }))
      .catch(() => {});
  }, []);

  return (
    <ConfigContext.Provider value={config}>{children}</ConfigContext.Provider>
  );
}
