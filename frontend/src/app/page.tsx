import RevenueChart from "@/app/components/RevenueChart";
import FileUpload from "@/app/components/FileUpload"; 

export default function Dashboard() {
  return (
    <main className="p-8 bg-gray-50 min-h-screen">
      <div className="max-w-6xl mx-auto">
        <header className="mb-8 border-b pb-4 flex justify-between items-center">
          <div>
            <h1 className="text-3xl font-bold text-gray-900">NexusFlow Intelligence</h1>
            <p className="text-gray-500 mt-1">Predictive Analytics & IT Operations Platform</p>
          </div>
          <span className="px-3 py-1 rounded-full bg-emerald-100 text-emerald-800 text-xs font-semibold">
            Agency Mode: Active
          </span>
        </header>

        <section className="mb-8">
          <h2 className="text-xl font-bold mb-4 text-gray-800">Executive Key Performance Indicators</h2>
          <RevenueChart />
        </section>

        <section>
          <FileUpload />
        </section>
      </div>
    </main>
  );
}