import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

export const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-xs font-semibold select-none cursor-pointer disabled:pointer-events-none disabled:opacity-50 transition-all duration-150 ease-out active:scale-[0.98] focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 [&_svg]:pointer-events-none [&_svg]:size-3.5 [&_svg]:shrink-0 touch-manipulation',
  {
    variants: {
      variant: {
        default:
          'bg-[#FC5200] text-white shadow-xs hover:bg-[#E04900] active:bg-[#C93F00] font-bold tracking-tight',
        destructive:
          'bg-destructive text-destructive-foreground shadow-xs hover:bg-destructive/90 active:bg-destructive/80 font-semibold',
        outline:
          'border border-border bg-card text-foreground shadow-xs hover:bg-muted hover:border-neutral-400 dark:hover:border-neutral-600',
        secondary:
          'bg-muted text-foreground border border-border shadow-xs hover:bg-muted/80',
        ghost:
          'text-foreground hover:bg-muted hover:text-foreground',
        link:
          'text-[#FC5200] underline-offset-4 hover:underline hover:text-[#E04900]',
      },
      size: {
        default: 'h-9 px-4 py-2 text-xs',
        sm: 'h-7 rounded-sm px-2.5 text-xs',
        lg: 'h-10 rounded-lg px-5 text-sm',
        icon: 'h-8 w-8 rounded-md p-0',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button';
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    );
  }
);
Button.displayName = 'Button';
