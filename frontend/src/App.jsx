import { Component } from 'react'
import { Routes, Route } from 'react-router-dom'
import { AppProvider } from './context/AppContext'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Projections from './pages/Projections'
import LineupBuilder from './pages/LineupBuilder'
import Simulator from './pages/Simulator'
import GameCenter from './pages/GameCenter'
import ContestImport from './pages/ContestImport'
import MyContests from './pages/MyContests'
import Backtesting from './pages/Backtesting'

class ErrorBoundary extends Component {
  state = { hasError: false, error: null };

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-gray-950 flex items-center justify-center p-6">
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-8 max-w-md w-full text-center">
            <h2 className="text-lg font-bold text-gray-100 mb-2">Something went wrong</h2>
            <p className="text-sm text-gray-400 mb-4">
              {this.state.error?.message || 'An unexpected error occurred'}
            </p>
            <button
              onClick={() => {
                this.setState({ hasError: false, error: null });
                window.location.hash = '/';
                window.location.reload();
              }}
              className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-500 transition-colors"
            >
              Reload App
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

export default function App() {
  return (
    <ErrorBoundary>
      <AppProvider>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="projections" element={<Projections />} />
            <Route path="lineups" element={<LineupBuilder />} />
            <Route path="simulator" element={<Simulator />} />
            <Route path="games" element={<GameCenter />} />
            <Route path="contests" element={<ContestImport />} />
            <Route path="my-contests" element={<MyContests />} />
            <Route path="backtesting" element={<Backtesting />} />
          </Route>
        </Routes>
      </AppProvider>
    </ErrorBoundary>
  )
}
