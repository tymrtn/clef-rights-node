import React from "react";
import { createRoot } from "react-dom/client";
import { RightsNodeApp } from "./ui/RightsNodeApp";
import "./index.css";

const demoMode = import.meta.env.VITE_DEMO_MODE === "true";
const DemoApp = React.lazy(async () => {
  const module = await import("./ui/App");
  return { default: module.App };
});

const root = createRoot(document.getElementById("root")!);
root.render(
  demoMode ? (
    <React.Suspense fallback={<div className="p-8">Loading explicit demo…</div>}>
      <DemoApp />
    </React.Suspense>
  ) : (
    <RightsNodeApp />
  )
);
