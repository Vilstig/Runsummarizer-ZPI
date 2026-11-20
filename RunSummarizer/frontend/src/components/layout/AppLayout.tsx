import React from 'react';
import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { Header } from './Header';
import { BottomNav } from './BottomNav';
import { RouteErrorBoundary } from '../common/ErrorBoundary';

export const AppLayout: React.FC = () => {
  return (
    <div className="flex min-h-screen bg-background text-foreground antialiased selection:bg-[#FC5200] selection:text-white">
      {/* Sidebar Navigation (Desktop only: md:flex) */}
      <Sidebar />

      {/* Main Workspace Column */}
      <div className="flex flex-1 flex-col overflow-hidden min-w-0">
        <Header />

        <main className="flex-1 overflow-y-auto p-3.5 sm:p-6 lg:p-8 pb-28 md:pb-8">
          <div className="mx-auto max-w-6xl">
            <RouteErrorBoundary>
              <Outlet />
            </RouteErrorBoundary>
          </div>
        </main>
      </div>

      {/* Ergonomic Mobile Bottom Navigation Bar (md:hidden) */}
      <BottomNav />
    </div>
  );
};
