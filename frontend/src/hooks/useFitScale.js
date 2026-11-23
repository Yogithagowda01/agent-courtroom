import { useEffect, useState } from 'react';

// Scales the fixed-size window so it always fits the browser, with nothing cut off.
export function useFitScale(width, height, pad = 20, max = 1.6) {
  const calc = () =>
    Math.max(0.35, Math.min((window.innerWidth - pad * 2) / width, (window.innerHeight - pad * 2) / height, max));
  const [scale, setScale] = useState(calc);

  useEffect(() => {
    let raf = 0;
    const onResize = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => setScale(calc()));
    };
    window.addEventListener('resize', onResize);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', onResize);
    };
  }, []);

  return scale;
}
