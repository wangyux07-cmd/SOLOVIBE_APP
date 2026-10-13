type Route = { polyline?: string[] } | null | undefined;

function read(route: Route): [number, number][] {
  return (route?.polyline ?? []).map(point => point.split(',').map(Number))
    .filter((pair): pair is [number, number] => pair.length === 2 && pair.every(Number.isFinite));
}

export default function RouteSketch({ outbound, returning }: { outbound: Route; returning: Route }) {
  const out = read(outbound);
  const back = read(returning);
  if (out.length < 2 && back.length < 2) return <p className="text-xs text-[#a8b6ac]">本次未取得可绘制的道路折线；可打开高德核对路线。</p>;
  const all = [...out, ...back];
  const centerLat = all.reduce((sum, point) => sum + point[1], 0) / all.length;
  const scale = Math.cos(centerLat * Math.PI / 180);
  const xs = all.map(point => point[0] * scale);
  const ys = all.map(point => point[1]);
  const minX = Math.min(...xs); const maxX = Math.max(...xs);
  const minY = Math.min(...ys); const maxY = Math.max(...ys);
  const spanX = Math.max(maxX - minX, 0.00001);
  const spanY = Math.max(maxY - minY, 0.00001);
  const factor = Math.min(350 / spanX, 170 / spanY);
  const offsetX = (400 - spanX * factor) / 2;
  const offsetY = (220 - spanY * factor) / 2;
  const project = ([lng, lat]: [number, number]) =>
    `${(offsetX + (lng * scale - minX) * factor).toFixed(1)},${(220 - offsetY - (lat - minY) * factor).toFixed(1)}`;
  return <div className="mt-3 rounded-lg border border-white/10 bg-[#121d19] p-2">
    <svg viewBox="0 0 400 220" role="img" aria-label="高德步行道路折线示意：绿色去程，橙色返程" className="w-full">
      {out.length >= 2 && <polyline points={out.map(project).join(' ')} fill="none" stroke="#bdd7a2" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />}
      {back.length >= 2 && <polyline points={back.map(project).join(' ')} fill="none" stroke="#f7ba7f" strokeWidth="2" strokeDasharray="5 4" strokeLinecap="round" strokeLinejoin="round" />}
      {out.length > 0 && <circle cx={project(out[0]).split(',')[0]} cy={project(out[0]).split(',')[1]} r="5" fill="#bdd7a2" />}
      {out.length > 0 && <circle cx={project(out[out.length - 1]).split(',')[0]} cy={project(out[out.length - 1]).split(',')[1]} r="5" fill="#ffffff" />}
    </svg>
    <p className="text-[11px] text-[#a8b6ac]">高德返回的道路折线示意，不含道路底图。实线为去程，虚线为返程。</p>
  </div>;
}
