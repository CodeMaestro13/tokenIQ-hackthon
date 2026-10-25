import { create } from 'zustand';
import { persist } from 'zustand/middleware';
type UI = {
  connection: string;
  collapsed: boolean;
  selectedDecision: string | null;
  setConnection: (value: string) => void;
  toggle: () => void;
  inspect: (id: string | null) => void;
};
export const useUI = create<UI>((set) => ({
  connection: 'Connecting',
  collapsed: false,
  selectedDecision: null,
  setConnection: (connection) => set({ connection }),
  toggle: () => set((s) => ({ collapsed: !s.collapsed })),
  inspect: (selectedDecision) => set({ selectedDecision }),
}));
type Preferences = {
  precision: number;
  notifications: boolean;
  setPrecision: (value: number) => void;
  setNotifications: (value: boolean) => void;
};
export const usePreferences = create<Preferences>()(
  persist(
    (set) => ({
      precision: 2,
      notifications: true,
      setPrecision: (precision) => set({ precision }),
      setNotifications: (notifications) => set({ notifications }),
    }),
    { name: 'algolens-preferences' },
  ),
);
