import { TriangleAlert } from 'lucide-react';
export default function DegradedModeBanner({ active }: { active:boolean }) { return active ? <div className="degraded"><TriangleAlert size={17}/> AI reasoning unavailable - rule-based fail-safe active. Recommendations remain clinician-reviewable.</div> : null; }
