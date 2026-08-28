import { TriangleAlert } from 'lucide-react';
const DISCLAIMER='Decision support only. Not a validated diagnostic device. Graph-based reasoning is a heuristic, not a licensed clinical protocol.';
export default function DegradedModeBanner({ active: _active }: { active:boolean }) { return <div className="scope-disclaimer">{DISCLAIMER}</div>; }
