import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

export const badgeVariants = cva(
  'inline-flex items-center gap-1.5 rounded-sm border px-2 py-0.5 text-[11px] font-semibold transition-all duration-150 ease-out focus:outline-hidden focus:ring-1 focus:ring-ring select-none',
  {
    variants: {
      variant: {
        default:
          'border-transparent bg-primary text-primary-foreground shadow-xs',
        secondary:
          'border-border bg-muted/60 text-foreground',
        destructive:
          'border-destructive/25 bg-destructive/10 text-destructive',
        tint:
          'border-primary/25 bg-primary/10 text-primary',
        outline:
          'border-border bg-card text-foreground',
        surface:
          'border-border bg-background text-muted-foreground',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

export const Badge: React.FC<BadgeProps> = ({ className, variant, ...props }) => {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  );
};
Badge.displayName = 'Badge';
