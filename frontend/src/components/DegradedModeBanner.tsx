import { TriangleAlert } from 'lucide-react';
const DISCLAIMER='Decision support only. Not a validated diagnostic device. Graph-based reasoning is a heuristic, not a licensed clinical protocol.';
export default function DegradedModeBanner({ active }: { active:boolean }) { return <><div className="scope-disclaimer">{DISCLAIMER}</div>{active ? <div className="degraded"><TriangleAlert size={17}/> AI reasoning unavailable - rule-based fail-safe active. Recommendations remain clinician-reviewable.</div> : null}</>; }
