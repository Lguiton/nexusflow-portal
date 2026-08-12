"use client";
import { useState } from "react";

export default function FileUpload() {
  const [file, setFile] = useState<File | null>(null);
  const [analysis, setAnalysis] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const handleUpload = async () => {
    if (!file) return;
    setLoading(true);
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await fetch("http://localhost:8000/api/v1/etl/upload", {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      setAnalysis(data.agent_analysis);
    } catch (error) {
      console.error("Upload failed:", error);
    }
    setLoading(false);
  };

  return (
    <div className="p-6 bg-white rounded-xl shadow-sm border border-gray-100 mt-6">
      <h2 className="text-xl font-bold mb-4 text-gray-800">Predictive Churn Analysis</h2>
      <div className="flex gap-4 mb-6 items-center">
        <input type="file" accept=".csv" onChange={(e) => setFile(e.target.files?.[0] || null)} className="border border-gray-300 p-2 rounded-lg text-sm" />
        <button onClick={handleUpload} disabled={!file || loading} className="bg-blue-600 text-white px-6 py-2 rounded-lg font-medium">
          {loading ? "Analyzing..." : "Run AI Analysis"}
        </button>
      </div>
      {analysis && analysis.status === "success" && (
        <div className="border-t border-gray-100 pt-6">
          <div className="bg-red-50 border-l-4 border-red-500 p-4 rounded-r-md mb-6">
            <h3 className="text-red-800 font-bold">⚠️ Executive Insight</h3>
            <p className="text-red-700 text-sm mt-1">{analysis.insight}</p>
          </div>
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-gray-50 text-gray-600 text-sm">
                <th className="p-3 border-b font-medium">Client ID</th>
                <th className="p-3 border-b font-medium">MRR Risk</th>
                <th className="p-3 border-b font-medium">Risk %</th>
              </tr>
            </thead>
            <tbody>
              {analysis.high_risk_clients.map((client: any, idx: number) => (
                <tr key={idx}>
                  <td className="p-3 border-b">{client.client_id}</td>
                  <td className="p-3 border-b text-red-600 font-bold">${client.mrr}</td>
                  <td className="p-3 border-b font-bold text-red-800">{client.churn_risk_percent}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}