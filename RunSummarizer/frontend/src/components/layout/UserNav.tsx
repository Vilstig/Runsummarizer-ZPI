import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useClerk, useUser } from '@clerk/clerk-react';
import {
  LogOut,
  Palette,
  Settings,
  ShieldCheck,
  Zap,
} from 'lucide-react';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { ConfirmModal } from '@/components/common/ConfirmModal';

export const UserNav: React.FC = () => {
  const navigate = useNavigate();
  const { user } = useUser();
  const { signOut } = useClerk();
  const [signOutModalOpen, setSignOutModalOpen] = useState(false);

  const initials =
    user?.firstName && user?.lastName
      ? `${user.firstName.charAt(0)}${user.lastName.charAt(0)}`.toUpperCase()
      : user?.firstName
        ? user.firstName.charAt(0).toUpperCase()
        : 'U';

  const handleNavigate = (path: string) => {
    navigate(path);
  };

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            aria-label="User account menu"
            className="flex h-9 w-9 items-center justify-center rounded-full transition-all duration-150 ease-out active:scale-95 focus-visible:outline-hidden focus-visible:ring-1 focus-visible:ring-primary border border-border bg-card hover:border-primary cursor-pointer select-none"
          >
            {user?.imageUrl ? (
              <img
                src={user.imageUrl}
                alt={user.fullName || 'User avatar'}
                className="h-7 w-7 rounded-full object-cover"
              />
            ) : (
              <div className="flex h-7 w-7 items-center justify-center rounded-full bg-muted border border-border text-xs font-semibold text-foreground">
                {initials}
              </div>
            )}
          </button>
        </DropdownMenuTrigger>

        <DropdownMenuContent align="end" className="w-64">
          {/* User details header (menu item, so it is reachable with the keyboard) */}
          <DropdownMenuItem
            onClick={() => handleNavigate('/settings?tab=account')}
            className="gap-3 p-2 rounded-xl cursor-pointer select-none"
          >
            {user?.imageUrl ? (
              <img
                src={user.imageUrl}
                alt={user.fullName || 'User avatar'}
                className="h-8 w-8 rounded-full object-cover border border-border"
              />
            ) : (
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-muted border border-border text-xs font-semibold text-foreground">
                {initials}
              </div>
            )}
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-semibold text-foreground leading-tight">
                {user?.fullName || 'Runner Account'}
              </p>
              <p className="truncate text-xs text-muted-foreground mt-0.5">
                {user?.primaryEmailAddress?.emailAddress}
              </p>
            </div>
          </DropdownMenuItem>

          <DropdownMenuSeparator />

          {/* Unified Settings Links */}
          <DropdownMenuItem
            onClick={() => handleNavigate('/settings?tab=account')}
            className="gap-2.5 cursor-pointer"
          >
            <ShieldCheck className="h-4 w-4 text-muted-foreground shrink-0" />
            <div className="flex flex-col">
              <span className="font-medium text-xs">Manage Account & Security</span>
              <span className="text-xs text-muted-foreground">
                Profile credentials, password, sessions
              </span>
            </div>
          </DropdownMenuItem>

          <DropdownMenuItem
            onClick={() => handleNavigate('/settings?tab=integrations')}
            className="gap-2.5 cursor-pointer"
          >
            <Zap className="h-4 w-4 text-muted-foreground shrink-0" />
            <span className="text-xs font-medium text-foreground">Integrations & Sync</span>
          </DropdownMenuItem>

          <DropdownMenuItem
            onClick={() => handleNavigate('/settings?tab=appearance')}
            className="gap-2.5 cursor-pointer"
          >
            <Palette className="h-4 w-4 text-muted-foreground shrink-0" />
            <span className="text-xs font-medium text-foreground">Theme & Appearance</span>
          </DropdownMenuItem>

          <DropdownMenuItem
            onClick={() => handleNavigate('/settings')}
            className="gap-2.5 cursor-pointer"
          >
            <Settings className="h-4 w-4 text-muted-foreground shrink-0" />
            <span className="text-xs font-medium text-foreground">All Settings</span>
          </DropdownMenuItem>

          <DropdownMenuSeparator />

          {/* Sign Out */}
          <DropdownMenuItem
            onClick={() => setSignOutModalOpen(true)}
            className="gap-2.5 text-destructive focus:text-destructive focus:bg-destructive/10 cursor-pointer"
          >
            <LogOut className="h-4 w-4 shrink-0 text-destructive" />
            <span className="text-xs font-semibold">Sign Out</span>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      {/* Confirmation Modal */}
      <ConfirmModal
        open={signOutModalOpen}
        onOpenChange={setSignOutModalOpen}
        title="Sign Out of Session"
        description="Are you sure you want to sign out of RunSummarizer? You will need to sign in again to access your workouts."
        confirmLabel="Sign Out"
        variant="default"
        onConfirm={() => {
          signOut({ redirectUrl: '/sign-in' });
        }}
      />
    </>
  );
};