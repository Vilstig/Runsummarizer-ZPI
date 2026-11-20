import React from 'react';
import { BrandLogo } from './BrandLogo';
import { cn } from '@/lib/utils';

export interface BrandHeaderProps {
  className?: string;
  subtitle?: string;
}

export const BrandHeader: React.FC<BrandHeaderProps> = ({
  className,
  subtitle = 'AI summaries for your runs',
}) => {
  return (
    <div className={cn('flex flex-col items-center gap-1.5 text-center', className)}>
      <BrandLogo size="lg" showText={true} />
      {subtitle && (
        <span className="text-xs text-muted-foreground font-medium mt-0.5">
          {subtitle}
        </span>
      )}
    </div>
  );
};