import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { ToastContainer } from "react-toastify";
import App from "./App";
import "./index.css";
import "react-toastify/dist/ReactToastify.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <BrowserRouter>
    <App />
    <ToastContainer
      position="top-right"
      autoClose={3800}
      hideProgressBar={false}
      newestOnTop
      closeOnClick
      pauseOnHover
      draggable
      theme="dark"
      toastStyle={{
        background: "rgba(14, 17, 32, 0.96)",
        color: "#d7d9e1",
        border: "1px solid rgba(122, 131, 255, 0.26)",
      }}
      progressStyle={{
        background: "linear-gradient(90deg,#34c9ff,#7a83ff)",
      }}
    />
  </BrowserRouter>
);
