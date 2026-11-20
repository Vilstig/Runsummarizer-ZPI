import React from 'react';
import { NavLink } from 'react-router-dom';
import {
  Activity,
  Calendar,
  Home,
  Settings,
  TrendingUp,
} from 'lucide-react';
import { cn } from '@/lib/utils';

const MOBILE_NAV_ITEMS = [
  { to: '/home', label: 'Home', icon: Home },
  { to: '/calendar', label: 'Calendar', icon: Calendar },
  { to: '/activities', label: 'Activities', icon: Activity },
  { to: '/trends', label: 'Trends', icon: TrendingUp },
  { to: '/settings', label: 'Settings', icon: Settings },
];

export const BottomNav: React.FC = () => {
  return (
    <nav
      aria-label="Mobile Navigation"
      className="fixed bottom-0 inset-x-0 z-40 flex items-center justify-around border-t border-border bg-background/95 backdrop-blur-md pb-[env(safe-area-inset-bottom,0px)] pt-1 md:hidden shadow-lg"
    >
      {MOBILE_NAV_ITEMS.map((item) => {
        const Icon = item.icon;
        return (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              cn(
                'group flex min-h-[48px] min-w-[50px] flex-1 flex-col items-center justify-center gap-1 py-1 text-center transition-all duration-150 ease-out select-none touch-manipulation active:scale-95 focus-visible:ring-1 focus-visible:ring-primary focus-visible:outline-hidden',
                isActive
                  ? 'text-[#FC5200]'
                  : 'text-muted-foreground hover:text-foreground'
              )
            }
          >
            {({ isActive }) => (
              <>
                <div
                  className={cn(
                    'flex h-7 w-10 items-center justify-center rounded-md transition-all duration-150',
                    isActive ? 'bg-[#FC5200]/10 text-[#FC5200]' : 'group-hover:bg-muted/50'
                  )}
                >
                  <Icon
                    className={cn(
                      'h-4 w-4 transition-transform',
                      isActive ? 'text-[#FC5200]' : 'text-muted-foreground'
                    )}
                  />
                </div>
                <span
                  className={cn(
                    'text-[11px] font-medium tracking-tight leading-none',
                    isActive ? 'font-bold text-[#FC5200]' : 'text-muted-foreground'
                  )}
                >
                  {item.label}
                </span>
              </>
            )}
          </NavLink>
        );
      })}
    </nav>
  );
};
