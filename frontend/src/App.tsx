import { Navigate, Route, Routes } from 'react-router-dom'
import AppLayout from './components/AppLayout'
import CollectPage from './pages/CollectPage'
import JobsPage from './pages/JobsPage'
import PoolPage from './pages/PoolPage'
import SettingsPage from './pages/SettingsPage'
import SourcesPage from './pages/SourcesPage'

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<Navigate to="/collect" replace />} />
        <Route path="/collect" element={<CollectPage />} />
        <Route path="/pool" element={<PoolPage />} />
        <Route path="/feed" element={<Navigate to="/pool?tab=material" replace />} />
        <Route path="/digests" element={<Navigate to="/pool?tab=outputs&kind=digest" replace />} />
        <Route path="/articles" element={<Navigate to="/pool?tab=outputs&kind=article" replace />} />
        <Route path="/sources" element={<SourcesPage />} />
        <Route path="/jobs" element={<JobsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/collect" replace />} />
      </Route>
    </Routes>
  )
}
