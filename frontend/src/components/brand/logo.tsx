import Image from "next/image";

type Size = "sm" | "md" | "lg";
const PX: Record<Size, number> = { sm: 24, md: 32, lg: 48 };

export function Logo({ size = "md", className = "" }: { size?: Size; className?: string }) {
  const px = PX[size];
  return (
    <Image
      src="/logo.svg"
      alt="NotebookLM Reimagined"
      width={px}
      height={px}
      className={className}
      priority
    />
  );
}

export function Wordmark({ size = "md" }: { size?: Size }) {
  const text = size === "lg" ? "text-2xl" : size === "md" ? "text-lg" : "text-sm";
  return (
    <div className="flex items-center gap-2">
      <Logo size={size} />
      <span className={`${text} font-semibold tracking-tight`}>NotebookLM</span>
    </div>
  );
}
