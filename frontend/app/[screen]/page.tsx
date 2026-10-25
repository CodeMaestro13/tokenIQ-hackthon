import Terminal from '@/components/terminal';
import { notFound } from 'next/navigation';
const screens = [
  'dashboard',
  'trading',
  'strategy',
  'positions',
  'orders',
  'risk',
  'logs',
  'settings',
];
export function generateStaticParams() {
  return screens.map((screen) => ({ screen }));
}
export default async function Page({ params }: { params: Promise<{ screen: string }> }) {
  const { screen } = await params;
  if (!screens.includes(screen)) notFound();
  return <Terminal screen={screen} />;
}
