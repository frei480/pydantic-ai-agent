import React from "react";
import ReactDOM from "react-dom/client";
import AdminPage from "./AdminPage";
import App from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {window.location.pathname === "/admin" ? <AdminPage /> : <App />}
  </React.StrictMode>,
);
