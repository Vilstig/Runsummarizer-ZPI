import React from 'react';
import { Link } from 'react-router-dom';
import { Zap } from 'lucide-react';
import { cn } from '@/lib/utils';

export interface BrandLogoProps {
  className?: string;
  showText?: boolean;
  size?: 'sm' | 'md' | 'lg' | 'xl';
}

export const BrandLogo: React.FC<BrandLogoProps> = ({
  className,
  showText = true,
  size = 'md',
}) => {
  const [imgError, setImgError] = React.useState(false);

  return (
    <Link
      to="/home"
      className={cn(
        'group inline-flex items-center gap-3 select-none transition-transform duration-150 active:scale-[0.97] touch-manipulation focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-hidden rounded-sm',
        className
      )}
      aria-label="RunSummarizer - Go to Home"
    >
      {/* Pure logo container without border frame */}
      <div
        className={cn(
          'flex items-center justify-center rounded-sm shrink-0 overflow-hidden',
          size === 'sm' && 'h-11 w-11',
          size === 'md' && 'h-12 w-12',
          size === 'lg' && 'h-16 w-16',
          size === 'xl' && 'h-20 w-20'
        )}
      >
        {!imgError ? (
          <img
            src="/logo.jpg"
            alt="RunSummarizer Logo"
            className="h-full w-full object-contain rounded-sm"
            onError={() => setImgError(true)}
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center bg-primary rounded-sm text-primary-foreground">
            <Zap
              className={cn(
                'fill-current text-white',
                size === 'sm' && 'h-5 w-5',
                size === 'md' && 'h-6 w-6',
                size === 'lg' && 'h-8 w-8',
                size === 'xl' && 'h-10 w-10'
              )}
            />
          </div>
        )}
      </div>

      {showText && (
        <span
          className={cn(
            'font-extrabold tracking-tight text-foreground block group-hover:text-primary transition-colors leading-none',
            size === 'sm' && 'text-base sm:text-lg',
            size === 'md' && 'text-lg sm:text-xl',
            (size === 'lg' || size === 'xl') && 'text-2xl'
          )}
        >
          RunSummarizer
        </span>
      )}
    </Link>
  );
};