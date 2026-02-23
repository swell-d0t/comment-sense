import { DashboardHeader } from "@/components/dashboard/header"
import { StatsGrid } from "@/components/dashboard/stats-grid"
import { RecentAnalysesTable } from "@/components/dashboard/recent-analyses-table"

export default function DashboardPage() {
  return (
    <div className="flex flex-1 flex-col">
      <DashboardHeader />
      <div className="flex flex-1 flex-col gap-6 px-6 py-6">
        <StatsGrid />
        <RecentAnalysesTable />
      </div>
    </div>
  )
}
