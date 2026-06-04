import { P } from "../theme";

export function TextAction({
  children,
  busy = false,
  danger = false,
  disabled = false,
  title,
  onClick,
}: {
  children: React.ReactNode;
  busy?: boolean;
  danger?: boolean;
  disabled?: boolean;
  title?: string;
  onClick?: () => void | Promise<void>;
}) {
  const inactive = disabled || busy;
  return (
    <>
      <style>{`
        @keyframes prismTextScan {
          0% { background-position: 130% 0; }
          100% { background-position: -130% 0; }
        }
      `}</style>
      <span
        onClick={() => { if (!inactive) void onClick?.(); }}
        title={title}
        style={{
          fontFamily: P.mono,
          fontSize: 11,
          color: danger ? P.arxiv : P.mid,
          cursor: inactive ? "default" : "pointer",
          opacity: disabled ? 0.45 : 1,
          userSelect: "none",
          backgroundImage: busy ? `linear-gradient(90deg, ${P.mid} 0%, ${P.mid} 28%, ${P.hi} 45%, ${P.mid} 62%, ${P.mid} 100%)` : undefined,
          backgroundSize: busy ? "240% 100%" : undefined,
          WebkitBackgroundClip: busy ? "text" : undefined,
          backgroundClip: busy ? "text" : undefined,
          WebkitTextFillColor: busy ? "transparent" : undefined,
          animation: busy ? "prismTextScan 1.15s ease-in-out infinite" : undefined,
        }}
      >
        {children}
      </span>
    </>
  );
}
