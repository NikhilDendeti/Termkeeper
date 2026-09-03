import { Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import ContractDetailPage from "./pages/ContractDetailPage";
import ContractListPage from "./pages/ContractListPage";
import GuardrailPage from "./pages/GuardrailPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<ContractListPage />} />
        <Route path="/contracts/:id" element={<ContractDetailPage />} />
        <Route path="/guardrail" element={<GuardrailPage />} />
      </Route>
    </Routes>
  );
}
