import React from 'react';
import { ErrorBoundary, type FallbackProps } from 'react-error-boundary';
import { AlertTriangle, RotateCcw, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';

const RouteErrorFallback: React.FC<FallbackProps> = ({
  error,
  resetErrorBoundary,
}) => {
  return (
    <div className="flex min-h-[400px] w-full flex-col items-center justify-center p-6 text-center">
      <div className="rounded-sm border border-destructive/25 bg-destructive/10 text-destructive p-4 shadow-xs">
        <AlertTriangle className="h-10 w-10 stroke-[1.75]" />
      </div>
      <h2 className="mt-4 text-xl font-bold tracking-tight text-foreground">
        Something went wrong on this screen
      </h2>
      <p className="mt-2 max-w-md text-xs text-muted-foreground bg-muted/60 p-2.5 rounded-lg border border-border">
        {error instanceof Error ? error.message : 'An unexpected error occurred'}
      </p>
      <div className="mt-6 flex items-center gap-3">
        <Button
          onClick={resetErrorBoundary}
          variant="default"
          size="default"
        >
          <RotateCcw className="h-4 w-4 mr-1.5" />
          Try Again
        </Button>
        <Button
          onClick={() => window.location.reload()}
          variant="outline"
          size="default"
        >
          <RefreshCw className="h-4 w-4 mr-1.5" />
          Reload View
        </Button>
      </div>
    </div>
  );
};

export const RouteErrorBoundary: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  return (
    <ErrorBoundary
      FallbackComponent={RouteErrorFallback}
    >
      {children}
    </ErrorBoundary>
  );
};