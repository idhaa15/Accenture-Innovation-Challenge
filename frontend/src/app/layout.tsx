import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = { title: 'PatientTriage.ai', description: 'Safety-first clinical decision support prototype' };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="en"><body>{children}</body></html>; }
