import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  Package,
  Layers,
  Cog,
  Settings,
  Calculator,
  Store,
  Users,
  Tags,
  FolderHeart,
  ClipboardList,
  BookOpen,
  Inbox,
  UserRound,
  ScrollText,
  Receipt,
} from 'lucide-react';
import { useAuth } from '../lib/auth';
import BrandLogo from './BrandLogo';

export default function Sidebar({ onLinkClick }) {
  const { isAdmin, user } = useAuth();
  const isWriter = user?.role === 'writer';

  const navItems = [
    // Writer sees only blog
    ...(isWriter
      ? [
          { path: '/admin/posts', label: 'وبلاگ', icon: BookOpen },
          { path: '/', label: 'کاتالوگ', icon: Store },
        ]
      : [
          { path: '/dashboard', label: 'داشبورد', icon: LayoutDashboard },
          { path: '/custom-orders', label: 'سفارشات سایت', icon: Inbox },
          { path: '/orders', label: 'سفارش‌ها', icon: ClipboardList },
          { path: '/commerce-admin', label: 'فاکتور و پرداخت', icon: Receipt },
          { path: '/customers', label: 'مشتریان', icon: UserRound },
          { path: '/products', label: 'محصولات', icon: Package },
          { path: '/materials', label: 'مواد', icon: Layers },
          { path: '/machines', label: 'ماشین‌ها', icon: Cog },
          { path: '/categories', label: 'دسته‌بندی‌ها', icon: Tags },
          { path: '/collections', label: 'کالکشن‌ها', icon: FolderHeart },
          { path: '/admin/posts', label: 'وبلاگ', icon: BookOpen },
          { path: '/calculator', label: 'ماشین حساب', icon: Calculator },
          { path: '/', label: 'کاتالوگ', icon: Store },
        ]),
    ...(isAdmin
      ? [
          { path: '/settings', label: 'تنظیمات', icon: Settings },
          { path: '/users', label: 'کاربران', icon: Users },
          { path: '/audit', label: 'گزارش فعالیت', icon: ScrollText },
        ]
      : []),
  ];

  return (
    <nav
      className="flex flex-col h-full overflow-y-auto border-l"
      style={{
        backgroundColor: 'var(--bg-sidebar)',
        borderColor: 'var(--border-color)',
      }}
    >
      <div
        className="flex items-center gap-3 px-5 py-5 border-b"
        style={{ borderColor: 'var(--border-color)' }}
      >
        <BrandLogo height={60}>
          <div className="flex items-center gap-3">
            <div
              className="flex items-center justify-center w-[60px] h-[60px] rounded-full font-bold text-white text-lg shrink-0"
              style={{
                background: 'linear-gradient(135deg, #6366f1, #818cf8)',
                boxShadow: '0 0 18px rgba(129, 140, 248, 0.45)',
              }}
            >
              S
            </div>
            <div className="min-w-0">
              <h2 className="font-bold text-base leading-tight truncate" style={{ color: 'var(--text-primary)' }}>
                Spaghetti
              </h2>
              <p className="text-[11px] truncate" style={{ color: 'var(--text-sidebar)' }}>
                سیستم مدیریت
              </p>
            </div>
          </div>
        </BrandLogo>
      </div>

      <div className="flex-1 px-3 py-4 space-y-1">
        {navItems.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === '/'}
            onClick={onLinkClick}
            className="flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-sm font-medium transition-all duration-200"
            style={({ isActive }) => ({
              backgroundColor: isActive ? 'var(--bg-sidebar-active)' : 'transparent',
              color: isActive ? 'var(--text-sidebar-active)' : 'var(--text-sidebar)',
              border: isActive
                ? '1px solid color-mix(in srgb, var(--accent) 50%, transparent)'
                : '1px solid transparent',
              boxShadow: isActive ? '0 0 22px rgba(129, 140, 248, 0.14)' : 'none',
              minHeight: 44,
            })}
          >
            {({ isActive }) => (
              <>
                <span
                  className="w-1.5 h-1.5 rounded-full shrink-0"
                  style={{
                    backgroundColor: isActive ? 'var(--accent-2, #22d3ee)' : 'var(--text-muted)',
                    boxShadow: isActive ? '0 0 8px var(--accent-2, #22d3ee)' : 'none',
                  }}
                />
                <item.icon size={18} style={{ color: 'inherit' }} />
                <span className="truncate">{item.label}</span>
              </>
            )}
          </NavLink>
        ))}
      </div>

      <div className="px-4 py-4 border-t" style={{ borderColor: 'var(--border-color)' }}>
        <div
          className="flex items-center gap-3 px-3 py-2.5 rounded-xl"
          style={{
            backgroundColor: 'var(--bg-tertiary)',
            border: '1px solid var(--border-color)',
          }}
        >
          <div
            className="w-8 h-8 rounded-full shrink-0 flex items-center justify-center text-xs font-bold"
            style={{
              backgroundColor: 'var(--accent-light)',
              color: 'var(--accent)',
              border: '1px solid color-mix(in srgb, var(--accent) 40%, transparent)',
            }}
          >
            {(user?.username || 'A').slice(0, 1).toUpperCase()}
          </div>
          <div className="min-w-0 flex-1 text-right">
            <p className="text-xs font-semibold truncate" style={{ color: 'var(--text-primary)' }}>
              {isAdmin ? 'مدیر سیستم' : 'کاربر'}
            </p>
            <p className="text-[11px] truncate" style={{ color: 'var(--text-muted)' }}>
              {user?.username || 'admin'}
            </p>
          </div>
        </div>
      </div>
    </nav>
  );
}
