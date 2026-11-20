import React from 'react';
import { cn } from '@/lib/utils';

export interface LoadingSpinnerProps {
  size?: 'sm' | 'md' | 'lg';
  className?: string;
  label?: string;
}

/**
 * Animated athletic runner loading component.
 * Features a stylized sprinting runner silhouette with natural stride bounce keyframes,
 * dynamic speed trails, and horizontal running track dashes using the brand orange (#FC5200) with deeper shades for depth.
 */
export const LoadingSpinner: React.FC<LoadingSpinnerProps> = ({
  size = 'md',
  className,
  label,
}) => {
  const isInline = size === 'sm' && !label;

  // Responsive SVG sizing matrix
  const svgDimensions = {
    sm: 'w-4 h-4',
    md: 'w-14 h-14 sm:w-16 sm:h-16',
    lg: 'w-20 h-20 sm:w-24 sm:h-24',
  }[size];

  return (
    <div
      role="status"
      aria-label={label || 'Loading...'}
      className={cn(
        isInline
          ? 'inline-flex items-center justify-center shrink-0'
          : 'flex flex-col items-center justify-center gap-3 p-4',
        className
      )}
    >
      <div className="relative flex items-center justify-center">
        <svg
          viewBox="0 0 64 64"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          className={cn(svgDimensions, 'shrink-0 select-none overflow-visible')}
        >
          {/* Stylized Running Athlete (Clean static silhouette) */}
          <g>
            {/* Runner Head */}
            <circle cx="43" cy="13" r="4.5" className="fill-primary" />

            {/* Torso / Core with forward lean */}
            <path
              d="M42 19 L33 33"
              className="stroke-primary"
              strokeWidth="4.5"
              strokeLinecap="round"
            />

            {/* Lead Arm (pumping forward) */}
            <path
              d="M39 23 L48 27 L45 33"
              className="stroke-primary"
              strokeWidth="3.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />

            {/* Rear Arm (driving back) */}
            <path
              d="M38 23 L28 21 L23 27"
              className="stroke-[#C2410C] dark:stroke-[#7C2D12]"
              strokeWidth="3.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />

            {/* Lead Leg (striding forward) */}
            <path
              d="M33 33 L42 41 L49 47"
              className="stroke-primary"
              strokeWidth="3.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            />

            {/* Rear Leg (push-off drive) */}
            <path
              d="M33 33 L24 39 L14 42"
              className="stroke-[#C2410C] dark:stroke-[#7C2D12]"
              strokeWidth="3.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </g>

          {/* Dynamic Horizontal Stride Track Lines (dashing underfoot) */}
          {size !== 'sm' && (
            <g aria-hidden="true">
              <line
                x1="4"
                y1="52"
                x2="60"
                y2="52"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeDasharray="8 6"
                className="stroke-primary animate-ground-track"
              />
              <line
                x1="12"
                y1="56"
                x2="52"
                y2="56"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeDasharray="6 8"
                className="stroke-[#FED7AA] dark:stroke-[#431407] animate-ground-track-slow"
              />
            </g>
          )}
        </svg>
      </div>

      {label && (
        <span
          className={cn(
            'text-xs tracking-tight text-muted-foreground text-center animate-pulse font-medium select-none',
            size === 'lg' && 'text-sm'
          )}
        >
          {label}
        </span>
      )}
    </div>
  );
};