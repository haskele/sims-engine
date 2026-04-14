import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Projections from './pages/Projections'
import LineupBuilder from './pages/LineupBuilder'
import Simulator from './pages/Simulator'
import GameCenter from './pages/GameCenter'
import ContestImport from './pages/ContestImport'
import Backtesting from './pages/Backtesting'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="projections" element={<Projections />} />
        <Route path="lineups" element={<LineupBuilder />} />
        <Route path="simulator" element={<Simulator />} />
        <Route path="games" element={<GameCenter />} />
        <Route path="contests" element={<ContestImport />} />
        <Route path="backtesting" element={<Backtesting />} />
      </Route>
    </Routes>
  )
}
