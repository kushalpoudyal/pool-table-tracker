import React from 'react';

export default function TableArt() {
  return <svg className="table-art" viewBox="0 0 360 200" aria-hidden="true">
    <defs>
      <pattern id="felt" width="5" height="5" patternUnits="userSpaceOnUse"><path d="M1 1h.5" stroke="#aadac2" opacity=".35"/></pattern>
      <radialGradient id="ball" cx=".28" cy=".22" r=".82"><stop stopColor="#515e53"/><stop offset="1" stopColor="#111c19"/></radialGradient>
    </defs>
    <g transform="rotate(-13 180 100)">
      <rect x="14" y="23" width="337" height="165" rx="14" fill="#0b3329" opacity=".6"/>
      <rect x="12" y="13" width="337" height="165" rx="14" fill="#233d32" stroke="#a1af7b" strokeWidth="2"/>
      <rect x="24" y="25" width="313" height="141" rx="5" fill="#43806a" stroke="#73947c" strokeWidth="4"/>
      <rect x="24" y="25" width="313" height="141" fill="url(#felt)"/>
      {[[26,26],[181,23],[335,26],[26,163],[181,166],[335,163]].map(([x,y])=><circle key={`${x}-${y}`} cx={x} cy={y} r="8" fill="#142b24"/>)}
      {[65,101,140,220,260,300].map(x=><path key={x} d={`M${x} 18v2m0 149v2`} stroke="#e1c798" strokeWidth="2"/>)}
      <path d="M101 113l74-37 60 41" fill="none" stroke="#e3e3bb" strokeDasharray="4 5" opacity=".65"/>
      <path d="M-23 169l117-53" stroke="#233d32" strokeWidth="6"/><path d="M-23 166l117-53" stroke="#d7bb89" strokeWidth="4"/>
      <circle cx="105" cy="111" r="9" fill="#faf2d8"/>
      <circle cx="179" cy="74" r="11" fill="url(#ball)"/><circle cx="177" cy="72" r="5.8" fill="#f3eedb"/>
      <text x="177" y="75" textAnchor="middle" fontSize="8" fontWeight="bold" fill="#1e3028">8</text>
      <circle cx="248" cy="120" r="10" fill="#e9ac45"/><circle cx="246" cy="117" r="3" fill="#ffe4a3"/>
    </g>
  </svg>;
}
