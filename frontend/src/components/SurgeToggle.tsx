import { Check, Zap } from 'lucide-react';
export default function SurgeToggle({onClick,disabled,active=false}:{onClick:()=>void;disabled:boolean;active?:boolean}){return <button className="surge" disabled={disabled} onClick={onClick}>{active?<Check size={15}/>:<Zap size={15}/>} {active?'3x surge active · Reset':'Simulate 3x surge'}</button>}
