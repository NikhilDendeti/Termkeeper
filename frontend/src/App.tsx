import { Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import AboutPage from "./pages/AboutPage";
import ContractDetailPage from "./pages/ContractDetailPage";
import ContractListPage from "./pages/ContractListPage";
import EvaluationPage from "./pages/EvaluationPage";
import GuardrailPage from "./pages/GuardrailPage";
import UploadPage from "./pages/UploadPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<ContractListPage />} />
        <Route path="/contracts/:id" element={<ContractDetailPage />} />
        <Route path="/upload" element={<UploadPage />} />
        <Route path="/guardrail" element={<GuardrailPage />} />
        <Route path="/evaluation" element={<EvaluationPage />} />
        <Route path="/about" element={<AboutPage />} />
      </Route>
    </Routes>
  );
}
