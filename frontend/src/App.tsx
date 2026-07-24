import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import { DiscoverPage } from '@/features/discover/DiscoverPage'
import { FollowingPage } from '@/features/following/FollowingPage'
import { BookPage } from '@/features/book/BookPage'
import { PerformancePage } from '@/features/performance/PerformancePage'
import { ActivityPage } from '@/features/activity/ActivityPage'
import { SettingsPage } from '@/features/settings/SettingsPage'

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/discover" replace />} />
        <Route path="/discover" element={<DiscoverPage />} />
        <Route path="/following" element={<FollowingPage />} />
        <Route path="/book" element={<BookPage />} />
        <Route path="/performance" element={<PerformancePage />} />
        <Route path="/activity" element={<ActivityPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/discover" replace />} />
      </Route>
    </Routes>
  )
}
