// PRISM mark: a white beam entering a prism and refracting into a spectrum whose
// rays terminate in graph nodes — light/refraction + knowledge constellation.
// Colors reuse the source palette so it reads as the same family as the graph.
export function Logo({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M11 5 L4 26 L18 26 Z" stroke="#e6e9ef" strokeWidth="1.6" strokeLinejoin="round" fill="rgba(110,168,254,0.12)" />
      <path d="M0 17 H8" stroke="#e6e9ef" strokeWidth="1.6" strokeLinecap="round" />
      <g strokeWidth="1.5" strokeLinecap="round">
        <path d="M13 17 L27 8" stroke="#f0776a" />
        <path d="M13 17 L29 13" stroke="#f5c542" />
        <path d="M13 17 L29 18" stroke="#4ec9a8" />
        <path d="M13 17 L29 23" stroke="#5cb8e6" />
        <path d="M13 17 L27 28" stroke="#a78bfa" />
      </g>
      <g>
        <circle cx="27" cy="8" r="1.8" fill="#f0776a" />
        <circle cx="29" cy="13" r="1.8" fill="#f5c542" />
        <circle cx="29" cy="18" r="1.8" fill="#4ec9a8" />
        <circle cx="29" cy="23" r="1.8" fill="#5cb8e6" />
        <circle cx="27" cy="28" r="1.8" fill="#a78bfa" />
      </g>
    </svg>
  );
}
