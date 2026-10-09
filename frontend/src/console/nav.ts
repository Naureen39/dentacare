import {
  BookOpenText,
  CalendarDays,
  ClipboardList,
  CreditCard,
  History,
  LayoutDashboard,
  MessagesSquare,
  Settings as SettingsIcon,
  Stethoscope,
  UserCog,
  Users,
  type LucideIcon,
} from 'lucide-react'

import type { Role } from '@/lib/auth'

export interface NavItem {
  to: string
  label: string
  /** What a dentist calls it, when different. */
  dentistLabel?: string
  icon: LucideIcon
  roles: Role[]
  end?: boolean
}

const staff: Role[] = ['admin', 'receptionist', 'dentist']
const frontDesk: Role[] = ['admin', 'receptionist']

export const workNav: NavItem[] = [
  {
    to: '/staff',
    label: 'Today',
    dentistLabel: 'My day',
    icon: ClipboardList,
    roles: staff,
    end: true,
  },
  {
    to: '/staff/schedule',
    label: 'Schedule',
    dentistLabel: 'My schedule',
    icon: CalendarDays,
    roles: staff,
  },
  { to: '/staff/patients', label: 'Patients', icon: Users, roles: frontDesk },
  { to: '/staff/billing', label: 'Billing desk', icon: CreditCard, roles: frontDesk },
]

export const adminNav: NavItem[] = [
  { to: '/admin/analytics', label: 'Analytics', icon: LayoutDashboard, roles: ['admin'] },
  { to: '/admin/staff', label: 'Staff', icon: UserCog, roles: ['admin'] },
  { to: '/admin/services', label: 'Services and pricing', icon: Stethoscope, roles: ['admin'] },
  { to: '/admin/dentists', label: 'Dentists and hours', icon: CalendarDays, roles: ['admin'] },
  { to: '/admin/knowledge', label: 'Knowledge base', icon: BookOpenText, roles: ['admin'] },
  { to: '/admin/chats', label: 'Chat review', icon: MessagesSquare, roles: ['admin'] },
  { to: '/admin/settings', label: 'Settings', icon: SettingsIcon, roles: ['admin'] },
  { to: '/admin/audit', label: 'Audit log', icon: History, roles: ['admin'] },
]

export const sectionsFor = (role: Role) => {
  const work = workNav.filter((i) => i.roles.includes(role))
  const admin = adminNav.filter((i) => i.roles.includes(role))
  return [
    { title: 'Work', items: work },
    ...(admin.length ? [{ title: 'Administration', items: admin }] : []),
  ]
}

export const labelFor = (item: NavItem, role: Role) =>
  role === 'dentist' && item.dentistLabel ? item.dentistLabel : item.label
