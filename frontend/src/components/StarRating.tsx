import { useState } from "react";
import { Star } from "lucide-react";

interface Props {
  value: number | null;
  onRate?: (stars: number) => void;
  size?: number;
  busy?: boolean;
}

/** 1–5 звёзд. Без onRate — только отображение. */
export default function StarRating({ value, onRate, size = 18, busy }: Props) {
  const [hover, setHover] = useState<number | null>(null);
  const shown = hover ?? value ?? 0;
  return (
    <div className="inline-flex items-center gap-0.5" onMouseLeave={() => setHover(null)}>
      {[1, 2, 3, 4, 5].map((i) => (
        <button
          key={i}
          type="button"
          disabled={!onRate || busy}
          title={onRate ? `${i} из 5` : undefined}
          onMouseEnter={() => onRate && setHover(i)}
          onClick={() => onRate?.(i)}
          className={`p-0.5 transition-transform ${onRate ? "hover:scale-110" : "cursor-default"}`}
        >
          <Star size={size} className={i <= shown ? "fill-warn text-warn" : "text-dim"} />
        </button>
      ))}
    </div>
  );
}
