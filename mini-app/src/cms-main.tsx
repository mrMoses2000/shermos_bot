import React from "react";
import ReactDOM from "react-dom/client";
import CmsApp from "./cms/App";
import "./styles/index.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <CmsApp />
  </React.StrictMode>
);
