import React, { Suspense } from 'react';
import { createBrowserRouter, Navigate } from 'react-router-dom';
import { ProtectedRoute } from '@/components/common/ProtectedRoute';
import { AppLayout } from '@/components/layout/AppLayout';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';

// Direct imports for core entry pages
import SignInPage from '@/pages/SignInPage';
import SignUpPage from '@/pages/SignUpPage';
import HomePage from '@/pages/HomePage';
import ActivityListPage from '@/pages/ActivityListPage';
import OAuthCallbackPage from '@/pages/OAuthCallbackPage';

// Performance: Code-splitting (React.lazy) for heavy charting & deep-view pages
const ActivityDetailPage = React.lazy(
  () => import('@/pages/ActivityDetailPage')
);
const CalendarPage = React.lazy(() => import('@/pages/CalendarPage'));
const SettingsPage = React.lazy(() => import('@/pages/SettingsPage'));
const TrendsPage = React.lazy(() => import('@/pages/TrendsPage'));
const ActivitySearchPage = React.lazy(
  () => import('@/pages/ActivitySearchPage')
);

const SuspenseWrapper: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => (
  <Suspense
    fallback={
      <div className="flex h-[450px] w-full items-center justify-center">
        <LoadingSpinner size="lg" label="Loading..." />
      </div>
    }
  >
    {children}
  </Suspense>
);

export const router = createBrowserRouter([
  // Public authentication routes
  {
    path: '/sign-in/*',
    element: <SignInPage />,
  },
  {
    path: '/sign-up/*',
    element: <SignUpPage />,
  },
  {
    path: '/oauth/callback',
    element: <OAuthCallbackPage />,
  },

  // Authenticated workspace routes wrapped by ProtectedRoute & AppLayout
  {
    element: <ProtectedRoute />,
    children: [
      {
        element: <AppLayout />,
        children: [
          {
            path: '/',
            element: <Navigate to="/home" replace />,
          },
          {
            path: '/home',
            element: <HomePage />,
          },
          {
            path: '/calendar',
            element: (
              <SuspenseWrapper>
                <CalendarPage />
              </SuspenseWrapper>
            ),
          },
          {
            path: '/activities',
            element: <ActivityListPage />,
          },
          {
            path: '/activities/:activityId',
            element: (
              <SuspenseWrapper>
                <ActivityDetailPage />
              </SuspenseWrapper>
            ),
          },
          {
            path: '/search',
            element: (
              <SuspenseWrapper>
                <ActivitySearchPage />
              </SuspenseWrapper>
            ),
          },
          {
            path: '/trends',
            element: (
              <SuspenseWrapper>
                <TrendsPage />
              </SuspenseWrapper>
            ),
          },
          {
            path: '/settings',
            element: (
              <SuspenseWrapper>
                <SettingsPage />
              </SuspenseWrapper>
            ),
          },
          {
            path: '*',
            element: <Navigate to="/home" replace />,
          },
        ],
      },
    ],
  },
]);

