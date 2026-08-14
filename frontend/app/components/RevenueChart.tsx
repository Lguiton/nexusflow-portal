"use client";

export default function RevenueChart() {
  const metrics = [
    { label: "Monthly Recurring Revenue (MRR)", value: "$124,500", change: "+14.2%" },
    { label: "Active Enterprise Clients", value: "38", change: "+4 net new" },
    { label: "Average Churn Risk Index", value: "4.1%", change: "-1.8%" },
    { label: "System Uptime SLA", value: "99.98%", change: "Optimal" },
  ];

  const trendData = [
    { month: "Jan", mrr: "$18k", height: "30%" },
    { month: "Feb", mrr: "$24k", height: "40%" },
    { month: "Mar", mrr: "$29k", height: "50%" },
    { month: "Apr", mrr: "$35k", height: "60%" },
    { month: "May", mrr: "$42k", height: "75%" },
    { month: "Jun", mrr: "$48k", height: "85%" },
    { month: "Jul", mrr: "$124k", height: "100%" },
  ];

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {metrics.map((item, idx) => (
          <div key={idx} className="bg-white border border-gray-200 p-5 rounded-xl shadow-xs">
            <p className="text-sm font-medium text-gray-500">{item.label}</p>
            <p className="text-2xl font-bold text-gray-900 mt-2">{item.value}</p>
            <div className="mt-3 flex items-center gap-2">
              <span className="text-xs font-semibold text-emerald-700 bg-emerald-100 px-2 py-0.5 rounded-md">
                {item.change}
              </span>
              <span className="text-xs text-gray-400">vs last month</span>
            </div>
          </div>
        ))}
      </div>

      <div className="bg-white border border-gray-200 p-6 rounded-xl shadow-xs">
        <h3 className="text-lg font-bold text-gray-900 mb-1">MRR Growth Trend</h3>
        <p className="text-sm text-gray-500 mb-6">Historical revenue trajectory across active enterprise cohorts.</p>
        
        <div className="h-48 flex items-end justify-between gap-4 border-b border-gray-100 pb-2 px-2">
          {trendData.map((bar, idx) => (
            <div key={idx} className="flex-1 flex flex-col items-center gap-2 h-full justify-end">
              <span className="text-xs font-semibold text-gray-600">{bar.mrr}</span>
              <div 
                style={{ height: bar.height }} 
                className="w-full bg-emerald-600 hover:bg-emerald-500 transition-all rounded-t-md"
              ></div>
              <span className="text-xs font-medium text-gray-500">{bar.month}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
