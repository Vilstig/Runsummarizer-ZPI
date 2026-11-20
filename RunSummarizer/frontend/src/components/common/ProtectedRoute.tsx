import React from 'react';
import { useAuth } from '@clerk/clerk-react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { LoadingSpinner } from './LoadingSpinner';
import { isMockEnabled, setAuthTokenGetter } from '@/api/client';

/**
 * ProtectedRoute safely handles Clerk's `isLoaded` and `isSignedIn` lifecycle states.
 * While Clerk initializes, a full-screen neutral loader prevents layout thrashing
 * and unauthorized API fetches. When loaded, it wires Clerk's getToken into the API client.
 * In Mock Mode, allows instant preview of all views without third-party auth requirements.
 */
export const ProtectedRoute = () => {
  const { isLoaded, isSignedIn, getToken } = useAuth();
  const location = useLocation();

  React.useEffect(() => {
    if (isLoaded && isSignedIn) {
      setAuthTokenGetter(getToken);
    } else {
      setAuthTokenGetter(null);
    }
  }, [isLoaded, isSignedIn, getToken]);

  if (!isLoaded && !isMockEnabled) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-background">
        <LoadingSpinner size="lg" label="Signing you in..." />
      </div>
    );
  }

  if (!isSignedIn && !isMockEnabled) {
    return <Navigate to="/sign-in" replace state={{ from: location }} />;
  }

  return <Outlet />;
};