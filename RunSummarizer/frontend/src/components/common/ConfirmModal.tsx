import React from 'react';
import { AlertCircle } from 'lucide-react';
import { LoadingSpinner } from './LoadingSpinner';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

export interface ConfirmModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: 'default' | 'destructive';
  onConfirm: () => void;
  loading?: boolean;
}

export const ConfirmModal: React.FC<ConfirmModalProps> = ({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  variant = 'default',
  onConfirm,
  loading = false,
}) => {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md rounded-md border border-border bg-card">
        <div className="flex items-start gap-4">
          {variant === 'destructive' && (
            <div className="rounded-sm border border-destructive/25 bg-destructive/10 text-destructive p-2 shrink-0">
              <AlertCircle className="h-5 w-5" />
            </div>
          )}
          <DialogHeader className="flex-1 space-y-1 text-left sm:text-left">
            <DialogTitle className="text-base text-foreground font-semibold">{title}</DialogTitle>
            <DialogDescription className="text-xs text-muted-foreground">{description}</DialogDescription>
          </DialogHeader>
        </div>

        <DialogFooter className="mt-4 gap-2 sm:gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={loading}
            className="min-h-[44px] sm:min-h-[36px] rounded-sm touch-manipulation"
          >
            {cancelLabel}
          </Button>
          <Button
            type="button"
            variant={variant === 'destructive' ? 'destructive' : 'default'}
            onClick={onConfirm}
            disabled={loading}
            className="min-h-[44px] sm:min-h-[36px] rounded-sm touch-manipulation font-semibold"
          >
            {loading ? <LoadingSpinner size="sm" className="p-0 mr-2" /> : null}
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};