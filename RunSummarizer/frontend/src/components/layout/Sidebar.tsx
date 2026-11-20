import React from 'react';
import { NavLink } from 'react-router-dom';
import {
  Activity,
  Calendar,
  Home,
  Search,
  Settings,
  TrendingUp,
} from 'lucide-react';
import { BrandLogo } from '../common/BrandLogo';
import { cn } from '@/lib/utils';

const NAV_ITEMS = [
  { to: '/home', label: 'Home', icon: Home },
  { to: '/calendar', label: 'Calendar', icon: Calendar },
  { to: '/activities', label: 'Activities', icon: Activity },
  { to: '/search', label: 'Search', icon: Search },
  { to: '/trends', label: 'Trends', icon: TrendingUp },
  { to: '/settings', label: 'Settings', icon: Settings },
];

export const Sidebar: React.FC = () => {
  return (
    <aside className="hidden md:flex w-64 flex-col border-r border-border bg-sidebar shrink-0 min-h-screen">
      {/* Brand Header with enlarged Logo */}
      <div className="flex h-16 items-center border-b border-border px-5">
        <BrandLogo size="md" showText={true} />
      </div>

      {/* Navigation links with athletic cockpit styling */}
      <nav className="flex-1 space-y-1 p-3">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                cn(
                  'group flex min-h-[44px] items-center gap-3 rounded-md px-3.5 py-2.5 text-xs font-semibold select-none cursor-pointer transition-all duration-150 ease-out active:scale-[0.98] focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-hidden',
                  isActive
                    ? 'bg-muted text-foreground border-l-3 border-[#FC5200] font-bold shadow-xs'
                    : 'text-muted-foreground hover:bg-muted/60 hover:text-foreground'
                )
              }
            >
              {({ isActive }) => (
                <>
                  <Icon
                    className={cn(
                      'h-4 w-4 shrink-0 transition-colors',
                      isActive ? 'text-[#FC5200]' : 'text-muted-foreground group-hover:text-foreground'
                    )}
                  />
                  <span>{item.label}</span>
                </>
              )}
            </NavLink>
          );
        })}
      </nav>
    </aside>
  );
};
