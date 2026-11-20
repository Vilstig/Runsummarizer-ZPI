import React from 'react';
import { Check, Copy } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';

export interface CopyButtonProps {
  text: string;
  /** Tooltip and accessible name, e.g. 'Copy to clipboard'. */
  label?: string;
  className?: string;
}

/**
 * Icon-only copy button with a tooltip. The tooltip shows on hover and keyboard
 * focus; on touch (no hover) it appears as 'Copied' after a tap.
 */
export const CopyButton: React.FC<CopyButtonProps> = ({
  text,
  label = 'Copy to clipboard',
  className,
}) => {
  const [copied, setCopied] = React.useState(false);

  React.useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1500);
    return () => window.clearTimeout(timer);
  }, [copied]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      toast.error('Could not copy to clipboard');
    }
  };

  return (
    <div className={cn('group relative inline-flex', className)}>
      <button
        type="button"
        onClick={handleCopy}
        aria-label={label}
        className="flex h-11 w-11 sm:h-9 sm:w-9 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground touch-manipulation cursor-pointer focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-primary"
      >
        {copied ? (
          <Check className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
        ) : (
          <Copy className="h-4 w-4" />
        )}
      </button>

      {/* Visual only: the button's aria-label and the live region below carry the text */}
      <span
        aria-hidden="true"
        className={cn(
          'pointer-events-none absolute right-0 bottom-full mb-1.5 whitespace-nowrap rounded-md bg-foreground px-2 py-1 text-xs font-medium text-background shadow-md transition-opacity',
          copied
            ? 'opacity-100'
            : 'opacity-0 group-hover:opacity-100 group-has-[:focus-visible]:opacity-100'
        )}
      >
        {copied ? 'Copied' : label}
      </span>
      <span className="sr-only" aria-live="polite">
        {copied ? 'Copied to clipboard' : ''}
      </span>
    </div>
  );
};
