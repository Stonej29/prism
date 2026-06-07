// PRISM mark: a white beam runs into the centre of a centred prism and refracts
// outward into a spectrum whose rays terminate in graph nodes — light/refraction
// + knowledge constellation. Colours reuse the source palette.
export function Logo({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M16 6 L8 21 L24 21 Z" stroke="#e6e9ef" strokeWidth="1.6" strokeLinejoin="round" fill="rgba(110,168,254,0.12)" />
      <path d="M2 16 H16" stroke="#e6e9ef" strokeWidth="1.6" strokeLinecap="round" />
      <g strokeWidth="1.5" strokeLinecap="round">
        <path d="M16 16 L27 7" stroke="#f0776a" />
        <path d="M16 16 L29 11.5" stroke="#f5c542" />
        <path d="M16 16 L30 16" stroke="#4ec9a8" />
        <path d="M16 16 L29 20.5" stroke="#5cb8e6" />
        <path d="M16 16 L27 25" stroke="#a78bfa" />
      </g>
      <g>
        <circle cx="27" cy="7" r="1.7" fill="#f0776a" />
        <circle cx="29" cy="11.5" r="1.7" fill="#f5c542" />
        <circle cx="30" cy="16" r="1.7" fill="#4ec9a8" />
        <circle cx="29" cy="20.5" r="1.7" fill="#5cb8e6" />
        <circle cx="27" cy="25" r="1.7" fill="#a78bfa" />
      </g>
    </svg>
  );
}
