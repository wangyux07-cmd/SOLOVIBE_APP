type Leg = { route: { polyline?: string[] }; to_name: string };

export default function ItineraryRouteSketch({ legs }: { legs: Leg[] }) {
  const paths = legs.map(leg => (leg.route.polyline ?? []).map(point => point.split(',').map(Number))
    .filter((point): point is [number, number] => point.length === 2 && point.every(Number.isFinite)));
  const all = paths.flat();
  if (all.length < 2) return <p className="mt-3 text-xs text-[#a8b6ac]">路线有时长证据，但缺少可绘制折线；请打开高德逐段核对。</p>;
  const scale = Math.cos(all.reduce((sum, point) => sum + point[1], 0) / all.length * Math.PI / 180);
  const xs = all.map(point => point[0] * scale);
  const ys = all.map(point => point[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const spanX = Math.max(maxX - minX, 0.00001), spanY = Math.max(maxY - minY, 0.00001);
  const factor = Math.min(350 / spanX, 170 / spanY);
  const offsetX = (400 - spanX * factor) / 2, offsetY = (220 - spanY * factor) / 2;
  const point = ([longitude, latitude]: [number, number]) =>
    `${(offsetX + (longitude * scale - minX) * factor).toFixed(1)},${(220 - offsetY - (latitude - minY) * factor).toFixed(1)}`;
  const colors = ['#bdd7a2', '#8fc7d8', '#d8b9e8', '#f7ba7f'];
  return <div className="mt-4 rounded-lg border border-white/10 bg-[#121d19] p-2">
    <svg viewBox="0 0 400 220" role="img" aria-label="按游览顺序连接各站的高德步行道路折线" className="w-full">
      {paths.map((path, index) => path.length >= 2 &&
        <polyline key={index} points={path.map(point).join(' ')} fill="none"
          stroke={colors[index % colors.length]} strokeWidth="3" strokeLinecap="round" />)}
      {paths.slice(0, -1).map((path, index) => path.length >= 2 &&
        <g key={index}><circle cx={point(path[path.length - 1]).split(',')[0]}
          cy={point(path[path.length - 1]).split(',')[1]} r="9" fill="#19231d" stroke={colors[index % colors.length]} />
          <text x={Number(point(path[path.length - 1]).split(',')[0]) - 3}
            y={Number(point(path[path.length - 1]).split(',')[1]) + 3} fill="white" fontSize="10">{index + 1}</text></g>)}
    </svg>
    <p className="text-[11px] text-[#a8b6ac]">各色线段按 1 → 2 → 3 → 返程顺序连接；为高德道路折线示意，无道路底图。</p>
  </div>;
}
